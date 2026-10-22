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

## Using the app

- **Applications** lists everything, newest first. **Add application** opens a form; it saves straight to the database, so run the export first if you want a backup.
- **Edit** on any row opens that application: change its fields (moving it to another company reuses that company; a company left with no applications is removed, see [ADR 0006](docs/decisions/0006-companies-without-applications.md)), see its stage history, and record a new stage.
- Above the list: a **Pipeline** chart (how applications moved from stage to stage; repeated or backwards steps are left out so the chart has no loops) and three stats:
  - **Response rate**: applications that got any reply (screen, interview, onsite, offer or rejected) out of those at least 14 days old. Ghosted and withdrawn don't count as replies; newer applications are left out because they haven't had a fair chance yet.
  - **Interview rate**: applications that reached interview, onsite or offer, out of those at least 14 days old (same window as the response rate).
  - **Since last application**: days since the most recent applied date.

  The chart library (Apache ECharts) is bundled in `src/brain_dock/static/vendor/` with its license and a recorded checksum, so pages never load anything from another site.
- Open the app at `http://127.0.0.1:8000` or `http://localhost:8000`. Other host names are refused on purpose, and forms only accept posts from the app's own pages (see [ADR 0005](docs/decisions/0005-form-security-on-a-localhost-app.md)).

## Development

- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

Design decisions are recorded in [docs/decisions/](docs/decisions/).
