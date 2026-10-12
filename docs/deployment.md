# Public deployment

The app can be shared with testers over HTTPS from any machine that runs Docker Compose,
without opening a port: a Cloudflare Tunnel connects out to Cloudflare and gives the app a
public `https://` address. HTTPS matters: without it the microphone is blocked on every phone.

Safeguards for a public test, outermost first (details in
[ADR-11.2](adr/step-11.2-public-deployment-hardening.md)):

| Layer | Where | What it stops |
|-------|-------|---------------|
| Cloudflare Tunnel, app port bound to `127.0.0.1` | `docker-compose.public.yml`, `docker-compose.yml` | direct access that bypasses the proxy and the firewall |
| nginx rate limit per client IP (6 recommendations or recordings per minute, 5 API requests per second) | `frontend/nginx.conf` | a script flooding the API |
| Per-visitor daily limits (10 recommendations, 20 recordings) | `DAILY_RECOMMENDATION_LIMIT`, `DAILY_TRANSCRIPTION_LIMIT` | one person using up everyone's tests |
| Daily limits of all visitors together (100, 200) | `DAILY_TOTAL_RECOMMENDATION_LIMIT`, `DAILY_TOTAL_TRANSCRIPTION_LIMIT` | the month's budget going in one day, also through new browsers or private windows |
| OpenAI project hard spend limit | platform.openai.com | everything else; the app then says `budget_exhausted` |
| Per-browser history, privacy note, no `/api/docs` | backend, home page | testers reading each other's descriptions; advertising the API |

## Before the first start (once)

1. **OpenAI:** a dedicated project for the deployment with a **hard** monthly spend limit
   (*Project settings → Limits*), only the models in `.env` allowed, its own API key in `.env`.
   Turn auto-recharge off. Keep running evals with another key in another project, so evals
   never use the testers' budget.
2. **LangSmith:** `LANGSMITH_PROJECT=song-recommender-public` in `.env`, so testers' runs are
   separate from yours. The project is created by the first trace.
3. **Spotify (optional):** a separate Client ID for the deployment. It shares the account's
   quota with your other apps, but can be revoked on its own.
4. **`.env`:** readable by you only (`chmod 600 .env`), never committed (`git status` must not
   list it, nor `data/`).

## Stage 1: from your PC with a Quick Tunnel (free, random address)

Prerequisites: Docker Desktop running, with *Settings → Resources → WSL integration* enabled for
your WSL distribution (`docker info` works in WSL).

```bash
scripts/public.sh start   # build, start, wait for the tunnel, print the public address
scripts/public.sh url     # print the address again
scripts/public.sh stop    # kill switch: off the internet, still running locally
scripts/public.sh down    # stop everything; ./data is kept
scripts/public.sh stats   # usage of the last 7 days, today's totals against the limits
```

`start` prints `https://<words>.trycloudflare.com` once the address answers; share it. No
Cloudflare account is needed. The address cannot be chosen: it is random, and a new one comes
with every start of the tunnel container (`start` after `stop`, a reboot, a Docker restart);
`start` while the tunnel runs keeps it. A chosen name needs a named tunnel on your own domain
(Stage 2).

Without the script, the same is `docker compose -f docker-compose.yml -f
docker-compose.public.yml up --build -d`, then `… logs tunnel | grep -o
'https://[a-z0-9-]*\.trycloudflare\.com'` a few seconds later (the address is logged about 5 s
after the tunnel starts). Limits of a Quick Tunnel: no uptime guarantee, a new address every
time the `tunnel` container starts, at most 200 requests in flight. Keep the PC awake (Windows
power settings) and Docker Desktop running.

Tip: `export COMPOSE_FILE=docker-compose.yml:docker-compose.public.yml` lets you type plain
`docker compose …` in that shell.

`scripts/public.sh` reads the Quick Tunnel address from the logs; with a named tunnel (Stage 2)
`start` reports that it found none, and the address is your public hostname.

Check before inviting testers, on a phone over mobile data (not your Wi-Fi):

- one text and one voice recommendation work;
- the home page shows the privacy note;
- `https://<address>/api/docs` answers `404`.

## Stage 2: fixed address (named tunnel)

1. Move a domain's DNS to a free Cloudflare account.
2. Cloudflare dashboard → *Zero Trust → Networks → Tunnels → Create a tunnel* (type
   cloudflared); copy its token. Add a public hostname, e.g. `songs.example.pl`, with service
   `http://frontend:80`.
3. Put the token in `.env` as `TUNNEL_TOKEN=…`.
4. In `docker-compose.public.yml`, replace the Quick Tunnel `command` with the named-tunnel
   lines (`command: tunnel --no-autoupdate run` and the `TUNNEL_TOKEN` environment).
5. `docker compose -f docker-compose.yml -f docker-compose.public.yml up -d`.

The same files work on a small VPS (Docker Engine + Compose plugin; `mkdir -p data && sudo chown
1000:1000 data`). With the domain on Cloudflare, a free WAF rate-limiting rule on
`/api/recommendations` can be added as another layer in front of nginx.

## Sizing the limits to the budget

1. Run 10 recommendations on the deployed app and read their cost on the OpenAI Usage page
   (filtered by the project), or from the token counts in LangSmith.
2. `DAILY_TOTAL_RECOMMENDATION_LIMIT` ≈ monthly hard limit ÷ 30 ÷ cost of one recommendation,
   leaving room for transcriptions (`gpt-transcribe` is billed per audio minute).
3. Change the values in `.env` and run `docker compose … up -d` (the backend restarts).

## Kill switch and monitoring

Fastest first:

- `scripts/public.sh stop` (= `docker compose -f docker-compose.yml -f docker-compose.public.yml
  stop tunnel`): the app is off the internet in seconds; it keeps running locally with its
  data. Back online with `scripts/public.sh start`, under a new address.
- A leaked key: revoke it in the OpenAI project; the app then answers with an error.
- Transcription costs spike: `STT_PROVIDER=none` and `up -d` removes only the microphone.

Where to look:

- `scripts/public.sh stats`: recommendations per day (completed, failed, waiting for an answer,
  voice), transcriptions, distinct visitors, today's totals against
  `DAILY_TOTAL_*_LIMIT`, error codes and ratings. Read-only, from `data/app.db`.
- `docker compose logs -f frontend | grep -v Wget`: every request live, with the visitor's IP
  (`Wget` lines are the healthcheck).

- OpenAI Usage (by project and key): spend per day.
- LangSmith project `song-recommender-public`: runs, latency, errors, testers' ratings.
- `docker compose logs -f backend`: `Daily limit of all visitors reached`, `LLM budget is used
  up`, OpenAI 429s, Spotify and YouTube quota.
- `docker compose logs -f frontend`: nginx `limiting requests` lines when the rate limit
  rejects a client.

## Backup

Testers' feedback lives in `data/app.db`. A consistent copy while the app runs:

```bash
docker compose exec backend python -c "import sqlite3; sqlite3.connect('/data/app.db').backup(sqlite3.connect('/data/app-backup.db'))"
```

The copy is `data/app-backup.db` on the host; move it somewhere else (another disk, cloud
storage). On a server, run it daily from cron.
