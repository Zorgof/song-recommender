# Development environment

This guide describes the toolchain, how to set it up, and the shared editor and code-quality
configuration of the repository.

## Toolchain

| Tool | Version | Where it is pinned | Purpose |
|------|---------|--------------------|---------|
| Python | **3.14.8** | `backend/.python-version`, `requires-python` in `backend/pyproject.toml` | Backend runtime |
| uv | ≥ 0.12 | — | Python version manager, dependency resolver, virtual environments, lockfile (`backend/uv.lock`) |
| Node.js | **24 LTS** | `frontend/.nvmrc`, `engines.node` in `frontend/package.json` | Frontend build and dev server |
| npm | bundled with Node | `frontend/package-lock.json` | Frontend dependencies |
| nvm | ≥ 0.40 | — | Node.js version manager; reads `.nvmrc` |
| Docker Desktop | with Compose v2 | — | Runs the whole app locally (from step 9) |

### Setup on WSL 2 (Ubuntu)

```bash
# uv (Python is downloaded automatically by uv on first `uv sync`)
curl -LsSf https://astral.sh/uv/install.sh | sh

# nvm + Node.js 24 LTS
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh | bash
# open a new terminal, then:
cd frontend && nvm install     # installs the version from .nvmrc
nvm alias default 24

# Docker: install Docker Desktop on Windows, then enable
# Settings → Resources → WSL integration for this distro, and start Docker Desktop.
docker info                    # must print engine details, not a connection error
```

### Everyday commands

```bash
# backend
cd backend
uv sync                 # create .venv and install locked dependencies
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # strict type check

# frontend
cd frontend
npm install
npm run dev             # http://localhost:5173, proxies /api to http://localhost:8000
npm run build           # type check + production build
npm run lint            # oxlint
npm run format          # prettier --write
```

## EditorConfig (`.editorconfig`)

[EditorConfig](https://editorconfig.org) is a small, editor-independent file format that tells
editors and IDEs how to handle basic formatting: indentation, line endings, encoding and
whitespace. VS Code (with the *EditorConfig for VS Code* extension), JetBrains IDEs, Vim, Neovim
and most other editors read it automatically. Everyone working on the repository then gets the
same basic settings, whatever their personal editor configuration is.

It complements the language formatters instead of replacing them: ruff format (Python) and
Prettier (TypeScript, CSS, JSON, Markdown) rewrite code on demand. EditorConfig makes sure that
what you type is already close to that style. Prettier also reads `.editorconfig` for
`indent_style`, `indent_size` and `end_of_line` when its own config does not set them.

### How the file is read

- The editor looks for `.editorconfig` in the directory of the opened file and in every parent
  directory, until it finds a file with `root = true`.
- Sections (`[...]`) are glob patterns matched against file paths. When several sections
  match a file, the later ones override the earlier ones.

### The settings used in this repository

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.py]
indent_size = 4

[*.md]
trim_trailing_whitespace = false
```

| Setting | Value | Meaning and reason |
|---------|-------|--------------------|
| `root` | `true` | This is the top-most `.editorconfig`. The editor stops searching parent directories, so no `.editorconfig` outside the repository (e.g. in your home directory) can affect it. |
| `[*]` | section | Applies to every file. |
| `charset` | `utf-8` | Files are saved as UTF-8 without BOM. Polish UI translations (ą, ę, ł, ż…) and emoji (👍/👎) must survive any editor. |
| `end_of_line` | `lf` | Unix line endings (`\n`). Important on Windows / WSL: CRLF in shell scripts or Dockerfiles breaks them inside Linux containers, and mixed endings produce noisy git diffs. |
| `insert_final_newline` | `true` | Every file ends with a newline. POSIX tools expect it, and git does not show "No newline at end of file" warnings. |
| `trim_trailing_whitespace` | `true` | Spaces at the end of lines are removed on save, so there are no invisible whitespace-only changes in diffs. |
| `indent_style` | `space` | Indentation uses spaces, never tabs. |
| `indent_size` | `2` | Two spaces per indentation level: the convention for TypeScript, JSON, YAML, CSS and HTML, and what Prettier produces. |
| `[*.py]` → `indent_size` | `4` | Python files use four spaces (PEP 8, and what ruff format produces). |
| `[*.md]` → `trim_trailing_whitespace` | `false` | In Markdown, two trailing spaces mean a hard line break, so they must not be removed. |

Other EditorConfig properties exist (`tab_width`, `max_line_length` and some editor-specific
ones) but are not used here: line length is enforced by the formatters (ruff: 100, Prettier: 100).

## Code quality tools

| Tool | Scope | Configuration |
|------|-------|---------------|
| ruff (lint + format) | Python | `[tool.ruff]` in `backend/pyproject.toml`: line length 100, rule sets E, W, F, I, B, UP, SIM, ASYNC, RUF |
| mypy (strict) | Python | `[tool.mypy]` in `backend/pyproject.toml` |
| pytest + pytest-asyncio | Python tests | `[tool.pytest.ini_options]` in `backend/pyproject.toml` |
| oxlint | TypeScript / React | `frontend/.oxlintrc.json` |
| Prettier | TypeScript, CSS, JSON, Markdown, HTML in `frontend/` | `frontend/.prettierrc.json`, `frontend/.prettierignore` |
| TypeScript compiler | type checking | `frontend/tsconfig*.json` |
