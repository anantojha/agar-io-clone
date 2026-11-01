import json
from dataclasses import replace

import pytest

from game import Config
from server.game_server import GameServer, clean_name
from server.limits import Limits
from server.protocol import decode_state


def make(bots=0, limits=None, send_every=1, **overrides):
    cfg = replace(Config(), **{"food_count": 0, "virus_count": 0, **overrides})
    return GameServer(cfg, bots=bots, seed=1, limits=limits, send_every=send_every)


def say(server, client, **msg):
    server.handle_message(client, json.dumps(msg))


def drain(client):
    """Everything queued for the client, decoded; state frames get "t": "s"."""
    return [{**decode_state(m), "t": "s"} if isinstance(m, bytes) else json.loads(m) for m in client.take()]


def join(server, name="Ada"):
    client = server.connect()
    say(server, client, t="join", name=name)
    return client


def test_clean_name():
    assert clean_name("  Ada  ") == "Ada"
    assert clean_name("x" * 40) == "x" * 16
    assert clean_name("a\x00b\n") == "ab"
    assert clean_name("") == "Anonymous"
    assert clean_name(None) == "Anonymous"
    assert clean_name(123) == "Anonymous"


def test_join_sends_welcome_and_creates_a_living_player():
    server = make()
    client = join(server)
    [welcome] = drain(client)
    assert welcome == {
        "t": "welcome", "id": client.player.id, "map": 4000.0, "tick": 30, "snap": 33, "fr": 6.0, "pr": 20.8,
    }
    assert client.player.alive and client.player.name == "Ada"


def test_second_join_while_alive_is_ignored():
    server = make()
    client = join(server)
    drain(client)
    say(server, client, t="join", name="Other")
    assert client.player.name == "Ada"
    assert drain(client) == []


def test_move_sets_the_target_and_clamps_to_the_map():
    server = make()
    client = join(server)
    say(server, client, t="move", x=1234, y=-50)
    assert (client.player.target_x, client.player.target_y) == (1234, 0)
    say(server, client, t="move", x=9999, y=10)
    assert client.player.target_x == 4000


@pytest.mark.parametrize("x,y", [("a", 1), (None, 1), (True, 1), (float("nan"), 1), (1, [1])])
def test_bad_move_values_are_ignored(x, y):
    server = make()
    client = join(server)
    before = (client.player.target_x, client.player.target_y)
    server.handle_message(client, json.dumps({"t": "move", "x": x, "y": y}, allow_nan=True))
    assert (client.player.target_x, client.player.target_y) == before


def test_messages_before_joining_are_ignored():
    server = make()
    client = server.connect()
    say(server, client, t="move", x=1, y=1)
    server.handle_message(client, "{{{{")
    server.handle_message(client, "x" * 2000)
    assert client.player is None


def test_state_contains_me_cells_names_and_leaderboard():
    server = make(bots=3)
    client = join(server)
    drain(client)
    server.tick()
    [state] = drain(client)
    assert state["t"] == "s"
    me = client.player.cells[0]
    assert state["me"][:2] == [round(me.x), round(me.y)]
    assert any(c[0] == me.id and c[1] == client.player.id for c in state["c"])
    assert state["n"][client.player.id] == "Ada"
    assert state["lb"]


def test_names_are_only_sent_once_per_player():
    server = make()
    client = join(server)
    server.tick()
    assert "n" in drain(client)[-1]
    server.tick()
    assert "n" not in drain(client)[-1]


def test_only_the_newest_state_is_kept_for_a_slow_client():
    server = make()
    client = join(server)
    drain(client)
    for _ in range(5):
        server.tick()
    assert len(drain(client)) == 1


def test_view_culls_far_away_food():
    server = make(food_count=0)
    client = join(server)
    me = client.player.cells[0]
    from game.world import Food

    near = Food(9001, me.x + 100 if me.x < 3500 else me.x - 100, me.y)
    far_x = 100 if me.x > 2000 else 3900
    far = Food(9002, far_x, 100 if me.y > 2000 else 3900)
    for f in (near, far):
        server.world.food[f.id] = f
        server.world.food_grid.insert(f)
    server.tick()
    state = drain(client)[-1]
    xs = {tuple(f[:2]) for f in state["f"]}
    assert (round(near.x), round(near.y)) in xs
    assert (round(far.x), round(far.y)) not in xs


def test_death_sends_dead_stops_state_and_rejoin_respawns():
    server = make()
    victim = join(server, "Victim")
    killer = join(server, "Killer")
    drain(victim), drain(killer)
    v, k = victim.player.cells[0], killer.player.cells[0]
    v.x, v.y, v.mass = 1000, 1000, 20
    k.x, k.y, k.mass = 1005, 1000, 500
    victim.player.target_x, victim.player.target_y = 1000, 1000
    killer.player.target_x, killer.player.target_y = 1005, 1000

    server.tick()
    messages = drain(victim)
    assert [m["t"] for m in messages] == ["dead"]
    assert messages[0]["by"] == "Killer"
    assert not victim.player.alive

    server.tick()
    assert drain(victim) == []  # dead players get no state

    say(server, victim, t="join", name="Again")
    assert victim.player.alive and victim.player.name == "Again"
    server.tick()
    assert drain(victim)[-1]["t"] == "s"


def test_disconnect_removes_the_player_from_the_world():
    server = make()
    client = join(server)
    pid = client.player.id
    server.disconnect(client)
    assert pid not in server.world.players
    assert pid not in server.clients
    server.tick()  # nothing blows up


def test_bots_show_up_on_the_leaderboard():
    server = make(bots=5)
    client = join(server)
    server.tick()
    state = drain(client)[-1]
    assert len(state["lb"]) == 6


def test_split_and_eject_messages_act_on_the_players_cells():
    server = make()
    client = join(server)
    me = client.player.cells[0]
    me.mass = 200
    say(server, client, t="move", x=me.x + 500 if me.x < 3000 else me.x - 500, y=me.y)
    say(server, client, t="split")
    assert len(client.player.cells) == 2
    server.world.time += 1  # past the eject cooldown
    say(server, client, t="eject")
    assert len(server.world.pellets) == 2  # both cells were big enough


def test_split_before_joining_does_nothing():
    server = make()
    client = server.connect()
    say(server, client, t="split")
    say(server, client, t="eject")
    assert client.player is None and server.world.pellets == []


def test_state_lists_viruses_and_pellets_in_view():
    server = make(virus_count=0)
    client = join(server)
    me = client.player.cells[0]
    me.mass = 200
    from game.world import Virus

    dx = 300 if me.x < 3000 else -300
    v = Virus(9001, me.x + dx, me.y, 100, 60)
    server.world.viruses[v.id] = v
    server.world._virus_grid.insert(v)
    say(server, client, t="eject")
    server.tick()
    state = drain(client)[-1]
    assert state["vi"] == [[round(v.x), round(v.y), 60.0]]
    assert len(state["e"]) == 1 and state["e"][0][2] == client.player.id


def test_view_widens_when_pieces_spread_out():
    server = make()
    client = join(server)
    me = client.player.cells[0]
    me.mass = 200
    say(server, client, t="move", x=me.x, y=me.y)
    say(server, client, t="split")
    piece = client.player.cells[1]
    piece.vx = piece.vy = 0
    server.tick()
    together = drain(client)[-1]["v"]
    piece.x += 600 if piece.x < 2000 else -600
    server.tick()
    assert drain(client)[-1]["v"] > together


def test_stats():
    server = make(bots=4)
    join(server)
    server.tick()
    stats = server.stats()
    assert stats["players"] == 1 and stats["bots"] == 4
    assert stats["tick_ms"] >= 0
