# Phase 5: Free deployment plan

Written 2026-10-30. **Status: plan only. Nothing has been deployed or published.**

## Decisions already made

- **No credit cards.** Not for verification, not for a hold.
- **Sleeping is fine.** A one-minute wake-up on the first visit after idle is acceptable.
- **A public GitHub repo is fine.**
- **Hosting must be 100% free.**

## The main finding: no host is confirmed card-free

A web search found conflicting claims about card requirements. None of the sources is a vendor's own sign-up page, so
nothing below is settled until Step A.

| Host | Card? | Notes |
|---|---|---|
| **Hugging Face Spaces** (Docker) | Probably not | Free tier is 2 vCPU and 16 GB, far more than the 0.1 vCPU hosts. Sleeps after 48 h idle. The docs found suggest creating a Docker Space might need a paid plan, and nothing was found on WebSocket support. Unverified. |
| **Render** | Conflicting | Web services sleep after 15 min idle, and active WebSocket messages now count as activity (Feb 2026 change). Forum posts report a card prompt; one article says a $1 hold that is released; others say none. 0.1 vCPU, 512 MB, 750 h and 100 GB egress a month. |
| **Koyeb** | Conflicting | Described as never sleeping. One source says a $29 hold has applied since Feb 2026. 0.1 vCPU, 512 MB. Mistral AI agreed to acquire it in Feb 2026. |
| **SnapDeploy** | Claims no | 0.25 vCPU, WebSockets, no card, but that comes from its own marketing. |
| Fly.io, Oracle Always Free | No | Not usable without a card. Oracle also reclaims instances idle below 20% CPU over 7 days. |

## Who does what

I can't create accounts, enter passwords, or accept terms or OAuth prompts. **You do sign-ups and logins.** I do the
code, config files, tests and measurements, and I ask before anything goes public.

## Step A: Pick a host (about 15 minutes, you and me)

- [ ] Open each candidate's create-service page in the browser pane, in this order:
  1. Hugging Face Spaces
  2. Render
  3. Koyeb
  4. SnapDeploy
- [ ] For each, record: is there any payment step? Does the free tier allow a Docker or web service with WebSockets?
      Does it sleep?
- [ ] The first one with no payment step wins. Stop before entering anything.
- [ ] If none passes, use the fallback in Step H.

**Done when:** one host is chosen, or Step H is chosen.

## Step B: Prepare the repo (me, local only, nothing public)

**Code**
- [ ] `Dockerfile` and `.dockerignore`. Runs as a non-root user, listens on `$PORT`, uses `--proxy-headers`.
- [ ] `client/config.js` holding the server URL, replacing the `?server=` query.
- [ ] A "waking the server…" screen. It sends a no-CORS request to `/health` to wake a sleeping host, then retries the
      WebSocket with backoff for about 90 seconds.
- [ ] Pause the tick loop after about 60 seconds with no humans connected, and resume on the next connection.
- [ ] Bots fill only the gap up to a target population, so more players means fewer bots and CPU stays roughly flat.
- [ ] `--url` option for `tools/loadtest.py` so it can test a deployed server.
- [ ] A host adapter file for the winner:
  - Render: `render.yaml`
  - Hugging Face: README front matter with `sdk: docker` and `app_port`

**Repo hygiene before it goes public**
- [ ] Add a `LICENSE` (MIT by default unless you say otherwise).
- [ ] Scan for secrets (there should be none).
- [ ] Replace README details that only apply to this laptop.

**GitHub Actions**
- [ ] Run `pytest` on every push.
- [ ] Deploy `client/` to GitHub Pages.

**Tests**
- [ ] Cover pause-when-empty and bot filling.
- [ ] Build the Docker image, if Docker is installed here.

**Done when:** tests pass and the image builds locally.

## Step C: Publish the repo (you, then me)

- [ ] **Identity.** The git identity on this machine looks like a work email (`@bell.ca`). A public repo exposes the
      email on every commit. Use a personal GitHub account and its `noreply` address.
- [ ] **Employer check.** Check your employer's policy on personal projects built on a work laptop. That is your
      decision, not mine.
- [ ] I make the first commit with that identity.
- [ ] You create the public repo and approve the push.

**Done when:** the code is public and the `pytest` workflow is green.

## Step D: Deploy the server

- [ ] You connect the chosen host to the GitHub repo, or push the image.
- [ ] Set these variables:

| Variable | Value |
|---|---|
| `AGAR_TRUST_PROXY` | `1` |
| `AGAR_ALLOWED_ORIGINS` | `https://<you>.github.io` (origin only, no path) |
| `AGAR_MAX_PLAYERS` | 10–15 to start |

- [ ] Health check path is `/health`.

**Done when:** `/health` answers over `https` and a WebSocket connects from a browser.

## Step E: Deploy the client

- [ ] Enable Pages with the Actions workflow.
- [ ] Point `config.js` at the server's `wss://` address.

**Done when:** `https://<you>.github.io/<repo>/` loads, wakes the server, and a game starts.

## Step F: Verify on the real host

- [ ] **Cold start:** time how long it takes from a sleeping host to playable.
- [ ] **Two devices:** you on a laptop and a phone on mobile data, in the same game. This is the first test over a
      real network.
- [ ] **Load test:** run it against the deployed URL, starting small. Watch `tick_ms` and `cpu_s` in `/health`.
      If `tick_ms` regularly nears the 33 ms budget, set `AGAR_SEND_EVERY=3` or cut the bots.
- [ ] **Player cap:** set `AGAR_MAX_PLAYERS` from the numbers, then record the host, settings and measured cap in the
      README.
- [ ] **Bandwidth:** about 19 kB/s per player, roughly 68 MB per player-hour. A 100 GB monthly allowance covers about
      1,400 player-hours. Compression may lower this.

**Done when:** a friend on another network plays from the public link.

## Step G: Run it

- [ ] **Updates:** pushing to `main` redeploys.
- [ ] **Rollback:** redeploy the previous commit.
- [ ] **If the host changes terms:** the Docker image moves to another host with a config change.
- [ ] **Billing:** if a card is ever added, check the billing page for stray paid resources.
- [ ] **Warm-up pinger:** optional and skipped by default. It may go against the host's terms.

## Step H: Fallback with no host

Run the server on your own machine and expose it with a free Cloudflare quick tunnel. This is from memory and needs
verifying.

- Needs no account.
- Needs `cloudflared` installed, which I would only do with your OK.
- The URL changes every run, so the tunnel serves the client too. Friends open that one link, and there is no Pages
  step.
- The game is only up while your laptop is.

## Expected capacity

On the development laptop each player costs about 0.3% of one core. A 0.1 vCPU host is probably several times slower
than one of those cores, so expect roughly 8–25 players. Step F measures it. Hugging Face's 2 vCPU would remove this
problem.

## Risks

| Risk | What happens |
|---|---|
| No free host passes the card check | Step H becomes the plan |
| 0.1 vCPU is too slow | Fewer players, `AGAR_SEND_EVERY=3`, fewer bots |
| Free tiers change | Moving hosts is a config change, because the app is one Docker image |
| Public repo | Anyone can read the code. No secrets go in it |

## Order

A, then B, then C, D and E, then F.

## Sources

- [Hugging Face Spaces overview](https://huggingface.co/docs/hub/en/spaces-overview)
- [Hugging Face Space runtime and sleep](https://huggingface.co/docs/huggingface_hub/package_reference/space_runtime.md)
- [Render card requirement thread](https://community.render.com/t/free-but-credit-card-first/24630)
- [Render changelog: WebSocket activity](https://render.com/changelog/free-web-services-now-remain-active-while-receiving-websocket-messages)
- [Free Docker hosting roundup](https://flywp.com/blog/9769/best-free-docker-hosting-platforms)
- [Free Docker hosting without a card](https://hostadvice.com/docker-hosting/free-docker-hosting-no-credit-card/)
- [SnapDeploy free backend hosting](https://dev.to/snapdeploy/free-backend-hosting-7-platforms-that-wont-kill-your-api-2026-1i1g)
- [Koyeb vs free container tier](https://snapdeploy.dev/blog/koyeb-vs-free-container-tier)
- [Oracle Always Free resources](https://docs.oracle.com/iaas/Content/FreeTier/resourceref.htm)
