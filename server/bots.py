import math
import random

from game import Player, World

BOT_NAMES = [
    "Blob", "Nibbles", "Orbit", "Pip", "Goober", "Chomp", "Mochi", "Sprout", "Zorp", "Bubbles",
    "Gumdrop", "Wobble", "Pebble", "Munch", "Jelly", "Dot", "Fizz", "Nugget", "Pogo", "Squish",
]

THINK_EVERY = 6  # ticks between decisions per bot (5 Hz at 30 ticks per second)
RESPAWN_DELAY = 3.0  # seconds a dead bot waits before coming back


SPLIT_ATTACK_COOLDOWN = 15.0  # seconds between a bot's split attacks
MAX_CELLS_FOR_ATTACK = 2  # a bot with more pieces than this is busy getting back together


class Bot:
    __slots__ = ("player", "offset", "wander", "respawn_at", "next_split")

    def __init__(self, player: Player, offset: int):
        self.player = player
        self.offset = offset  # staggers decisions so bots don't all think on the same tick
        self.wander: tuple[float, float] | None = None
        self.respawn_at: int | None = None
        self.next_split = 0  # tick before which the bot won't split again


class BotManager:
    """Fills the world with simple players: flee from bigger cells, chase smaller ones, eat food."""

    def __init__(self, world: World, count: int, rng: random.Random):
        self.world = world
        self.rng = rng
        self.tick = 0
        self.bots: list[Bot] = []
        for i in range(count):
            name = f"{BOT_NAMES[i % len(BOT_NAMES)]}{'' if i < len(BOT_NAMES) else i}"
            self.bots.append(Bot(world.add_player(name), offset=i))

    def update(self, tick: int) -> None:
        world = self.world
        self.tick = tick
        respawn_ticks = int(RESPAWN_DELAY * world.config.tick_rate)
        for bot in self.bots:
            if not bot.player.alive:
                if bot.respawn_at is None:
                    bot.respawn_at = tick + respawn_ticks
                elif tick >= bot.respawn_at:
                    world.respawn(bot.player.id)
                    bot.respawn_at = None
                    bot.wander = None
            elif (tick + bot.offset) % THINK_EVERY == 0:
                self.think(bot)

    def think(self, bot: Bot) -> None:
        world = self.world
        cfg = world.config
        player = bot.player
        me = max(player.cells, key=lambda c: c.mass)
        my_radius = me.radius
        vision = 400 + 5 * my_radius

        flee_x = flee_y = 0.0
        prey = None
        prey_dist = math.inf
        for other in world.query_cells(me.x, me.y, vision):
            if other.owner is player:
                continue
            dx, dy = other.x - me.x, other.y - me.y
            dist = math.hypot(dx, dy) or 1e-6
            if other.mass > me.mass * cfg.eat_ratio:
                danger = other.radius + my_radius + 300
                if dist < danger:
                    weight = (danger - dist) / danger
                    flee_x -= dx / dist * weight
                    flee_y -= dy / dist * weight
            elif me.mass > other.mass * cfg.eat_ratio * 1.1 and dist < prey_dist:
                prey, prey_dist = other, dist

        if flee_x or flee_y:
            norm = math.hypot(flee_x, flee_y)
            middle = cfg.map_size / 2
            # Pull toward the middle a little so fleeing doesn't pin the bot against a wall.
            tx = me.x + flee_x / norm * 600 + (middle - me.x) * 0.25
            ty = me.y + flee_y / norm * 600 + (middle - me.y) * 0.25
        elif prey is not None:
            tx, ty = prey.x, prey.y
            if self._can_split_attack(bot, me, prey, prey_dist):
                world.set_target(player.id, tx, ty)  # the split throws pieces toward the target
                if world.split(player.id):
                    bot.next_split = self.tick + int(SPLIT_ATTACK_COOLDOWN * cfg.tick_rate)
        else:
            # A cell big enough to burst on a virus keeps clear of them while looking for food.
            avoid = (
                world.query_viruses(me.x, me.y, 350)
                if me.mass >= cfg.virus_mass * cfg.eat_ratio else []
            )
            food = min(
                (
                    f for f in world.query_food(me.x, me.y, 350)
                    if all(math.hypot(f.x - v.x, f.y - v.y) > v.radius + my_radius for v in avoid)
                ),
                key=lambda f: (f.x - me.x) ** 2 + (f.y - me.y) ** 2,
                default=None,
            )
            if food is not None:
                tx, ty = food.x, food.y
            else:
                tx, ty = self._wander_target(bot, me.x, me.y)
        world.set_target(player.id, tx, ty)

    def _can_split_attack(self, bot: Bot, me, prey, prey_dist: float) -> bool:
        """Split when half of me could still eat the prey and the thrown half can reach it."""
        cfg = self.world.config
        if self.tick < bot.next_split or len(bot.player.cells) > MAX_CELLS_FOR_ATTACK:
            return False
        if me.mass < cfg.min_split_mass or me.mass / 2 < prey.mass * cfg.eat_ratio * 1.05:
            return False
        reach = (cfg.split_speed_base + cfg.split_speed_per_radius * me.radius) / cfg.boost_decay
        return prey_dist < reach * 0.9

    def _wander_target(self, bot: Bot, x: float, y: float) -> tuple[float, float]:
        size = self.world.config.map_size
        target = bot.wander
        if target is None or math.hypot(target[0] - x, target[1] - y) < 150:
            target = (self.rng.uniform(0.1, 0.9) * size, self.rng.uniform(0.1, 0.9) * size)
            bot.wander = target
        return target
