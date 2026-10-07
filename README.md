# song-recommender

Simple, agent-based song recommendation for your daily use.

Describe your mood and how your day looks — by text or by voice — and a multi-agent LLM
system recommends **one song** that fits, with a Spotify player embedded in the page, a
YouTube link and a short explanation. Every decision is traced in LangSmith so the selection
logic can be inspected and tuned.

> **Status:** early development — step 2 (LLM layer and routing) of the
> [implementation plan](docs/implementation-plan.md). Nothing is runnable end to end yet.

## Documentation

- [Requirements](docs/requirements.md)
- [Technical implementation plan](docs/implementation-plan.md)
- [Development environment](docs/development.md) — toolchain setup, `.editorconfig`, code-quality tools
- [Architecture Decision Records](docs/adr/README.md)

## Tech stack

| Area | Technology |
|------|-----------|
| Backend | Python 3.14.8, FastAPI, LangGraph, LangChain (OpenAI / Anthropic / Gemini) |
| Observability | LangSmith |
| Frontend | React 19, TypeScript, Vite |
| Storage | SQLite |
| Runtime | Docker Compose |

## Repository layout

```
backend/    FastAPI app and agents (Python, uv)
frontend/   React SPA (TypeScript, Vite)
docs/       requirements, implementation plan, ADRs
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

Docker Compose setup arrives in step 9.
