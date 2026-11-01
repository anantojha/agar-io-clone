import asyncio
import contextlib
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket

from game import Config

from .game_server import Client, GameServer, _dumps
from .limits import Limits

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"

# WebSocket close codes
CLOSE_GOING_AWAY = 1001
CLOSE_POLICY = 1008
CLOSE_TRY_AGAIN_LATER = 1013


async def _watch(ws: WebSocket, client: Client, game: GameServer) -> None:
    """Close the connection when nothing has arrived for idle_timeout seconds."""
    idle = game.limits.idle_timeout
    try:
        while True:
            await asyncio.sleep(min(idle / 3, 5.0))
            if game.clock() - client.last_seen > idle:
                await ws.close(code=CLOSE_GOING_AWAY)
                return
    except Exception:
        pass


async def _pump(ws: WebSocket, client: Client) -> None:
    """Send whatever the game has queued for this client. Ends quietly when the socket closes."""
    try:
        while True:
            await client.event.wait()
            client.event.clear()
            for message in client.take():
                if isinstance(message, bytes):
                    await ws.send_bytes(message)
                else:
                    await ws.send_text(message)
    except Exception:
        pass


def _client_ip(ws: WebSocket, limits: Limits) -> str:
    if limits.trust_proxy:
        forwarded = ws.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


def create_app(
    bots: int | None = None,
    seed: int | None = None,
    config: Config | None = None,
    limits: Limits | None = None,
    send_every: int | None = None,
) -> Starlette:
    if bots is None:
        bots = int(os.environ.get("AGAR_BOTS", "15"))
    if limits is None:
        limits = Limits.from_env()
    if send_every is None:
        send_every = int(os.environ.get("AGAR_SEND_EVERY", "2"))
    game = GameServer(config, bots=bots, seed=seed, limits=limits, send_every=send_every)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        loop_task = asyncio.create_task(game.run())
        yield
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task

    async def health(request):
        return JSONResponse({"status": "ok", **game.stats()})

    async def play(ws: WebSocket):
        if limits.allowed_origins:
            origin = ws.headers.get("origin", "").rstrip("/")
            if origin not in limits.allowed_origins:
                await ws.close(code=CLOSE_POLICY)  # refused before the handshake completes
                return
        await ws.accept()
        ip = _client_ip(ws, limits)
        reason = game.refusal(ip)
        if reason:
            await ws.send_text(_dumps({"t": "full", "reason": reason}))
            await ws.close(code=CLOSE_TRY_AGAIN_LATER)
            return

        client = game.connect(ip)
        sender = asyncio.create_task(_pump(ws, client))
        watchdog = asyncio.create_task(_watch(ws, client, game))
        try:
            while True:
                event = await ws.receive()
                if event["type"] == "websocket.disconnect":
                    break
                text = event.get("text")
                if text is not None and not game.handle_message(client, text):
                    await ws.close(code=CLOSE_POLICY)
                    break
                # Binary frames from clients are not part of the protocol; ignore them.
        finally:
            sender.cancel()
            watchdog.cancel()
            game.disconnect(client)

    app = Starlette(
        routes=[
            Route("/health", health),
            WebSocketRoute("/ws", play),
            Mount("/", app=StaticFiles(directory=CLIENT_DIR, html=True), name="client"),
        ],
        lifespan=lifespan,
    )
    app.state.game = game
    return app


app = create_app()
