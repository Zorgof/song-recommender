# ADR-09: Step 9 — Docker

- Status: Accepted
- Date: 2026-10-11
- Step: 9

## Context

Step 9 of the [implementation plan](../implementation-plan.md) makes the app run with one
command (FR-60):
- multi-stage Dockerfiles: the backend on `python:3.14.8-slim` + uv, non-root; the frontend
  built on Node LTS and served by nginx;
- `docker-compose.yml` with healthchecks, `depends_on: service_healthy` and the `./data`
  volume;
- `docker-compose.dev.yml` with bind mounts and hot reload.

Requirements carried over from earlier ADRs:
- nginx must allow 10 MB uploads (ADR-06);
- nginx must allow long requests: one recommendation takes 10–40 s (ADR-05);
- nginx must serve `index.html` for client-side routes such as `/history` (ADR-07).

"Done when": `cp .env.example .env`, filling in the keys, then `docker compose up --build`
gives a working app at `http://localhost:8080`, and data survives a restart.

## Decision / What was implemented

### Backend image — `backend/Dockerfile`, `backend/.dockerignore`

- **Build stage.**
  - `python:3.14.8-slim` with uv `0.12.23`, copied from `ghcr.io/astral-sh/uv`.
  - `uv sync --locked --no-dev --no-install-project`: the exact `uv.lock` versions, without
    pytest, ruff or mypy. The project itself is not a package (`tool.uv.package = false`).
  - Bytecode is compiled, the uv cache is a BuildKit cache mount, and the image's Python is
    used, not a downloaded one.
- **Runtime stage.**
  - A fresh `python:3.14.8-slim` with only `.venv`, `alembic.ini` and `app/`.
  - User `app` with **uid/gid 1000** (build args `APP_UID`/`APP_GID`).
  - Environment: `APP_ENV=production`, `DATA_DIR=/data`, `PYTHONUNBUFFERED`,
    `PYTHONDONTWRITEBYTECODE`.
- **Command:** `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
  --proxy-headers --forwarded-allow-ips *`.
  - **One worker on purpose.** The app uses SQLite, has one local user, and keeps state in the
    process: the YouTube quota pause and the Spotify token.
  - Migrations still run at startup (ADR-01).
- `.dockerignore` keeps `.venv`, `data`, `tests`, caches and `.env` out of the build context.
- Image size: 493 MB, mostly LangChain with three provider SDKs.

### Frontend image — `frontend/Dockerfile`, `frontend/nginx.conf`

- **Stages:**
  - `deps`: `node:24.21.0-alpine`, `npm ci` with an npm cache mount.
  - `dev`: the Vite dev server, used by the dev override.
  - `build`: `npm run build`, i.e. `tsc -b` + `vite build`.
  - Runtime: `nginx:1.30-alpine` (stable line, 1.30.5), 93 MB.
- **`nginx.conf`:**
  - **`/api/` → `http://backend:8000`.** The address goes through a variable and Docker's DNS
    resolver (`127.0.0.11`, `valid=10s`). nginx therefore finds the backend again after it is
    recreated with a new IP address, without restarting nginx.
  - `proxy_read_timeout` / `proxy_send_timeout` 120 s; `X-Forwarded-*` and `X-Real-IP`
    headers.
  - **`client_max_body_size 11m`.** The backend enforces the exact 10 MB limit, with its own
    error code.
  - **JSON error pages for errors nginx produces itself**, in the API's error shape:
    - 413 → `{"error":{"code":"audio_too_large",…}}`;
    - 502 (backend unreachable) → `{"error":{"code":"network_error",…}}`.

    The UI then shows a localized message instead of `internal_error`. Errors from the
    backend pass through unchanged.
  - **`/assets/`**: `Cache-Control: public, max-age=31536000, immutable`, since Vite's file
    names are content-hashed. A missing asset is a 404, not `index.html`.
  - **`/`**: `try_files $uri /index.html`, so `/history` works on reload. `index.html` is sent
    with `Cache-Control: no-cache`, so a new build is picked up at once.
  - gzip for CSS, JS, JSON and SVG; `X-Content-Type-Options: nosniff`;
    `Referrer-Policy: strict-origin-when-cross-origin`.

### `docker-compose.yml`

- **`backend`:**
  - `env_file: .env`. `environment` sets `APP_ENV: production` and `DATA_DIR: /data`; these
    win over the `.env` values, which are meant for running without Docker
    (`DATA_DIR=./data`, `APP_ENV=development`).
  - Bind mount `./data:/data` in long syntax with `create_host_path: false` (see Issues).
  - Healthcheck: `python -c "urllib.request.urlopen('http://127.0.0.1:8000/api/health')"`
    every 10 s, `start_period` 20 s. The slim image has no curl.
  - `restart: unless-stopped`.
- **`frontend`:**
  - Published on `${APP_PORT:-8080}:80`.
  - `depends_on: backend: condition: service_healthy`.
  - Healthcheck with busybox `wget`; `restart: unless-stopped`.
- The backend is not published on the host; only nginx is.

### `docker-compose.dev.yml` (override)

- **Backend:**
  - `APP_ENV=development`;
  - `uvicorn --reload --reload-dir /app/app` with `./backend/app` bind-mounted;
  - port 8000 published.
- **Frontend:**
  - the `dev` stage, tagged **`song-recommender-frontend-dev`**;
  - `./frontend` bind-mounted, with `node_modules` kept from the image (anonymous volume);
  - `API_PROXY_TARGET=http://backend:8000`;
  - ports replaced with `!override` (5173 only);
  - its own healthcheck.
- `vite.config.ts` reads `API_PROXY_TARGET` (default `http://localhost:8000`), so the same
  config works on the host and in Docker.

### Repository changes

- **`data/.gitkeep`.** The root `data/` directory is now part of the repository (empty), so a
  fresh clone bind-mounts a directory owned by the user.
- **`.gitignore`.** The old pattern `data/` ignored *every* directory named `data`, including
  any future source directory such as `src/lib/data/`. It is replaced by anchored patterns:
  `/data/*`, `!/data/.gitkeep`, `/backend/data/`.
- **Backend: `ensure_writable_dir()`** in `app/db/migrate.py`, called before migrations. An
  unwritable data directory now stops startup with a `ConfigurationError` that names the
  directory and the uid and gives the fix, instead of SQLite's "unable to open database file".
  It comes with two new tests.
- **Documentation:**
  - root `README.md`: "Run it with Docker", updated status, stack and layout;
  - `docs/development.md`: "Development in Docker" and an image table;
  - plan 2.6: the error responses produced by nginx.

## Deviations from the plan

- **`nginx:1.30-alpine` instead of `nginx:alpine`.** It is pinned to the stable line, so a
  rebuild cannot silently move to a new mainline version.
- **uid/gid 1000 instead of an arbitrary system user.** This avoids permission problems with
  the bind-mounted `./data` (see Issues).

## Issues encountered and how they were solved

1. **Docker was not reachable from WSL at first.** `/usr/bin/docker` pointed to the missing
   `/mnt/wsl/docker-desktop`. The files were written and the backend's runtime command was
   checked without Docker:
   - the image's `uv sync --no-dev` was replicated into a temporary directory;
   - the `CMD` was run with `APP_ENV=production`;
   - the healthcheck command exited 0, and the logs were JSON.

   After the developer started Docker Desktop with WSL integration, everything was verified
   in Docker (see Live verification).
2. **Ownership of the bind-mounted `./data`.**
   - The backend runs as uid 1000. When `./data` is missing, Docker creates it **owned by
     root**. The backend then cannot write, fails with "unable to open database file", and
     restarts in a loop. This was reproduced.
   - Fixes:
     - (a) `data/.gitkeep`, so the directory always exists in a clone;
     - (b) `create_host_path: false`, which makes Docker Engine on Linux refuse to start
       instead. **Docker Desktop ignores this option**, as observed here: it created the
       directory as root anyway;
     - (c) the backend's startup check, which now prints: *"The data directory /data is not
       writable by uid 1000. … `sudo chown 1000:1000 data`"*.
   - A root entrypoint that chowns and drops privileges would also work. It was not chosen:
     it adds a root phase to every start for a case that (a) prevents.
3. **The dev build replaced the production image.** Both used the tag
   `song-recommender-frontend`, so after a dev run, `docker compose up` without `--build` would
   have started Vite instead of nginx. The dev image now has its own tag. Checked: the
   production image ID is unchanged after a dev build.
4. **nginx-generated errors were HTML.**
   - A 12 MB upload got nginx's HTML 413 page, and a stopped backend gave HTML 502. The UI
     would have shown "unexpected error".
   - They are now JSON with `audio_too_large` / `network_error`.
   - Also removed: a doubled `Cache-Control` header, caused by `expires` plus `add_header`.
5. **zsh does not word-split unquoted variables.** A `$DC` holding `docker compose -f … -f …`
   failed as "command not found". `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` is
   used instead, and is now also documented as the convenient way to use the dev override.

## Live verification

Docker Engine 29.8.0 (Docker Desktop, WSL 2), Compose v5.5.1, buildx 0.37. The developer's
`.env` was used.

| Check | Result |
|-------|--------|
| `docker compose config` (prod, prod + dev) | valid; `APP_ENV`/`DATA_DIR` overrides applied; dev ports replaced by `!override` |
| `docker compose build` | both images built with no warnings (23 s); backend 493 MB, frontend 93 MB |
| `docker compose up -d` | backend healthy, then frontend started and healthy, in 11 s; backend runs as `uid=1000(app)`; `data/app.db` and `checkpoints.db` owned by the host user |
| `GET :8080/`, `/history` | 200 `index.html` (SPA fallback), `no-cache`, security headers |
| `GET` a hashed `/assets/*.js` / a missing asset | 200, gzip, one-year immutable cache / 404 |
| `GET /api/meta` via nginx | `environment: production`, STT and LangSmith enabled; `X-Request-ID` passed back |
| PL recommendation via nginx | 200 in 12.5 s: Bill Evans - Peace Piece, both links verified, Polish explanation |
| `hmm` (EN) → clarification → answer | `needs_clarification` → `completed` (Tycho - A Walk) |
| `POST /api/transcriptions` with the PL clip via nginx | 200, exact Polish text, `language: pl` |
| Uploads of 10 MB / 10 MB + 1 B / 12 MB | reaches the backend (rejected by OpenAI as non-audio: `invalid_audio`) / backend 413 `audio_too_large` / nginx 413 JSON `audio_too_large` |
| Backend stopped | `/api/*` → 502 JSON `network_error`; the SPA still loads |
| Backend recreated on a new IP (172.18.0.2 → .4), nginx not restarted | `/api/health` 200 through nginx |
| Paused clarification, then backend restart, then answer | `completed` (Nick Drake - From The Morning): the checkpoint survived in `./data` |
| `docker compose down` + `up` | history unchanged (same items and feedback) |
| Dev override | backend `development` on :8000, Vite on :5173 proxying to `backend:8000`, `/history` 200, :8080 closed; editing `backend/app/__init__.py` → "WatchFiles detected changes… Reloading"; editing `src/App.tsx` → Vite "hmr update" (both files restored afterwards) |
| Fresh copy of the repository (tracked files + `.env`), project `sr-fresh`, port 8081 | builds and starts; health 200; `data/` populated by the host user |
| Same copy with `data/` deleted / root-owned | Docker Desktop creates it as root; the backend stops with the "not writable by uid 1000 … chown" message |
| Backend tests / ruff / mypy | 298 passed; clean; no issues in 83 files |
| Frontend tests / lint / format / build | 65 passed; clean; clean; succeeds |

The temporary project, its images and the IP-placeholder container were removed afterwards.
The production stack was left running on :8080.

## Consequences

- **The app runs with `docker compose up --build -d`** at `http://localhost:8080`. History
  and paused requests live in `./data` on the host.
- **The microphone needs a secure context.** It works at `http://localhost:8080`. Access from
  another device needs HTTPS in front of nginx; the step 11 troubleshooting guide documents
  this.
- **The backend image is large** (493 MB) because all three provider SDKs are installed
  (FR-20: switching providers by configuration only). Optional dependency groups per provider
  could shrink it, at the cost of rebuilding when switching.
- **No Content-Security-Policy yet.** The Spotify embed and the album-art CDNs would have to be
  allow-listed and tested in a real browser. It can be added once those origins are confirmed.
- **Step 10 (evals)** can run against the Docker backend or the host.

## Verification

| Command / check | Result |
|-----------------|--------|
| `docker compose up --build -d`, open `http://localhost:8080` | working app, see Live verification |
| Data after `docker compose down` / `up` and after a backend restart | kept |
| `cd backend && uv run pytest -q` | 298 passed |
| `uv run ruff check .`, `ruff format --check .`, `uv run mypy` | clean |
| `cd frontend && npm test`, `npm run lint`, `npm run format:check`, `npm run build` | 65 passed; clean; clean; succeeds |
