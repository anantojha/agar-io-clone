import json

from starlette.testclient import TestClient

from server.app import create_app
from server.protocol import decode_state


def test_health_reports_stats():
    with TestClient(create_app(bots=3, seed=1)) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["bots"] == 3
    assert body["players"] == 0


def test_serves_the_client_page():
    with TestClient(create_app(bots=0, seed=1)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "<canvas" in response.text


def test_join_over_a_websocket_gets_welcome_then_state():
    with TestClient(create_app(bots=2, seed=1)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"t": "join", "name": "Ada"}))
            welcome = json.loads(ws.receive_text())
            assert welcome["t"] == "welcome"
            assert welcome["map"] == 4000

            frame = ws.receive()
            while "bytes" not in frame or frame["bytes"] is None:
                frame = ws.receive()
            state = decode_state(frame["bytes"])
            assert len(state["me"]) == 3
            assert any(cell[1] == welcome["id"] for cell in state["c"])
            assert "Ada" in state["n"].values()
            assert state["lb"]

            ws.send_text(json.dumps({"t": "move", "x": 10, "y": 10}))
            assert client.get("/health").json()["players"] == 1
        assert client.get("/health").json()["players"] == 0


def test_garbage_does_not_kill_the_connection():
    with TestClient(create_app(bots=0, seed=1)) as client:
        with client.websocket_connect("/ws") as ws:
            for junk in ["not json", "[]", "null", '{"t":"move","x":"a"}', "x" * 5000]:
                ws.send_text(junk)
            ws.send_text(json.dumps({"t": "join", "name": "Ok"}))
            assert json.loads(ws.receive_text())["t"] == "welcome"
