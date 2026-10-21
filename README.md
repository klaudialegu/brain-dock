# Brain Dock

A personal, local-first job-search hub: applications, interview prep, inbox triage and learning in one place. Built with Claude Code as a pair programmer, in small reviewed slices.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (on macOS: `brew install uv`).
2. Install dependencies: `uv sync`. This creates a local `.venv/` with Python 3.12 and everything in `uv.lock`.
3. Optional: `cp config.example.toml config.toml` and edit it to choose your own world clocks. `config.toml` is gitignored; without it, the app uses the defaults in the example.
4. Create the local database: `uv run python -m brain_dock.db`. It lives in `data/brain_dock.db`, which is gitignored.
   - Try it with fake data: `uv run python -m brain_dock.importer --demo` loads `demo/applications.json` into `data/demo.db`.
   - Use your own: `cp demo/applications.json data/my_applications.json`, edit it, then `uv run python -m brain_dock.importer`. The JSON file is the source of truth: each run rebuilds the database from it. Everything in `data/` is gitignored.
5. Run the app: `uv run uvicorn brain_dock.main:app --reload`
6. Open http://localhost:8000

## Development

- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

Design decisions are recorded in [docs/decisions/](docs/decisions/).
