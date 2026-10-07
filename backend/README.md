# Song Recommender — backend

FastAPI service hosting the LangGraph agents. See the [root README](../README.md) and
[docs/implementation-plan.md](../docs/implementation-plan.md).

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.14.8 (pinned in `.python-version`) is installed automatically by uv.

```bash
uv sync                    # create .venv and install dependencies
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type check
```
