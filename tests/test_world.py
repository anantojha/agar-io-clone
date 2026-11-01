import random
from dataclasses import replace

import pytest

from game import Config, DeathEvent, World

DT = 1 / 30


def make_world(**overrides) -> World:
    """A world with no food unless a test asks for it, so tests control exactly what exists."""
    cfg = replace(Config(), **{"food_count": 0, "virus_count": 0, **overrides})
    return World(cfg, random.Random(1))


def place(world: World, name: str, x: float, y: float, mass: float):
    player = world.add_player(name)
    cell = player.cells[0]
    cell.x, cell.y, cell.mass = x, y, mass
    player.target_x, player.target_y = x, y  # stay put unless the test moves it
    return player, cell


# --- sizes and speed --------------------------------------------------


def test_radius_grows_with_mass():
    w = make_world()
    _, small = place(w, "s", 500, 500, 20)
    _, big = place(w, "b", 1500, 1500, 200)
    assert big.radius > small.radius


def test_speed_falls_with_mass_and_has_a_floor():
    w = make_world()
    assert w.speed_for(20) > w.speed_for(200) > w.speed_for(2000)
    assert w.speed_for(1e12) == w.config.min_speed


# --- movement ---------------------------------------------------------


def test_moves_toward_target_without_overshooting():
    w = make_world()
    p, cell = place(w, "a", 500, 500, 20)
    w.set_target(p.id, 510, 500)
    for _ in range(100):
        w.step(DT)
    assert cell.x == pytest.approx(510)
    assert cell.y == pytest.approx(500)


def test_stays_inside_the_map():
    w = make_world()
    p, cell = place(w, "a", 100, 100, 20)
    w.set_target(p.id, -5000, -5000)
    for _ in range(300):
        w.step(DT)
    assert cell.x == pytest.approx(cell.radius)
    assert cell.y == pytest.approx(cell.radius)
    w.set_target(p.id, 99999, 99999)
    for _ in range(3000):
        w.step(DT)
    assert cell.x == pytest.approx(w.config.map_size - cell.radius)


# --- food -------------------------------------------------------------


def test_eats_food_under_its_center_and_gains_mass():
    w = make_world(food_count=1)
    _, cell = place(w, "a", 500, 500, 20)
    food = next(iter(w.food.values()))
    food.x, food.y = 500, 500
    w.food_grid.clear()
    w.food_grid.insert(food)
    w.step(DT)
    assert food.id not in w.food
    assert cell.mass == pytest.approx(20 + w.config.food_mass)


def test_ignores_food_outside_its_radius():
    w = make_world(food_count=1)
    _, cell = place(w, "a", 500, 500, 20)
    food = next(iter(w.food.values()))
    food.x, food.y = 500 + cell.radius + 5, 500
    w.food_grid.clear()
    w.food_grid.insert(food)
    w.step(DT)
    assert food.id in w.food


def test_food_respawns_to_the_target_count():
    w = make_world(food_count=100, food_respawn_per_tick=7)
    assert len(w.food) == 100
    for f in list(w.food.values())[:30]:
        w._remove_food(f)
    w.step(DT)
    assert len(w.food) == 77
    for _ in range(10):
        w.step(DT)
    assert len(w.food) == 100


# --- eating cells -----------------------------------------------------


def test_bigger_cell_eats_smaller_and_victim_dies():
    w = make_world(decay_rate=0)
    big_p, big = place(w, "big", 500, 500, 100)
    small_p, small = place(w, "small", 505, 500, 20)
    events = w.step(DT)
    assert events == [DeathEvent(small_p.id, big_p.id)]
    assert not small_p.alive and small_p.cells == []
    assert big.mass == pytest.approx(120)


def test_no_eating_below_the_mass_ratio():
    w = make_world()
    a_p, a = place(w, "a", 500, 500, 100)
    b_p, b = place(w, "b", 505, 500, 100 / 1.25 + 1)  # ratio just under 1.25
    assert w.step(DT) == []
    assert a_p.alive and b_p.alive


def test_eats_when_ratio_is_just_met():
    w = make_world()
    a_p, a = place(w, "a", 500, 500, 100)
    b_p, b = place(w, "b", 505, 500, 100 / 1.25 - 1)
    assert len(w.step(DT)) == 1


def test_must_cover_the_victims_center():
    w = make_world()
    big_p, big = place(w, "big", 500, 500, 100)
    small_p, small = place(w, "small", 500 + big.radius, 500, 20)  # touching edge, center outside
    assert w.step(DT) == []
    assert small_p.alive


def test_cells_of_one_player_do_not_eat_each_other():
    w = make_world()
    p, first = place(w, "a", 500, 500, 100)
    from game.world import Cell

    second = Cell(w._new_id(), p, 505, 500, 20, w.config.radius_factor)
    first.merge_at = second.merge_at = 999  # still cooling down, so they only push apart
    p.cells.append(second)
    assert w.step(DT) == []
    assert len(p.cells) == 2


def test_dead_player_can_respawn_with_start_mass():
    w = make_world()
    big_p, _ = place(w, "big", 500, 500, 100)
    small_p, _ = place(w, "small", 505, 500, 20)
    w.step(DT)
    assert not small_p.alive
    w.respawn(small_p.id)
    assert small_p.alive
    assert small_p.mass == w.config.start_mass


def test_respawn_does_nothing_to_a_living_player():
    w = make_world()
    p, cell = place(w, "a", 500, 500, 100)
    w.respawn(p.id)
    assert p.cells == [cell] and cell.mass == 100


def test_mass_is_capped():
    w = make_world(max_mass=110)
    place(w, "big", 500, 500, 100)
    place(w, "small", 505, 500, 50)  # 100 / 50 = 2 >= ratio
    w.step(DT)
    assert next(iter(w.players.values())).cells[0].mass == 110


# --- decay and spawning ----------------------------------------------


def test_big_cells_decay_but_never_below_start_mass():
    w = make_world()
    _, big = place(w, "big", 500, 500, 1000)
    w.step(1.0)
    assert 20 < big.mass < 1000
    _, tiny = place(w, "tiny", 3000, 3000, 20)
    w.step(1.0)
    assert tiny.mass == 20


def test_spawn_prefers_spots_away_from_other_cells():
    w = make_world()
    _, blocker = place(w, "blocker", 2000, 2000, 5000)
    for _ in range(20):
        p = w.add_player("n")
        cell = p.cells[0]
        d = ((cell.x - 2000) ** 2 + (cell.y - 2000) ** 2) ** 0.5
        assert d > blocker.radius  # never spawns inside the big cell


def test_removing_a_player_removes_their_cells():
    w = make_world()
    p, _ = place(w, "a", 500, 500, 20)
    w.remove_player(p.id)
    assert p.id not in w.players
    assert w.step(DT) == []


# --- determinism ------------------------------------------------------


def run_scenario(seed: int):
    cfg = replace(Config(), food_count=300)
    w = World(cfg, random.Random(seed))
    r = random.Random(seed + 1000)
    for i in range(10):
        w.add_player(f"p{i}")
    for tick in range(200):
        if tick % 20 == 0:
            for p in w.players.values():
                w.set_target(p.id, r.uniform(0, cfg.map_size), r.uniform(0, cfg.map_size))
        w.step(DT)
    return sorted((p.id, round(p.mass, 6), p.alive) for p in w.players.values()), len(w.food)


def test_same_seed_gives_same_result():
    assert run_scenario(7) == run_scenario(7)
