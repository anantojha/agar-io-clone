import math
import random
from typing import NamedTuple

from .config import Config
from .grid import SpatialHash


class Food:
    __slots__ = ("id", "x", "y", "wire")

    def __init__(self, id: int, x: float, y: float):
        self.id = id
        self.x = x
        self.y = y
        self.wire: bytes | None = None  # food never moves, so the server caches its encoded form here


class Pellet:
    """Mass thrown by a player. Flies, slows down, then sits there until eaten or it expires."""

    __slots__ = ("id", "owner_id", "x", "y", "vx", "vy", "mass", "age", "eaten")

    def __init__(self, id: int, owner_id: int, x: float, y: float, vx: float, vy: float, mass: float):
        self.id = id
        self.owner_id = owner_id
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.mass = mass
        self.age = 0.0
        self.eaten = False


class Virus:
    __slots__ = ("id", "x", "y", "mass", "radius")

    def __init__(self, id: int, x: float, y: float, mass: float, radius: float):
        self.id = id
        self.x = x
        self.y = y
        self.mass = mass
        self.radius = radius


class Cell:
    __slots__ = ("id", "owner", "x", "y", "mass", "alive", "vx", "vy", "merge_at", "_radius_factor")

    def __init__(self, id: int, owner: "Player", x: float, y: float, mass: float, radius_factor: float):
        self.id = id
        self.owner = owner
        self.x = x
        self.y = y
        self.mass = mass
        self.alive = True
        self.vx = 0.0  # extra velocity from a split, fades out
        self.vy = 0.0
        self.merge_at = 0.0  # world time when it may merge with its owner's other cells
        self._radius_factor = radius_factor

    @property
    def radius(self) -> float:
        return self._radius_factor * math.sqrt(self.mass)


class Player:
    __slots__ = ("id", "name", "cells", "target_x", "target_y", "alive", "last_split", "last_eject")

    def __init__(self, id: int, name: str):
        self.id = id
        self.name = name
        self.cells: list[Cell] = []
        self.target_x = 0.0
        self.target_y = 0.0
        self.alive = False
        self.last_split = -math.inf
        self.last_eject = -math.inf

    @property
    def mass(self) -> float:
        return sum(c.mass for c in self.cells)


class DeathEvent(NamedTuple):
    victim_id: int
    killer_id: int


class World:
    """The whole game state and its rules. No networking and no clock: callers call step(dt)."""

    def __init__(self, config: Config | None = None, rng: random.Random | None = None):
        self.config = config or Config()
        self.rng = rng or random.Random()
        self.time = 0.0  # seconds of simulated time
        self.players: dict[int, Player] = {}
        self.food: dict[int, Food] = {}
        self.viruses: dict[int, Virus] = {}
        self.pellets: list[Pellet] = []  # oldest first
        self.food_grid = SpatialHash(self.config.food_grid_cell_size)
        self._virus_grid = SpatialHash(self.config.grid_cell_size)
        self._cell_grid = SpatialHash(self.config.grid_cell_size)  # rebuilt every step
        self._pellet_grid = SpatialHash(self.config.grid_cell_size)  # rebuilt every step
        self._next_id = 1
        for _ in range(self.config.food_count):
            self._spawn_food()
        for _ in range(self.config.virus_count):
            self._spawn_virus()

    # --- ids and sizes -------------------------------------------------

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def speed_for(self, mass: float) -> float:
        c = self.config
        speed = c.base_speed * (c.start_mass / mass) ** c.speed_exponent
        return max(speed, c.min_speed)

    def _new_cell(self, owner: Player, x: float, y: float, mass: float) -> Cell:
        return Cell(self._new_id(), owner, x, y, mass, self.config.radius_factor)

    def _merge_delay(self, mass: float) -> float:
        c = self.config
        return c.merge_base + c.merge_per_mass * mass

    # --- players -------------------------------------------------------

    def add_player(self, name: str) -> Player:
        player = Player(self._new_id(), name)
        self.players[player.id] = player
        self.respawn(player.id)
        return player

    def remove_player(self, player_id: int) -> None:
        player = self.players.pop(player_id, None)
        if player:
            for cell in player.cells:
                cell.alive = False
            player.cells = []
            player.alive = False

    def respawn(self, player_id: int) -> None:
        """Put a dead player back in the world with one starting cell. No-op if already alive."""
        player = self.players[player_id]
        if player.alive:
            return
        x, y = self._pick_spawn()
        player.cells = [self._new_cell(player, x, y, self.config.start_mass)]
        player.target_x, player.target_y = x, y
        player.alive = True

    def set_target(self, player_id: int, x: float, y: float) -> None:
        player = self.players.get(player_id)
        if player:
            player.target_x = x
            player.target_y = y

    def _pick_spawn(self) -> tuple[float, float]:
        c = self.config
        cells = [cell for p in self.players.values() for cell in p.cells]
        best, best_clearance = (c.map_size / 2, c.map_size / 2), -1.0
        for _ in range(c.spawn_candidates):
            x = self.rng.uniform(0, c.map_size)
            y = self.rng.uniform(0, c.map_size)
            clearance = min(
                (math.hypot(cell.x - x, cell.y - y) - cell.radius for cell in cells),
                default=math.inf,
            )
            for virus in self.viruses.values():
                clearance = min(clearance, math.hypot(virus.x - x, virus.y - y) - virus.radius)
            if clearance > best_clearance:
                best, best_clearance = (x, y), clearance
        return best

    # --- player actions ------------------------------------------------

    def split(self, player_id: int) -> bool:
        """Halve every cell that is big enough, throwing the new halves toward the cursor."""
        player = self.players.get(player_id)
        c = self.config
        if player is None or not player.alive or self.time - player.last_split < c.split_cooldown:
            return False
        player.last_split = self.time
        did_split = False
        for cell in sorted(player.cells, key=lambda cell: -cell.mass):
            if len(player.cells) >= c.max_cells:
                break
            if cell.mass < c.min_split_mass:
                continue
            half = cell.mass / 2
            cell.mass = half
            dx, dy = self._direction(cell, player)
            speed = c.split_speed_base + c.split_speed_per_radius * cell.radius
            piece = self._new_cell(player, cell.x, cell.y, half)
            piece.vx, piece.vy = dx * speed, dy * speed
            piece.merge_at = cell.merge_at = self.time + self._merge_delay(half)
            player.cells.append(piece)
            did_split = True
        return did_split

    def eject(self, player_id: int) -> bool:
        """Throw a pellet of mass from every cell that can afford it, toward the cursor."""
        player = self.players.get(player_id)
        c = self.config
        if player is None or not player.alive or self.time - player.last_eject < c.eject_cooldown:
            return False
        player.last_eject = self.time
        ejected = False
        for cell in player.cells:
            if cell.mass < c.min_eject_mass:
                continue
            cell.mass -= c.eject_cost
            dx, dy = self._direction(cell, player)
            angle = math.atan2(dy, dx) + self.rng.uniform(-0.1, 0.1)
            dx, dy = math.cos(angle), math.sin(angle)
            radius = cell.radius
            self.pellets.append(Pellet(
                self._new_id(), player.id,
                cell.x + dx * radius, cell.y + dy * radius,
                dx * c.eject_speed, dy * c.eject_speed, c.pellet_mass,
            ))
            ejected = True
        del self.pellets[:max(0, len(self.pellets) - c.max_pellets)]
        return ejected

    @staticmethod
    def _direction(cell: Cell, player: Player) -> tuple[float, float]:
        """Unit vector from the cell toward the player's cursor; to the right if they coincide."""
        dx, dy = player.target_x - cell.x, player.target_y - cell.y
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            return 1.0, 0.0
        return dx / dist, dy / dist

    # --- food and viruses ----------------------------------------------

    def _spawn_food(self) -> None:
        c = self.config
        food = Food(self._new_id(), self.rng.uniform(0, c.map_size), self.rng.uniform(0, c.map_size))
        self.food[food.id] = food
        self.food_grid.insert(food)

    def _remove_food(self, food: Food) -> None:
        del self.food[food.id]
        self.food_grid.remove(food)

    def _spawn_virus(self) -> None:
        c = self.config
        radius = c.radius_factor * math.sqrt(c.virus_mass)
        x = y = 0.0
        for _ in range(10):  # a few tries to stay off other viruses
            x = self.rng.uniform(radius, c.map_size - radius)
            y = self.rng.uniform(radius, c.map_size - radius)
            if all(math.hypot(v.x - x, v.y - y) > radius * 4 for v in self.viruses.values()):
                break
        virus = Virus(self._new_id(), x, y, c.virus_mass, radius)
        self.viruses[virus.id] = virus
        self._virus_grid.insert(virus)

    def _remove_virus(self, virus: Virus) -> None:
        del self.viruses[virus.id]
        self._virus_grid.remove(virus)

    # --- queries -------------------------------------------------------

    def query_cells(self, x: float, y: float, half: float) -> list[Cell]:
        """Living cells whose circle touches the square centered on (x, y) with half-side `half`.

        Uses the grid built by the last step(), so a cell spawned since then is not included.
        """
        return [
            c for c in self._cell_grid.query_list(x, y, half)
            if c.alive and abs(c.x - x) - c.radius <= half and abs(c.y - y) - c.radius <= half
        ]

    def query_food(self, x: float, y: float, half: float) -> list[Food]:
        """Food inside the square centered on (x, y) with half-side `half`."""
        return [
            f for f in self.food_grid.query_list(x, y, half)
            if abs(f.x - x) <= half and abs(f.y - y) <= half
        ]

    def query_viruses(self, x: float, y: float, half: float) -> list[Virus]:
        return [
            v for v in self._virus_grid.query_list(x, y, half)
            if abs(v.x - x) - v.radius <= half and abs(v.y - y) - v.radius <= half
        ]

    def query_pellets(self, x: float, y: float, half: float) -> list[Pellet]:
        """Pellets (flying or resting) inside the square, from the grid built by the last step()."""
        return [
            p for p in self._pellet_grid.query_list(x, y, half)
            if abs(p.x - x) <= half and abs(p.y - y) <= half
        ]

    # --- simulation ----------------------------------------------------

    def step(self, dt: float) -> list[DeathEvent]:
        """Advance the world by dt seconds. Returns the deaths that happened this step."""
        c = self.config
        self.time += dt
        live_cells: list[Cell] = []
        for player in self.players.values():
            if player.alive:
                live_cells.extend(player.cells)

        self._move_and_decay(live_cells, dt)
        self._merge_and_separate()
        live_cells = [cell for cell in live_cells if cell.alive]
        self._move_pellets(dt)

        self._cell_grid.clear()
        for cell in live_cells:
            self._cell_grid.insert(cell)
        self._pellet_grid.clear()
        for pellet in self.pellets:
            self._pellet_grid.insert(pellet)

        self._eat_food(live_cells)
        self._eat_pellets(live_cells)
        killers = self._eat_cells(live_cells)
        self._burst_on_viruses(live_cells)

        events = self._reap(killers)

        for _ in range(min(c.food_count - len(self.food), c.food_respawn_per_tick)):
            self._spawn_food()
        if len(self.viruses) < c.virus_count:
            self._spawn_virus()
        return events

    def _clamp(self, cell: Cell) -> None:
        size = self.config.map_size
        radius = cell.radius
        cell.x = min(max(cell.x, radius), size - radius)
        cell.y = min(max(cell.y, radius), size - radius)

    def _move_and_decay(self, cells: list[Cell], dt: float) -> None:
        c = self.config
        fade = math.exp(-c.boost_decay * dt)
        for cell in cells:
            if cell.mass > c.start_mass:
                cell.mass = max(c.start_mass, cell.mass - cell.mass * c.decay_rate * dt)

            owner = cell.owner
            dx = owner.target_x - cell.x
            dy = owner.target_y - cell.y
            dist = math.hypot(dx, dy)
            if dist > 1e-9:
                radius = cell.radius
                # Slow down when the cursor is inside the cell so it settles instead of jittering.
                factor = min(1.0, dist / radius)
                step = min(self.speed_for(cell.mass) * factor * dt, dist)
                cell.x += dx / dist * step
                cell.y += dy / dist * step

            if cell.vx or cell.vy:
                cell.x += cell.vx * dt
                cell.y += cell.vy * dt
                cell.vx *= fade
                cell.vy *= fade
                if cell.vx * cell.vx + cell.vy * cell.vy < 25.0:
                    cell.vx = cell.vy = 0.0
            self._clamp(cell)

    def _merge_and_separate(self) -> None:
        """Pieces of one player merge when both are ready and overlap, and push apart until then."""
        c = self.config
        for player in self.players.values():
            cells = player.cells
            if not player.alive or len(cells) < 2:
                continue
            for i in range(len(cells)):
                a = cells[i]
                for j in range(i + 1, len(cells)):
                    if not a.alive:
                        break
                    b = cells[j]
                    if not b.alive:
                        continue
                    dx, dy = b.x - a.x, b.y - a.y
                    dist = math.hypot(dx, dy)
                    ra, rb = a.radius, b.radius
                    if self.time >= a.merge_at and self.time >= b.merge_at:
                        big, small = (a, b) if a.mass >= b.mass else (b, a)
                        if dist < big.radius - c.eat_overlap * small.radius:
                            total = a.mass + b.mass
                            big.x = (a.x * a.mass + b.x * b.mass) / total
                            big.y = (a.y * a.mass + b.y * b.mass) / total
                            big.mass = min(c.max_mass, total)
                            small.alive = False
                    elif dist < ra + rb:
                        nx, ny = (dx / dist, dy / dist) if dist > 1e-6 else (1.0, 0.0)
                        overlap = ra + rb - dist
                        total = a.mass + b.mass
                        a.x -= nx * overlap * b.mass / total
                        a.y -= ny * overlap * b.mass / total
                        b.x += nx * overlap * a.mass / total
                        b.y += ny * overlap * a.mass / total
                        self._clamp(a)
                        self._clamp(b)

    def _move_pellets(self, dt: float) -> None:
        c = self.config
        size = c.map_size
        fade = math.exp(-c.pellet_decay * dt)
        for pellet in self.pellets:
            pellet.age += dt
            if pellet.vx or pellet.vy:
                pellet.x = min(max(pellet.x + pellet.vx * dt, 0.0), size)
                pellet.y = min(max(pellet.y + pellet.vy * dt, 0.0), size)
                pellet.vx *= fade
                pellet.vy *= fade
        self.pellets = [p for p in self.pellets if p.age < c.pellet_lifetime]

    def _eat_food(self, cells: list[Cell]) -> None:
        c = self.config
        for cell in cells:
            radius = cell.radius
            r2 = radius * radius
            eaten = [
                f for f in self.food_grid.query(cell.x, cell.y, radius)
                if (f.x - cell.x) ** 2 + (f.y - cell.y) ** 2 < r2
            ]
            for f in eaten:
                self._remove_food(f)
            if eaten:
                cell.mass = min(c.max_mass, cell.mass + c.food_mass * len(eaten))

    def _eat_pellets(self, cells: list[Cell]) -> None:
        c = self.config
        if not self.pellets:
            return
        slow = c.pellet_edible_speed ** 2
        for cell in cells:
            radius = cell.radius
            r2 = radius * radius
            for p in self._pellet_grid.query(cell.x, cell.y, radius):
                if p.eaten or p.vx * p.vx + p.vy * p.vy >= slow:
                    continue
                if (p.x - cell.x) ** 2 + (p.y - cell.y) ** 2 < r2:
                    p.eaten = True
                    cell.mass = min(c.max_mass, cell.mass + p.mass)
        self.pellets = [p for p in self.pellets if not p.eaten]

    def _eat_cells(self, cells: list[Cell]) -> dict[int, int]:
        """Resolve cell-eats-cell. Returns {eaten cell id: killer player id}."""
        c = self.config
        victims: dict[int, int] = {}
        for a in sorted(cells, key=lambda cell: -cell.mass):
            if not a.alive:
                continue
            ra = a.radius
            for b in self._cell_grid.query(a.x, a.y, ra):
                if b is a or not b.alive or b.owner is a.owner:
                    continue
                if a.mass < b.mass * c.eat_ratio:
                    continue
                reach = ra - c.eat_overlap * b.radius
                if reach <= 0:
                    continue
                if (a.x - b.x) ** 2 + (a.y - b.y) ** 2 < reach * reach:
                    b.alive = False
                    a.mass = min(c.max_mass, a.mass + b.mass)
                    victims[b.id] = a.owner.id
        return victims

    def _burst_on_viruses(self, cells: list[Cell]) -> None:
        """A cell big enough to eat a virus swallows it and bursts into pieces."""
        c = self.config
        if not self.viruses:
            return
        for cell in cells:
            if not cell.alive:
                continue
            radius = cell.radius
            for virus in self._virus_grid.query(cell.x, cell.y, radius):
                if virus.id not in self.viruses or cell.mass < virus.mass * c.eat_ratio:
                    continue
                reach = radius - c.eat_overlap * virus.radius
                if reach > 0 and (cell.x - virus.x) ** 2 + (cell.y - virus.y) ** 2 < reach * reach:
                    self._remove_virus(virus)
                    self._burst(cell, virus.mass)
                    break

    def _burst(self, cell: Cell, gained: float) -> None:
        c = self.config
        owner = cell.owner
        cell.mass = min(c.max_mass, cell.mass + gained)
        extra = min(c.virus_pieces, c.max_cells - len(owner.cells))
        if extra <= 0:
            return
        piece_mass = cell.mass / 2 / extra
        cell.mass /= 2
        speed = c.split_speed_base + c.split_speed_per_radius * cell.radius
        start = self.rng.uniform(0, math.tau)
        for i in range(extra):
            angle = start + math.tau * i / extra
            piece = self._new_cell(owner, cell.x, cell.y, piece_mass)
            piece.vx, piece.vy = math.cos(angle) * speed, math.sin(angle) * speed
            piece.merge_at = self.time + self._merge_delay(piece_mass)
            owner.cells.append(piece)
        cell.merge_at = self.time + self._merge_delay(cell.mass)

    def _reap(self, killers: dict[int, int]) -> list[DeathEvent]:
        """Drop eaten cells and mark players with no cells left as dead."""
        events: list[DeathEvent] = []
        for player in self.players.values():
            if not player.alive:
                continue
            dead = [cell for cell in player.cells if not cell.alive]
            if not dead:
                continue
            player.cells = [cell for cell in player.cells if cell.alive]
            if not player.cells:
                player.alive = False
                # With several cells eaten in one step, the last one listed decides the killer.
                killer = next((killers[cell.id] for cell in reversed(dead) if cell.id in killers), 0)
                events.append(DeathEvent(player.id, killer))
        return events
