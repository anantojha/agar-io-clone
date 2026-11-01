import random
from dataclasses import replace

from game import Config, World
from server.bots import BotManager

DT = 1 / 30


def setup(bots=1, **overrides):
    cfg = replace(Config(), **{"food_count": 0, "virus_count": 0, **overrides})
    world = World(cfg, random.Random(3))
    manager = BotManager(world, bots, random.Random(4))
    return world, manager


def put(world, player, x, y, mass):
    cell = player.cells[0]
    cell.x, cell.y, cell.mass = x, y, mass
    player.target_x, player.target_y = x, y
    return cell


def settle(world):
    """One step so the cell grid knows where everything was just put."""
    world.step(DT)


def test_bot_flees_from_a_bigger_cell():
    world, manager = setup()
    bot = manager.bots[0]
    me = put(world, bot.player, 2000, 2000, 50)
    threat_player = world.add_player("threat")
    put(world, threat_player, 2200, 2000, 500)  # to the right
    settle(world)
    manager.think(bot)
    assert bot.player.target_x < me.x  # runs left, away from the threat


def test_bot_chases_a_smaller_cell():
    world, manager = setup()
    bot = manager.bots[0]
    me = put(world, bot.player, 2000, 2000, 200)
    prey_player = world.add_player("prey")
    prey = put(world, prey_player, 2000, 2300, 20)  # below
    settle(world)
    manager.think(bot)
    assert (bot.player.target_x, bot.player.target_y) == (prey.x, prey.y)


def test_bot_splits_to_reach_close_prey_then_waits():
    world, manager = setup()
    bot = manager.bots[0]
    put(world, bot.player, 2000, 2000, 400)
    prey_player = world.add_player("prey")
    put(world, prey_player, 2000, 2200, 20)
    settle(world)
    manager.tick = 100
    manager.think(bot)
    assert len(bot.player.cells) == 2
    assert bot.next_split > 100
    world.time += 1  # past the world's split cooldown; the bot's own cooldown still holds
    manager.think(bot)
    assert len(bot.player.cells) == 2


def test_bot_does_not_split_at_distant_or_not_much_smaller_prey():
    world, manager = setup()
    bot = manager.bots[0]
    put(world, bot.player, 2000, 2000, 400)
    far = world.add_player("far")
    put(world, far, 2000, 2000 + 900, 20)
    settle(world)
    manager.think(bot)
    assert len(bot.player.cells) == 1

    world2, manager2 = setup()
    bot2 = manager2.bots[0]
    put(world2, bot2.player, 2000, 2000, 100)
    near = world2.add_player("near")
    put(world2, near, 2000, 2150, 75)  # 100/75 is above the eat ratio, but half of 100 is not
    settle(world2)
    manager2.think(bot2)
    assert len(bot2.player.cells) == 1


def test_bot_keeps_food_next_to_a_virus_when_big_enough_to_burst():
    from game.world import Food, Virus

    world, manager = setup()
    bot = manager.bots[0]
    me = put(world, bot.player, 2000, 2000, 300)
    virus = Virus(9100, 2100, 2000, 100, 60)
    world.viruses[virus.id] = virus
    world._virus_grid.insert(virus)
    risky, safe = Food(9001, 2110, 2000), Food(9002, 1800, 2000)  # risky is inside the virus
    for f in (risky, safe):
        world.food[f.id] = f
        world.food_grid.insert(f)
    settle(world)
    manager.think(bot)
    assert (bot.player.target_x, bot.player.target_y) == (safe.x, safe.y)


def test_bot_goes_for_nearby_food_when_alone():
    world, manager = setup(food_count=0)
    bot = manager.bots[0]
    put(world, bot.player, 2000, 2000, 20)
    from game.world import Food

    far, near = Food(9001, 2300, 2000), Food(9002, 2100, 2050)
    for f in (far, near):
        world.food[f.id] = f
        world.food_grid.insert(f)
    settle(world)
    manager.think(bot)
    assert (bot.player.target_x, bot.player.target_y) == (near.x, near.y)


def test_bot_wanders_when_nothing_is_around():
    world, manager = setup()
    bot = manager.bots[0]
    put(world, bot.player, 2000, 2000, 20)
    settle(world)
    manager.think(bot)
    first = (bot.player.target_x, bot.player.target_y)
    assert first != (2000, 2000)
    manager.think(bot)  # still heading to the same wander point
    assert (bot.player.target_x, bot.player.target_y) == first


def test_dead_bot_respawns_after_the_delay():
    world, manager = setup()
    bot = manager.bots[0]
    put(world, bot.player, 2000, 2000, 20)
    killer = world.add_player("killer")
    put(world, killer, 2005, 2000, 500)
    world.step(DT)
    assert not bot.player.alive
    for tick in range(1, 200):
        manager.update(tick)
        if bot.player.alive:
            break
    assert bot.player.alive
    assert tick >= 90  # waited about 3 seconds at 30 ticks per second


def test_manager_creates_the_requested_number_of_bots():
    world, manager = setup(bots=25)
    assert len(manager.bots) == 25
    assert len({b.player.name for b in manager.bots}) == 25
    assert all(b.player.alive for b in manager.bots)


def test_bots_run_for_a_while_without_errors():
    cfg = replace(Config(), food_count=400)
    world = World(cfg, random.Random(5))
    manager = BotManager(world, 15, random.Random(6))
    for tick in range(1, 900):
        manager.update(tick)
        world.step(DT)
    assert sum(1 for b in manager.bots if b.player.alive) > 0
