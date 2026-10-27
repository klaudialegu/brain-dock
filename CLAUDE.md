# Brain Dock: project rules for Claude

## What this is
Brain Dock is a personal, local-first job-search hub: applications, interview prep, inbox triage and learning in one place.
It is built with Claude Code as a pair programmer, in small reviewed slices.

## How we work
- One slice at a time. A slice is the smallest change that can be verified: seen working in the browser when it has UI, or proven by tests when it doesn't. If a task looks bigger than ~1 hour, propose splitting it.
- Plan before code for anything touching more than 2 files: show a short numbered plan and wait for approval.
- Explain the why before the how.
- Verify your own work: run tests, and for UI changes open the page in the browser and check it before saying done.
- Only say something is saved, parked, or done after the file is actually written. Never report a step in the past tense before doing it.
- Before reporting a check's result, confirm it actually ran what it claims (test count above 0, correct target, a spy that saw calls), and every new test must be able to fail: no always-true assertions.
- Before telling Klaudia how to change her data, check the instruction against the current ADRs (since ADR 0004 the database is the source of truth).
- Any plan that removes or renames tests includes the before/after `pytest --collect-only` test-ID diff, so the approved count is the real one.
- If a new test is worth adding mid-slice, add it and report the plan change; don't fold it into a planned test just to keep the test-ID diff matching.
- Before running a bulk rewrite across files (a regex or a script), dry-run it and read the diff before running fixers like `ruff --fix`.
- Before merging a PR another open PR is based on, retarget the dependent PR to main first (deleting a merged PR's branch closes any PR based on it).

## Privacy rules (non-negotiable; privacy beats convenience every time)
- Personal data never goes into git: no resumes, emails, mood entries, recruiter names/contacts, salary numbers, or the database file. .gitignore covers *.db, .env, data/, and personal docs.
- Secrets (API keys, OAuth tokens) only in .env or the macOS keychain. Never hardcode, print, or log them.
- Personal values (home city, names, preferences) go in a gitignored local config with a committed `.example` file; never hard-code them in code or tests.
- Least access: Gmail uses the read-only scope and a narrow search query (job alerts and recruiters only), never the whole inbox.
- Data minimization: before sending anything to the Claude API, strip what isn't needed (signatures, phone numbers, other people's addresses). Send only the text needed for the task.
- Local first: data stays on the user's machine. Anything cloud or deployed uses fake seed data only.
- Wellbeing data is the most sensitive data in this app: local only, never sent to any API, deletable with one click.
- Logs never contain email bodies, tokens, or personal details.
- If a feature needs a new kind of personal data or a new outside service, stop and ask first, and explain what data goes where.

## Engineering rules
- One git branch per slice. Small commits with conventional messages (feat:, fix:, docs:, test:, chore:).
- Never commit secrets. Credentials go in .env (gitignored). Keep .env.example current.
- Every piece of logic gets a pytest test. Run the tests before saying something is done.
- Record real decisions (stack, libraries, data model changes) as a short ADR in docs/decisions/NNNN-title.md.
- Prefer boring, well-documented tools. Ask before adding a dependency.
- Update README.md when setup steps change.

## Stack (see docs/decisions/0001-stack.md)
- Python 3.12, FastAPI, SQLite via SQLModel
- Server-rendered HTML with Jinja2 (plain form posts; HTMX only if a page needs partial updates, see ADR 0001); Apache ECharts, vendored, for charts
- pytest + ruff; GitHub Actions for CI
- Claude API (tool use) for the inbox agent

## Commands
- Install / sync dependencies: `uv sync`
- Create or upgrade the local database (data/brain_dock.db, gitignored; it is the source of truth, ADR 0004): `uv run python -m brain_dock.db`. Run it after pulling model changes; the app refuses to start until the database is migrated.
- After changing a model, create a migration and review it before committing: `uv run alembic revision --autogenerate -m "describe the change"`. tests/test_migrations.py fails if a model change has no migration.
- Back up everything to data/backups/ (gitignored, owner-only, same format the importer reads): `uv run python -m brain_dock.export`. Do this before risky changes.
- Check the agent audit log's hash chain (ADR 0008): `uv run python -m brain_dock.verify_audit`. It prints counts and positions only.
- First-time setup from data/my_applications.json: `uv run python -m brain_dock.importer`. It refuses to replace a database that already has applications; `--force` replaces it after writing a full, validated backup (if the backup fails, nothing is deleted).
- Load fake demo data into data/demo.db (never the real database): `uv run python -m brain_dock.importer --demo`
- Run the app (auto-reloads on save): `uv run uvicorn brain_dock.main:app --host 127.0.0.1 --reload`, then open http://127.0.0.1:8000 (bound to this machine only; never use --host 0.0.0.0)
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

## Map
- src/brain_dock/core/: the dock (ADR 0007): app factory, storage and migrations, security, web helpers, the Manifest type, and agents/ (the agent harness, ADR 0008). Never imports a module.
- src/brain_dock/modules/<name>/: one module each (job_search is #1): manifest.py, routes, models, its own migrations/, templates/ (loaded as "<name>/..."), static/.
- src/brain_dock/registry.py: installed and enabled modules (BRAIN_DOCK_MODULES); the only place that imports modules. main.py composes the app.
- tests/: pytest tests
- .claude/skills/: repeatable session routines (/resume, /learn, /wrap-up, /explain-diff, /adr)
- docs/decisions/: ADRs
- docs/design/: design details behind an ADR (e.g. agent-harness.md for ADR 0008)
- Personal working notes are local-only and gitignored (see CLAUDE.local.md if present).
