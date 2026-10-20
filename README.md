# Brain Dock

A personal, local-first job-search hub: applications, interview prep, inbox triage and learning in one place. Built with Claude Code as a pair programmer, in small reviewed slices.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (on macOS: `brew install uv`).
2. Install dependencies: `uv sync`. This creates a local `.venv/` with Python 3.12 and everything in `uv.lock`.
3. Optional: `cp config.example.toml config.toml` and edit it to choose your own world clocks. `config.toml` is gitignored; without it, the app uses the defaults in the example.
4. Run the app: `uv run uvicorn brain_dock.main:app --reload`
5. Open http://localhost:8000

## Development

- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

Design decisions are recorded in [docs/decisions/](docs/decisions/).
