"""Connect N fake players to a running server and report what it costs.

    .venv/bin/uvicorn server.app:app --port 8002 &
    .venv/bin/python tools/loadtest.py --clients 30 --seconds 20 --port 8002

Each fake player joins, steers toward random points, splits and ejects now and then, and rejoins
after being eaten. It never decodes the world, so the cost measured here is the server's, not this
script's. Server CPU comes from /health (process CPU seconds), so run the server on its own.
Raise AGAR_MAX_PLAYERS and AGAR_MAX_PER_IP on the server to go past its default caps.
"""
import argparse
import asyncio
import json
import random
import statistics
import time
import urllib.request

import websockets


def health(port: int) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never go through a proxy
    with opener.open(f"http://127.0.0.1:{port}/health", timeout=5) as response:
        return json.load(response)


class Stats:
    def __init__(self):
        self.frames = 0
        self.bytes = 0
        self.gaps: list[float] = []
        self.deaths = 0
        self.refused = 0
        self.closed_early = 0


async def player(i: int, args, stats: Stats, stop: asyncio.Event):
    rng = random.Random(i)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{args.port}/ws", proxy=None, max_size=2**22) as ws:
            await ws.send(json.dumps({"t": "join", "name": f"load{i}"}))

            async def act():
                while not stop.is_set():
                    await ws.send(json.dumps({"t": "move", "x": rng.uniform(0, 4000), "y": rng.uniform(0, 4000)}))
                    for _ in range(8):  # moves at about 15 a second, like the real client
                        if stop.is_set():
                            return
                        await asyncio.sleep(1 / 15)
                        await ws.send(json.dumps({"t": "move", "x": rng.uniform(0, 4000), "y": rng.uniform(0, 4000)}))
                    if rng.random() < 0.3:
                        await ws.send(json.dumps({"t": "split"}))
                    if rng.random() < 0.3:
                        await ws.send(json.dumps({"t": "eject"}))

            actor = asyncio.create_task(act())
            last = None
            try:
                while not stop.is_set():
                    try:
                        message = await asyncio.wait_for(ws.recv(), 1.0)
                    except asyncio.TimeoutError:
                        continue
                    now = time.perf_counter()
                    if isinstance(message, bytes):
                        stats.frames += 1
                        stats.bytes += len(message)
                        if last is not None:
                            stats.gaps.append((now - last) * 1000)
                        last = now
                    else:
                        data = json.loads(message)
                        if data["t"] == "dead":
                            stats.deaths += 1
                            last = None
                            await ws.send(json.dumps({"t": "join", "name": f"load{i}"}))
                        elif data["t"] == "full":
                            stats.refused += 1
                            return
            finally:
                actor.cancel()
    except (websockets.ConnectionClosed, OSError):
        stats.closed_early += 1


async def main(args):
    before = health(args.port)
    stats = Stats()
    stop = asyncio.Event()
    started = time.perf_counter()
    tasks = []
    for i in range(args.clients):
        tasks.append(asyncio.create_task(player(i, args, stats, stop)))
        await asyncio.sleep(0.05)  # join gradually, like real arrivals
    await asyncio.sleep(args.seconds)
    mid = health(args.port)
    stop.set()
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started

    window = args.seconds
    cpu = (mid["cpu_s"] - before["cpu_s"]) / (window + args.clients * 0.05)
    gaps = sorted(stats.gaps) or [0]
    pct = lambda p: gaps[min(len(gaps) - 1, int(len(gaps) * p))]
    print(f"clients={args.clients} seconds={window} players_on_server={mid['players']} bots={mid['bots']}")
    print(f"frames/s per client: {stats.frames / args.clients / elapsed:5.1f}   "
          f"bytes/s per client: {stats.bytes / args.clients / elapsed / 1000:6.1f} kB   "
          f"avg frame: {stats.bytes / max(stats.frames, 1):6.0f} B")
    print(f"gap between frames ms: p50={pct(0.5):.0f} p95={pct(0.95):.0f} p99={pct(0.99):.0f} max={gaps[-1]:.0f}")
    print(f"server tick: avg {mid['tick_ms']} ms of {mid['tick_budget_ms']} ms budget")
    print(f"server CPU: {cpu * 100:.1f}% of one core   ({cpu * 100 / max(args.clients, 1):.2f}% per player)")
    print(f"deaths={stats.deaths} refused={stats.refused} dropped_early={stats.closed_early}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=30)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--port", type=int, default=8002)
    asyncio.run(main(ap.parse_args()))
