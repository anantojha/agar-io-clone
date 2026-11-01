import json
from dataclasses import replace

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from game import Config
from server.app import create_app
from server.game_server import GameServer
from server.limits import Limits
from server.protocol import decode_state


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(limits=None, send_every=1, bots=0):
    cfg = replace(Config(), food_count=0, virus_count=0)
    server = GameServer(cfg, bots=bots, seed=1, limits=limits, send_every=send_every)
    server.clock = FakeClock()
    return server


def move(x=1):
    return json.dumps({"t": "move", "x": x, "y": 1})


# --- rate limit -------------------------------------------------------


def test_messages_over_the_rate_are_dropped_then_the_client_is_cut_off():
    server = make(Limits(msg_rate=10, msg_burst=5, drop_after=3))
    client = server.connect("a")
    server.handle_message(client, json.dumps({"t": "join", "name": "x"}))
    results = [server.handle_message(client, move(500 + i)) for i in range(10)]
    # 4 more fit in the burst of 5 (one went on the join); the rest are dropped, the 3rd drop disconnects.
    assert results[:4] == [True] * 4
    assert results[4:6] == [True, True]
    assert results[6] is False
    assert client.player.target_x == 503  # dropped messages did nothing


def test_the_bucket_refills_over_time():
    server = make(Limits(msg_rate=10, msg_burst=5, drop_after=1000))
    client = server.connect("a")
    server.handle_message(client, json.dumps({"t": "join", "name": "x"}))
    for i in range(10):
        server.handle_message(client, move(100))
    server.clock.now += 1.0  # ten tokens back, capped at the burst of five
    server.handle_message(client, move(777))
    assert client.player.target_x == 777


def test_normal_play_stays_well_inside_the_default_limit():
    server = make()
    client = server.connect("a")
    server.handle_message(client, json.dumps({"t": "join", "name": "x"}))
    for second in range(10):
        for _ in range(30):  # the client sends a move every 33 ms
            server.clock.now += 1 / 30
            assert server.handle_message(client, move(second + 1))
    assert client.drops == 0


# --- connection caps --------------------------------------------------


def test_server_turns_away_connections_beyond_its_capacity():
    server = make(Limits(max_players=3, max_per_ip=10))
    clients = [server.connect(f"ip{i}") for i in range(3)]
    assert server.refusal("new") == "full"
    server.disconnect(clients[0])
    assert server.refusal("new") is None


def test_one_address_cannot_hog_the_server():
    server = make(Limits(max_players=40, max_per_ip=2))
    a, b = server.connect("1.2.3.4"), server.connect("1.2.3.4")
    assert server.refusal("1.2.3.4") == "ip"
    assert server.refusal("5.6.7.8") is None
    server.disconnect(a)
    assert server.refusal("1.2.3.4") is None


def test_disconnecting_twice_does_not_corrupt_the_counts():
    server = make()
    client = server.connect("a")
    server.disconnect(client)
    server.disconnect(client)
    assert server.connections == 0


# --- cadence ----------------------------------------------------------


def test_state_frames_go_out_every_nth_tick():
    server = make(send_every=3)
    client = server.connect("a")
    server.handle_message(client, json.dumps({"t": "join", "name": "x"}))
    client.take()
    sent = []
    for _ in range(9):
        server.tick()
        sent.append(len(client.take()))
    assert sent == [0, 0, 1, 0, 0, 1, 0, 0, 1]


def test_leaderboard_is_sent_on_join_and_then_only_when_it_refreshes():
    server = make()
    client = server.connect("a")
    server.handle_message(client, json.dumps({"t": "join", "name": "x"}))
    client.take()
    has_board = []
    for _ in range(31):
        server.tick()
        [frame] = client.take()
        has_board.append("lb" in decode_state(frame))
    assert has_board[0] is True
    assert has_board.count(True) <= 3  # first frame, then about every 15 ticks
    assert has_board.count(True) >= 2


# --- over a real websocket -------------------------------------------


def test_origin_check_blocks_other_sites_and_allows_the_configured_one():
    app = create_app(bots=0, seed=1, limits=Limits(allowed_origins=("https://good.example",)))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}):
                pass
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):  # no origin header at all
                pass
        with client.websocket_connect("/ws", headers={"origin": "https://good.example/"}) as ws:
            ws.send_text(json.dumps({"t": "join", "name": "x"}))
            assert json.loads(ws.receive_text())["t"] == "welcome"


def test_a_full_server_says_so_and_hangs_up():
    app = create_app(bots=0, seed=1, limits=Limits(max_players=1))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            first.send_text(json.dumps({"t": "join", "name": "x"}))
            first.receive_text()
            with client.websocket_connect("/ws") as second:
                assert json.loads(second.receive_text()) == {"t": "full", "reason": "full"}
                with pytest.raises(WebSocketDisconnect) as closed:
                    second.receive_text()
                assert closed.value.code == 1013


def test_a_silent_connection_is_closed_after_the_idle_timeout():
    app = create_app(bots=0, seed=1, limits=Limits(idle_timeout=0.3))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()
            assert closed.value.code == 1001
        assert client.get("/health").json()["connections"] == 0


def test_a_flooding_client_is_disconnected():
    app = create_app(bots=0, seed=1, limits=Limits(msg_rate=1, msg_burst=3, drop_after=5))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            for _ in range(30):
                ws.send_text(move())
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()  # nothing is queued for us, so the next thing we see is the close
            assert closed.value.code == 1008


def test_binary_frames_from_a_client_are_ignored():
    with TestClient(create_app(bots=0, seed=1)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_bytes(b"\x00\x01\x02")
            ws.send_text(json.dumps({"t": "join", "name": "x"}))
            assert json.loads(ws.receive_text())["t"] == "welcome"


def test_limits_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGAR_MAX_PLAYERS", "12")
    monkeypatch.setenv("AGAR_ALLOWED_ORIGINS", "https://a.example/, https://b.example")
    monkeypatch.setenv("AGAR_TRUST_PROXY", "1")
    limits = Limits.from_env()
    assert limits.max_players == 12
    assert limits.allowed_origins == ("https://a.example", "https://b.example")
    assert limits.trust_proxy is True
    assert limits.max_per_ip == Limits().max_per_ip
