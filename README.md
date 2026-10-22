# Brain Dock

A personal, local-first job-search hub: applications, interview prep, inbox triage and learning in one place. Built with Claude Code as a pair programmer, in small reviewed slices.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (on macOS: `brew install uv`).
2. Install dependencies: `uv sync`. This creates a local `.venv/` with Python 3.12 and everything in `uv.lock`.
3. Optional: `cp config.example.toml config.toml` and edit it to choose your own world clocks. `config.toml` is gitignored; without it, the app uses the defaults in the example.
4. Create the local database: `uv run python -m brain_dock.db`. It lives in `data/brain_dock.db`, which is gitignored, and it is the source of truth. Run the same command after pulling changes that include new migrations; the app won't start on an out-of-date database.
   - Try it with fake data: `uv run python -m brain_dock.importer --demo` loads `demo/applications.json` into `data/demo.db`.
   - Use your own: `cp demo/applications.json data/my_applications.json`, edit it, then `uv run python -m brain_dock.importer` for first-time setup. Once the database has applications, the import refuses to replace them unless you pass `--force`, which writes a backup first. Everything in `data/` is gitignored.
5. Back up your data any time: `uv run python -m brain_dock.export` writes `data/backups/applications-<date>-<time>.json`. To restore one, copy it to `data/my_applications.json` and run the importer with `--force`.
6. Run the app: `uv run uvicorn brain_dock.main:app --host 127.0.0.1 --reload`. It only listens on this machine, so nothing on your network can reach your data.
7. Open http://127.0.0.1:8000

## Development

- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

Design decisions are recorded in [docs/decisions/](docs/decisions/).
