# Song Recommender — backend

FastAPI service hosting the LangGraph agents. See the [root README](../README.md) and
[docs/implementation-plan.md](../docs/implementation-plan.md).

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.14.8 (pinned in `.python-version`) is installed automatically by uv.

```bash
uv sync                    # create .venv and install dependencies
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/api/docs
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type check (strict, with the pydantic plugin)
```

Configuration is read from environment variables and from the repository-level `../.env`
(see [`.env.example`](../.env.example)). Environment variables take precedence over `.env`.

## Layout

```
app/
  main.py            application factory (create_app), lifespan, request logging middleware
  config.py          Settings (pydantic-settings)
  errors.py          AppError hierarchy and handlers producing {"error": {"code", "message"}}
  logging_config.py  JSON (production) / console (development) logging with secret redaction
  api/               routers, dependencies and response schemas
  db/                SQLAlchemy models, async engine, Alembic migrations
tests/
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | `{"status": "ok", "database": "ok"}`, or HTTP 503 when the database is unreachable |
| `GET /api/meta` | Public configuration for the frontend (models per tier, STT/LangSmith/catalog flags, locales); never contains secrets |
| `GET /api/docs` | Swagger UI; the OpenAPI schema is at `/api/openapi.json` |

Every response carries an `X-Request-ID` header, generated or propagated from the request.

## Database and migrations

SQLite files live in `DATA_DIR` (default `./data`, relative to the working directory).
Migrations run automatically on application startup (`alembic upgrade head`).

Creating a new migration after changing `app/db/models.py`:

```bash
uv run alembic revision --autogenerate --rev-id 0002 -m "short description"
# review the generated file in app/db/migrations/versions/, then:
uv run alembic upgrade head
uv run alembic check        # must report "No new upgrade operations detected."
```

Things to check in every generated revision:

- **Enum columns:** autogenerate renders each enum CHECK constraint twice (named after the enum
  and named by the convention). Keep only the `op.f("ck_<table>_<enum name>")` one and set
  `create_constraint=False` on the `sa.Enum(...)` in the migration (see `0001_initial_schema.py`).
- **Application types** such as `UTCDateTime` are rendered as plain SQLAlchemy types by
  `render_item` in `env.py`; revision scripts must never import `app` code.
- SQLite cannot `ALTER` most things; migrations use batch mode (`render_as_batch=True`).
