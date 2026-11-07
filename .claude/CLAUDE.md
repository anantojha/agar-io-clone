# Blobs (agar-io-clone)

A real-time multiplayer blob-eating game: Python/Starlette WebSocket server (`game/`, `server/`) plus a plain-JavaScript canvas
client (`client/`). The server runs free on Render; the client runs free on GitHub Pages. All of the code was written with AI
coding tools, and future work is expected to continue that way.

## Skills in `.claude/skills/` - read the one that matches your task first

| Skill | Use it for |
|---|---|
| `blobs-architecture` | Start here for any task: layout, flows, commands, rules that must not break |
| `blobs-game-and-bots` | Rules, balance, bots, spatial hash, test patterns |
| `blobs-wire-protocol` | Anything sent over the WebSocket; keeping Python, JS and tests in sync |
| `blobs-deploy-and-operate` | Deploying, env vars, Actions/Render failures, "works locally but not online" |
| `blobs-capacity-and-load-testing` | Player caps, lag, bandwidth, load tests, and the unfinished capacity work |
| `blobs-ai-workflow` | Verification habits, git hygiene, what AI cannot do, handoff notes |

## Quick commands

```bash
pip install -r requirements-dev.txt
python -m pytest -q                      # always from the repo root
uvicorn server.app:app --port 8000       # set server: "" in client/config.js to play against it
```

## Non-negotiables

- Hosting stays **free with no credit card**. Stop and ask before anything that could need one.
- Pushing to `main` deploys. Use a branch and wait for the `tests` workflow.
- No secrets in the repo; check the git author email before pushing (the repo is public).
- Verify before claiming: report what was run and what was not.

## State of the project

Deployed and working. Open items: measure real capacity on the host and set `AGAR_MAX_PLAYERS`; pin dependency versions in
`requirements.txt`; fill the copyright holder in `LICENSE`. Details are in `blobs-capacity-and-load-testing`.
