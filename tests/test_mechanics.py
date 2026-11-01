"""Split, merge, eject and virus rules."""
import math
import random
from dataclasses import replace

import pytest

from game import Config, World
from game.world import Virus

DT = 1 / 30


def make_world(**overrides) -> World:
    cfg = replace(Config(), **{"food_count": 0, "virus_count": 0, "decay_rate": 0, **overrides})
    return World(cfg, random.Random(1))


def place(world, name, x, y, mass):
    player = world.add_player(name)
    cell = player.cells[0]
    cell.x, cell.y, cell.mass = x, y, mass
    player.target_x, player.target_y = x, y
    return player, cell


def run(world, seconds):
    for _ in range(round(seconds / DT)):
        world.step(DT)


# --- split --------------------------------------------------------------


def test_split_halves_the_cell_and_throws_the_new_half_toward_the_cursor():
    w = make_world()
    p, cell = place(w, "a", 1000, 1000, 100)
    w.set_target(p.id, 2000, 1000)
    assert w.split(p.id)
    assert len(p.cells) == 2
    assert [c.mass for c in p.cells] == [50, 50]
    piece = p.cells[1]
    assert piece.vx > 0 and piece.vy == pytest.approx(0)
    run(w, 1.0)
    assert piece.x > cell.x + 100  # it flew ahead of the original


def test_split_conserves_mass():
    w = make_world()
    p, _ = place(w, "a", 1000, 1000, 100)
    w.set_target(p.id, 1500, 1500)
    w.split(p.id)
    assert p.mass == pytest.approx(100)


def test_split_needs_enough_mass():
    w = make_world()
    p, _ = place(w, "a", 1000, 1000, 39)
    assert not w.split(p.id)
    assert len(p.cells) == 1


def test_split_has_a_cooldown():
    w = make_world()
    p, _ = place(w, "a", 1000, 1000, 400)
    assert w.split(p.id)
    assert not w.split(p.id)  # same instant
    run(w, 0.3)
    assert w.split(p.id)
    assert len(p.cells) == 4


def test_split_stops_at_max_cells():
    w = make_world(max_cells=4, split_cooldown=0)
    p, _ = place(w, "a", 2000, 2000, 2000)
    for _ in range(10):
        w.split(p.id)
    assert len(p.cells) == 4


def test_dead_players_cannot_split_or_eject():
    w = make_world()
    p, _ = place(w, "a", 1000, 1000, 100)
    w.remove_player(p.id)
    assert not w.split(p.id)
    assert not w.eject(p.id)


# --- merge --------------------------------------------------------------


def test_pieces_stay_apart_until_the_cooldown_then_merge():
    w = make_world()
    p, _ = place(w, "a", 2000, 2000, 100)
    w.set_target(p.id, 2000, 2000)
    w.split(p.id)
    run(w, 5)
    assert len(p.cells) == 2  # still cooling down
    a, b = p.cells
    assert math.hypot(a.x - b.x, a.y - b.y) >= (a.radius + b.radius) * 0.95  # touching, not overlapping
    run(w, 10)
    assert len(p.cells) == 1
    assert p.mass == pytest.approx(100)


def test_pieces_do_not_overlap_while_cooling_down():
    w = make_world()
    p, _ = place(w, "a", 2000, 2000, 100)
    w.set_target(p.id, 2000, 2000)
    w.split(p.id)
    for _ in range(60):
        w.step(DT)
        a, b = p.cells
        assert math.hypot(a.x - b.x, a.y - b.y) >= (a.radius + b.radius) * 0.9


def test_a_big_split_takes_longer_to_merge():
    w = make_world()
    assert w._merge_delay(5000) > w._merge_delay(50)


# --- eject --------------------------------------------------------------


def test_eject_costs_mass_and_makes_a_pellet_flying_toward_the_cursor():
    w = make_world()
    p, cell = place(w, "a", 1000, 1000, 100)
    w.set_target(p.id, 2000, 1000)
    assert w.eject(p.id)
    assert cell.mass == pytest.approx(100 - w.config.eject_cost)
    [pellet] = w.pellets
    assert pellet.vx > 0 and abs(pellet.vy) < pellet.vx * 0.3
    assert pellet.mass == w.config.pellet_mass
    x0 = pellet.x
    run(w, 1.0)
    assert pellet.x > x0 + 100


def test_eject_needs_enough_mass_and_has_a_cooldown():
    w = make_world()
    p, _ = place(w, "a", 1000, 1000, 29)
    assert not w.eject(p.id)
    q, _ = place(w, "b", 3000, 3000, 100)
    assert w.eject(q.id)
    assert not w.eject(q.id)


def test_pellet_is_not_edible_while_flying_but_feeds_a_cell_once_it_rests():
    w = make_world()
    p, cell = place(w, "a", 1000, 1000, 100)
    w.set_target(p.id, 1000, 1000)
    other, other_cell = place(w, "b", 1300, 1000, 20)
    w.set_target(p.id, 1500, 1000)
    w.eject(p.id)
    pellet = w.pellets[0]
    other.target_x, other.target_y = 1300, 1000
    w.step(DT)
    assert pellet in w.pellets  # flying fast, passes over nothing yet
    pellet.vx = pellet.vy = 0.0
    pellet.x, pellet.y = other_cell.x, other_cell.y
    w.step(DT)
    assert pellet not in w.pellets
    assert other_cell.mass == pytest.approx(20 + w.config.pellet_mass)


def test_pellets_expire_and_the_total_is_capped():
    w = make_world(pellet_lifetime=2.0, max_pellets=5, eject_cooldown=0)
    p, _ = place(w, "a", 2000, 2000, 5000)
    p.target_x = 4000
    for _ in range(20):
        w.eject(p.id)
    assert len(w.pellets) == 5
    run(w, 2.5)
    assert w.pellets == []


# --- viruses ------------------------------------------------------------


def put_virus(w, x, y):
    v = Virus(w._new_id(), x, y, w.config.virus_mass, w.config.radius_factor * math.sqrt(w.config.virus_mass))
    w.viruses[v.id] = v
    w._virus_grid.insert(v)
    return v


def test_big_cell_bursts_on_a_virus_and_mass_is_conserved():
    w = make_world()
    p, cell = place(w, "a", 2000, 2000, 400)
    put_virus(w, 2000, 2000)
    w.step(DT)
    assert len(p.cells) == 1 + w.config.virus_pieces
    assert p.mass == pytest.approx(400 + w.config.virus_mass)
    assert not w.viruses


def test_burst_pieces_fly_apart():
    w = make_world()
    p, _ = place(w, "a", 2000, 2000, 400)
    put_virus(w, 2000, 2000)
    w.step(DT)
    run(w, 0.5)
    spread = max(math.hypot(c.x - 2000, c.y - 2000) for c in p.cells)
    assert spread > 100


def test_small_cell_is_not_affected_by_a_virus():
    w = make_world()
    p, cell = place(w, "a", 2000, 2000, 100)  # below 125, the mass needed to eat a virus
    v = put_virus(w, 2000, 2000)
    w.step(DT)
    assert len(p.cells) == 1
    assert v.id in w.viruses


def test_cell_at_the_cell_cap_just_gains_the_virus_mass():
    w = make_world(max_cells=1)
    p, cell = place(w, "a", 2000, 2000, 400)
    put_virus(w, 2000, 2000)
    w.step(DT)
    assert len(p.cells) == 1
    assert cell.mass == pytest.approx(500)


def test_virus_respawns():
    w = make_world(virus_count=3)
    assert len(w.viruses) == 3
    w._remove_virus(next(iter(w.viruses.values())))
    w.step(DT)
    assert len(w.viruses) == 3


def test_players_do_not_spawn_on_viruses():
    w = make_world(virus_count=5)
    for _ in range(20):
        p = w.add_player("n")
        cell = p.cells[0]
        assert all(math.hypot(v.x - cell.x, v.y - cell.y) > v.radius for v in w.viruses.values())


# --- queries and eating split pieces -----------------------------------


def test_queries_return_viruses_and_pellets_in_view():
    w = make_world()
    p, _ = place(w, "a", 2000, 2000, 100)
    near = put_virus(w, 2200, 2000)
    far = put_virus(w, 100, 100)
    p.target_x = 2000
    w.eject(p.id)
    w.step(DT)
    assert [v.id for v in w.query_viruses(2000, 2000, 500)] == [near.id]
    assert len(w.query_pellets(2000, 2000, 500)) == 1
    assert w.query_pellets(100, 100, 100) == []

