# agar-clone

Agar.io clone: Python game server, browser client. Plays locally first, then deploys to a free host.

## Play locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn server.app:app --port 8000
```

Open http://localhost:8000, type a name, press Play.

- **Mouse** steers. **Space** splits (needs mass 40+). **W** ejects mass (hold to keep feeding).
- Split pieces rejoin after about 10 seconds, longer when big.
- Green spiky **viruses** burst any blob of mass 125+ into pieces; smaller blobs can hide behind them.
- Touch screens get Split and Eject buttons.

`/health` shows players, bots, how long a tick takes against its 33 ms budget, CPU seconds used, and bytes sent.

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `AGAR_BOTS` | 15 | Bots that fill the arena |
| `AGAR_SEND_EVERY` | 2 | Send a world frame every N ticks (2 means 15 per second) |
| `AGAR_MAX_PLAYERS` | 25 | Open connections before new ones get "server full" |
| `AGAR_MAX_PER_IP` | 5 | Connections per address |
| `AGAR_MSG_RATE`, `AGAR_MSG_BURST` | 60, 120 | Messages per second a client may send, and its burst |
| `AGAR_DROP_AFTER` | 300 | Rate-limited messages before the client is disconnected |
| `AGAR_IDLE_TIMEOUT` | 30 | Seconds of silence before a connection is closed |
| `AGAR_ALLOWED_ORIGINS` | any | Comma-separated sites allowed to open a WebSocket, e.g. `https://me.github.io` |
| `AGAR_TRUST_PROXY` | off | Set to `1` behind a proxy so per-address limits use `X-Forwarded-For` |

## Develop

```bash
.venv/bin/python -m pytest                        # tests
.venv/bin/python bench/bench_tick.py --players 50 # cost of one game tick (--split for constant splitting)
.venv/bin/python bench/sim_bots.py --minutes 10   # bots only: how big they get (tuning decay and food)
```

Load test: start a server on its own port with higher caps, then point fake players at it.

```bash
AGAR_MAX_PLAYERS=200 AGAR_MAX_PER_IP=200 .venv/bin/uvicorn server.app:app --port 8002 &
.venv/bin/python tools/loadtest.py --clients 30 --seconds 15 --port 8002
```

On a laptop core, 60 fake players plus 15 bots used about 17% of one core, around 0.3% per player, and
about 19 kB/s of download per player. Re-measure on the real host: free hosts give a fraction of a core.

To try split and viruses without growing first, run a server where everyone starts at mass 300:

```bash
.venv/bin/python -c "
from dataclasses import replace
import uvicorn
from game import Config
from server.app import create_app
uvicorn.run(create_app(bots=10, config=replace(Config(), start_mass=300.0, virus_count=25)), port=8001)"
```

## Layout

- `game/`: the rules (`World.step(dt)`), with no networking. Numbers to tune are in `game/config.py`.
- `server/game_server.py`: messages, the tick loop, per-client snapshots, rate limits. The control messages are described at the top.
- `server/protocol.py`: the binary world-frame layout. `client/protocol.js` reads it, and a test runs that file under node against what Python writes.
- `server/limits.py`: caps and abuse limits, read from the environment.
- `server/bots.py`: bot AI (flee bigger cells, chase smaller ones, split to catch prey, eat food).
- `server/app.py`: Starlette app: `/ws`, `/health`, and the static client.
- `client/`: `index.html`, `game.js` and `protocol.js`, plain canvas with no build step.
- `bench/`, `tools/loadtest.py`, `tests/`.

## Roadmap

0. Scaffold (done)
1. Core simulation (done)
2. Local playable game: server loop, canvas client, bots (done)
3. Split, merge, eject mass, viruses (done)
4. Binary protocol, rate limits and caps, interpolation, load test, bot balance (done)
5. Free deploy (static client + one WebSocket server)
