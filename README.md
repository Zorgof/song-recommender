# song-recommender

Simple, agent-based song recommendation for your daily use.

Describe your mood and how your day looks — by text or by voice — and a multi-agent LLM
system recommends **one song** that fits, with a Spotify player embedded in the page, a
YouTube link and a short explanation. Every decision is traced in LangSmith so the selection
logic can be inspected and tuned.

> **Status:** the app runs end to end with Docker Compose (step 9 of the
> [implementation plan](docs/implementation-plan.md)). Evals and the full documentation follow
> in steps 10 and 11.

## Run it with Docker

Prerequisites: Docker with Compose v2 (on Windows: Docker Desktop with WSL integration), an
OpenAI API key, Spotify and YouTube API credentials, and optionally a LangSmith key. Each
variable is explained in [`.env.example`](.env.example).

```bash
cp .env.example .env          # then fill in the keys
docker compose up --build -d  # first build takes a few minutes
```

Open **http://localhost:8080** (change the port with `APP_PORT` in `.env`). The microphone
works on `localhost`; from another device it needs HTTPS.

- History and paused requests are stored in `./data` (`app.db`, `checkpoints.db`) and survive
  restarts and rebuilds. The directory must be writable by uid 1000 (the backend's user).
- `docker compose logs -f backend` shows the backend's JSON logs; `docker compose down` stops
  the app.
- After pulling new code, run `docker compose up --build -d` again.

## Documentation

- [Requirements](docs/requirements.md)
- [Technical implementation plan](docs/implementation-plan.md)
- [Development environment](docs/development.md) — toolchain setup, Docker development mode, `.editorconfig`, code-quality tools
- [Architecture Decision Records](docs/adr/README.md)

## Tech stack

| Area | Technology |
|------|-----------|
| Backend | Python 3.14.8, FastAPI, LangGraph, LangChain (OpenAI / Anthropic / Gemini) |
| Observability | LangSmith |
| Frontend | React 19, TypeScript, Vite, TanStack Query, Tailwind CSS, react-i18next (EN/PL) |
| Storage | SQLite |
| Runtime | Docker Compose: backend (uvicorn) and frontend (nginx) |

## Repository layout

```
backend/    FastAPI app and agents (Python, uv)
frontend/   React SPA (TypeScript, Vite)
docs/       requirements, implementation plan, ADRs
data/       SQLite files when running in Docker (git-ignored, except .gitkeep)
docker-compose.yml       the app: http://localhost:8080
docker-compose.dev.yml   development override with hot reload
.env.example  all configuration variables, documented
```

## Development setup

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.14.8 automatically), Node.js 24 LTS
(via [nvm](https://github.com/nvm-sh/nvm), `frontend/.nvmrc`) and Docker Desktop with WSL integration.
Full setup instructions: [docs/development.md](docs/development.md).

```bash
cp .env.example .env          # then fill in the keys

# backend
cd backend
uv sync
uv run pytest

# frontend
cd frontend
nvm use
npm install
npm run build
```

Or run both with hot reload in Docker: see
[docs/development.md](docs/development.md#development-in-docker).
