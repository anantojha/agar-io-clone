"""Connects the game world to clients: message handling, the tick loop, and per-client snapshots.

Wire protocol. Control messages are JSON text frames, the per-tick world state is a binary frame
(layout in server/protocol.py).

  client -> server (JSON)
    {"t": "join", "name": str}   start playing, or play again after dying
    {"t": "move", "x": n, "y": n}   world position the cursor points at
    {"t": "split"}   halve every big enough cell, throwing the new halves toward the cursor
    {"t": "eject"}   throw a pellet of mass from every big enough cell toward the cursor

  server -> client (JSON)
    {"t": "welcome", "id": n, "map": n, "tick": n, "snap": ms, "fr": n, "pr": n}
         once, after the first join; snap is the usual time between state frames, fr and pr are
         the radii of food and of ejected pellets
    {"t": "dead", "by": name, "peak": n}   the player was eaten; send "join" to play again
    {"t": "full", "reason": "full" | "ip"}   the server refused the connection, then closes it
"""
import asyncio
import json
import math
import random
import time

from game import Config, Player, World

from .bots import BotManager
from .limits import Limits
from .protocol import encode_state, pack_food

LEADERBOARD_EVERY = 15  # ticks between leaderboard refreshes
LEADERBOARD_SIZE = 10
MAX_MESSAGE_CHARS = 1024
MAX_NAME_CHARS = 16


def clean_name(value) -> str:
    if not isinstance(value, str):
        return "Anonymous"
    name = "".join(ch for ch in value if ch.isprintable()).strip()[:MAX_NAME_CHARS]
    return name or "Anonymous"


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


class FoodBlobs:
    """The wire bytes of each food bucket, rebuilt only when food in that bucket changes.

    Food never moves, so most buckets stay the same for many ticks and a snapshot can join a few
    ready-made byte strings instead of looking at every food item in view.
    """

    def __init__(self, grid):
        self.grid = grid
        self._blobs: dict[tuple[int, int], bytes] = {}

    def refresh(self) -> None:
        grid = self.grid
        for key in grid.dirty:
            items = grid.items_at(key)
            if items:
                self._blobs[key] = b"".join([f.wire or self._pack(f) for f in items])
            else:
                self._blobs.pop(key, None)
        grid.dirty.clear()

    @staticmethod
    def _pack(food) -> bytes:
        food.wire = pack_food(food.x, food.y, food.id % 8)
        return food.wire

    def view(self, x: float, y: float, half: float) -> bytes:
        """Packed food from every bucket touching the square. Includes some food just outside it."""
        blobs = self._blobs
        return b"".join([blobs[k] for k in self.grid.keys_in(x, y, half) if k in blobs])


class Client:
    """One connection. The transport reads `take()`; game code writes `outbox` and `state`."""

    def __init__(self, ip: str, now: float, burst: float):
        self.ip = ip
        self.player: Player | None = None
        self.outbox: list[str] = []  # must-deliver messages
        self.state: bytes | None = None  # only the newest snapshot matters, so a slow client drops frames
        self.event = asyncio.Event()  # set when there is something to send
        self.known_names: set[int] = set()
        self.board_seen = -1  # version of the leaderboard this client last got
        self.peak_mass = 0.0
        self.last_seen = now  # when the last message arrived, for the idle watchdog
        self.tokens = burst  # rate limit bucket
        self.refilled = now
        self.drops = 0

    def push(self, message: str) -> None:
        self.outbox.append(message)
        self.event.set()

    def set_state(self, frame: bytes) -> None:
        self.state = frame
        self.event.set()

    def take(self) -> list[str | bytes]:
        messages: list[str | bytes] = list(self.outbox)
        self.outbox = []
        if self.state is not None:
            messages.append(self.state)
            self.state = None
        return messages


class GameServer:
    def __init__(
        self,
        config: Config | None = None,
        bots: int = 15,
        seed: int | None = None,
        limits: Limits | None = None,
        send_every: int = 2,
    ):
        rng = random.Random(seed)
        self.world = World(config, rng)
        if self.world.config.map_size > 65000:
            raise ValueError("map_size must fit the u16 positions of the wire format")
        self.bots = BotManager(self.world, bots, random.Random(rng.random()))
        self.limits = limits or Limits()
        self.send_every = max(1, send_every)  # ticks between state frames
        self.dt = 1 / self.world.config.tick_rate
        self.clock = time.monotonic
        self._food = FoodBlobs(self.world.food_grid)
        self.clients: dict[int, Client] = {}  # by player id, joined clients only
        self.connections = 0
        self._per_ip: dict[str, int] = {}
        self.tick_count = 0
        self.tick_ms = 0.0  # moving average of how long a tick takes
        self.snapshots = 0
        self.snapshot_bytes = 0
        self._leaderboard: list[list] = []
        self._board_version = 0

    # --- connections ---------------------------------------------------

    def refusal(self, ip: str) -> str | None:
        """Why a new connection from `ip` should be turned away, or None to let it in."""
        if self.connections >= self.limits.max_players:
            return "full"
        if self._per_ip.get(ip, 0) >= self.limits.max_per_ip:
            return "ip"
        return None

    def connect(self, ip: str = "local") -> Client:
        self.connections += 1
        self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        return Client(ip, self.clock(), self.limits.msg_burst)

    def disconnect(self, client: Client) -> None:
        if client.ip is None:
            return  # already disconnected
        self.connections -= 1
        left = self._per_ip.get(client.ip, 1) - 1
        if left > 0:
            self._per_ip[client.ip] = left
        else:
            self._per_ip.pop(client.ip, None)
        client.ip = None
        if client.player is not None:
            self.clients.pop(client.player.id, None)
            self.world.remove_player(client.player.id)
            client.player = None

    def handle_message(self, client: Client, raw: str) -> bool:
        """Act on one client message. Returns False when the client should be disconnected."""
        if not self._allow(client):
            return client.drops < self.limits.drop_after
        if len(raw) > MAX_MESSAGE_CHARS:
            return True
        try:
            msg = json.loads(raw)
        except ValueError:
            return True
        if not isinstance(msg, dict):
            return True
        kind = msg.get("t")
        if kind == "join":
            self._join(client, clean_name(msg.get("name")))
        elif kind == "move":
            self._move(client, _number(msg.get("x")), _number(msg.get("y")))
        elif client.player is not None:
            if kind == "split":
                self.world.split(client.player.id)
            elif kind == "eject":
                self.world.eject(client.player.id)
        return True

    def _allow(self, client: Client) -> bool:
        """Token bucket: msg_rate messages a second, with room for a burst."""
        limits = self.limits
        now = self.clock()
        client.last_seen = now
        tokens = min(limits.msg_burst, client.tokens + (now - client.refilled) * limits.msg_rate)
        client.refilled = now
        if tokens >= 1:
            client.tokens = tokens - 1
            return True
        client.tokens = tokens
        client.drops += 1
        return False

    def _join(self, client: Client, name: str) -> None:
        world = self.world
        if client.player is None:
            player = world.add_player(name)
            client.player = player
            self.clients[player.id] = client
            cfg = world.config
            client.push(_dumps({
                "t": "welcome", "id": player.id, "map": cfg.map_size, "tick": cfg.tick_rate,
                "snap": round(self.dt * self.send_every * 1000),
                "fr": round(cfg.radius_factor * math.sqrt(cfg.food_mass), 1),
                "pr": round(cfg.radius_factor * math.sqrt(cfg.pellet_mass), 1),
            }))
        elif not client.player.alive:
            client.player.name = name
            world.respawn(client.player.id)
        else:
            return
        client.board_seen = -1
        client.peak_mass = client.player.mass

    def _move(self, client: Client, x: float | None, y: float | None) -> None:
        player = client.player
        if player is None or not player.alive or x is None or y is None:
            return
        size = self.world.config.map_size
        self.world.set_target(player.id, min(max(x, 0.0), size), min(max(y, 0.0), size))

    # --- the tick ------------------------------------------------------

    def tick(self) -> None:
        started = time.perf_counter()
        self.tick_count += 1
        world = self.world
        self.bots.update(self.tick_count)
        deaths = world.step(self.dt)

        for death in deaths:
            client = self.clients.get(death.victim_id)
            if client is not None:
                killer = world.players.get(death.killer_id)
                client.push(_dumps({
                    "t": "dead", "by": killer.name if killer else "", "peak": round(client.peak_mass),
                }))

        if self.tick_count % LEADERBOARD_EVERY == 0 or not self._leaderboard:
            self._leaderboard = self._build_leaderboard()
            self._board_version += 1

        if self.tick_count % self.send_every == 0:
            self._food.refresh()
            for client in self.clients.values():
                player = client.player
                if player is not None and player.alive:
                    frame = self._snapshot(client, player)
                    self.snapshots += 1
                    self.snapshot_bytes += len(frame)
                    client.set_state(frame)

        elapsed_ms = (time.perf_counter() - started) * 1000
        self.tick_ms = elapsed_ms if self.tick_count == 1 else self.tick_ms * 0.95 + elapsed_ms * 0.05

    def _build_leaderboard(self) -> list[list]:
        alive = [p for p in self.world.players.values() if p.alive]
        alive.sort(key=lambda p: -p.mass)
        return [[p.name, round(p.mass)] for p in alive[:LEADERBOARD_SIZE]]

    def _snapshot(self, client: Client, player: Player) -> bytes:
        world = self.world
        cells = player.cells
        mass = player.mass
        client.peak_mass = max(client.peak_mass, mass)
        cx = sum(c.x * c.mass for c in cells) / mass
        cy = sum(c.y * c.mass for c in cells) / mass
        # Zoom out with size, and with how far apart the pieces are so all of them stay in view.
        spread = max(math.hypot(c.x - cx, c.y - cy) + c.radius for c in cells)
        view = 450 + 10 * max(c.radius for c in cells) + spread

        visible = world.query_cells(cx, cy, view)
        new_names = {c.owner.id: c.owner.name for c in visible if c.owner.id not in client.known_names}
        client.known_names.update(new_names)
        board = None
        if client.board_seen != self._board_version:
            board = self._leaderboard
            client.board_seen = self._board_version
        return encode_state(
            me=(cx, cy, mass),
            view=view,
            cells=[(c.id, c.owner.id, c.x, c.y, c.radius) for c in visible],
            food=self._food.view(cx, cy, view),
            viruses=[(v.x, v.y, v.radius) for v in world.query_viruses(cx, cy, view)],
            pellets=[(p.x, p.y, p.owner_id) for p in world.query_pellets(cx, cy, view)],
            names=new_names,
            leaderboard=board,
        )

    # --- the loop ------------------------------------------------------

    async def run(self) -> None:
        """Tick at a fixed rate forever. If the host can't keep up, slow down instead of bursting."""
        next_time = time.perf_counter()
        while True:
            self.tick()
            next_time += self.dt
            delay = next_time - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                if delay < -0.25:
                    next_time = time.perf_counter()
                await asyncio.sleep(0)  # let sockets run even when every tick overruns

    def stats(self) -> dict:
        return {
            "players": len(self.clients),
            "connections": self.connections,
            "bots": len(self.bots.bots),
            "tick_ms": round(self.tick_ms, 2),
            "tick_budget_ms": round(self.dt * 1000, 1),
            "cpu_s": round(time.process_time(), 2),  # CPU time this process has used since it started
            "snapshots": self.snapshots,
            "snapshot_bytes": self.snapshot_bytes,
        }
