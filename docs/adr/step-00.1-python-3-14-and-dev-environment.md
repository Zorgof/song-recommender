# ADR-00.1: Step 0 — Python 3.14.8 and development environment setup

- Status: Accepted
- Date: 2026-10-07
- Step: 0 (additional ADR #1)
- Amends: [ADR-00](step-00-scaffolding.md) (Python version, follow-ups 1 and 2)

## Context

After step 0 the developer decided to move the backend from Python 3.13 to
**Python 3.14.8**, the latest stable CPython release. ADR-00 also left two follow-ups
open: Node.js was not installed in the WSL distro, and Docker was not reachable from WSL.
Both had to be resolved before frontend work and before step 9. The developer also asked
for documentation of `.editorconfig`.

## Decision / What was implemented

### Python 3.14.8

- **uv upgraded from 0.10.9 to 0.12.23** (`uv self update`). 0.10.9 only knew CPython up to 3.14.3; 0.12.23 offers 3.14.8.
- We checked that 3.14.8 is the newest stable release: uv lists 3.15 only as `3.15.0rc3`.
- `backend/.python-version` is now `3.14.8`.
- In `backend/pyproject.toml`:
  - `requires-python = ">=3.14.8,<3.15"`
  - `[tool.ruff] target-version = "py314"`
  - `[tool.mypy] python_version = "3.14"`
- `.venv` was recreated and `uv.lock` regenerated for the new `requires-python`. The dev tool versions did not change.
- The docs were updated: `README.md`, `backend/README.md`, and `docs/implementation-plan.md` (stack table; the step 9 Docker base image is now `python:3.14.8-slim`).
- `python:3.14.8-slim` exists on Docker Hub. It was pulled and run successfully, so step 9 can pin it exactly.

### Node.js 24 LTS via nvm

- **nvm v0.40.8** (latest release) is installed into `~/.nvm`. Its installer added the nvm loader to `~/.zshrc`; a backup of the original file was taken before.
- `nvm install` in `frontend/` installed **Node v24.21.0 / npm 11.19.0** from `.nvmrc`, with checksum verification. `nvm alias default 24` makes it the default for new shells.
- A fresh `zsh -i` resolves `node` to `~/.nvm/versions/node/v24.21.0/bin/node`.

### Docker

- The installed Docker Desktop already had **WSL integration enabled for the default distro** (`EnableIntegrationWithDefaultWslDistro: true` in `settings-store.json`; Ubuntu is the default WSL distro). Docker was unavailable in ADR-00 only because **Docker Desktop was not running**: its `AutoStart` setting is `false`.
- Docker Desktop was started from WSL with `powershell.exe Start-Process`. After a few seconds the `docker` CLI shim appeared in WSL (`/usr/bin/docker`).
- Versions: Docker Engine 29.8.0 (client and server), Docker Compose v5.5.1.

### Documentation

- New `docs/development.md`: toolchain table with pinned versions, setup on WSL 2, everyday commands, a full explanation of `.editorconfig` (what EditorConfig is, how the file is resolved, every setting with its reason), and an overview of the code-quality tools.
- `README.md` links to it and mentions nvm and Docker Desktop as prerequisites.

## Deviations from the plan

- The plan said Python 3.13; it now says 3.14.8.
- `requires-python` pins the lower bound to the patch level (`>=3.14.8`). This is intentional: the whole toolchain (local uv Python and the Docker base image) uses exactly 3.14.8, so there is no need to support older 3.14 patches.

## Issues encountered and how they were solved

1. **uv did not know Python 3.14.8.** The bundled list of downloadable Python builds in uv 0.10.9 ended at 3.14.3. Upgrading uv solved it.
2. **The old lockfile was resolved for 3.13.** `uv lock` warned that the lockfile's fork markers (`python_full_version == '3.13.*'`) did not match the new `requires-python`, and re-resolved it. No package versions changed.
3. **`node` was not found right after `nvm install`.** In the verification command, `nvm install` ran inside a pipeline (`| tail`), which is a subshell, so its `PATH` change was lost. This is not a problem in real use: verified in a fresh interactive shell.
4. **Docker Desktop does not start with Windows** (`AutoStart: false`). This was left unchanged because it is a personal preference. **Follow-up for the developer:** either start Docker Desktop manually before working on the project, or enable *Settings → General → Start Docker Desktop when you sign in*.

## Consequences

- All later backend dependencies must support Python 3.14 (LangChain, LangGraph, SQLAlchemy, FastAPI …). This is checked in step 1 and later when they are added.
- The temporary Node binary used in ADR-00 is no longer needed; nvm is the source of Node from now on.
- Step 9 can rely on a working Docker Engine in WSL.

## Verification

| Command | Result |
|---------|--------|
| `uv --version` | `uv 0.12.23` |
| `cd backend && uv run python --version` | `Python 3.14.8` |
| `uv run pytest -q` / `ruff check .` / `ruff format --check .` / `mypy` | 1 passed / all checks passed / formatted / no issues |
| `zsh -ic 'node --version; npm --version'` | `v24.21.0`, `11.19.0` |
| `cd frontend && npm ci && npm run lint && npm run build && npm run format:check` | All pass with the nvm-installed Node |
| `docker version` | client 29.8.0 / server 29.8.0 |
| `docker compose version` | v5.5.1 |
| `docker run --rm hello-world` | "Hello from Docker!" |
| `docker run --rm python:3.14.8-slim python --version` | `Python 3.14.8` |
