# Brain Dock: project rules for Claude

## What this is
Brain Dock is a personal, local-first job-search hub: applications, interview prep, inbox triage and learning in one place.
It is built with Claude Code as a pair programmer, in small reviewed slices.

## How we work
- One slice at a time. A slice is the smallest change that can be SEEN working in the browser. If a task looks bigger than ~1 hour, propose splitting it.
- Plan before code for anything touching more than 2 files: show a short numbered plan and wait for approval.
- Explain the why before the how.
- Verify your own work: run tests, and for UI changes open the page in the browser and check it before saying done.
- Only say something is saved, parked, or done after the file is actually written. Never report a step in the past tense before doing it.

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
- Server-rendered HTML with Jinja2 + HTMX; Apache ECharts for charts (it has Sankey/funnel)
- pytest + ruff; GitHub Actions for CI
- Claude API (tool use) for the inbox agent

## Commands
- Install / sync dependencies: `uv sync`
- Create the local database (data/brain_dock.db, gitignored): `uv run python -m brain_dock.db`
- Run the app (auto-reloads on save): `uv run uvicorn brain_dock.main:app --reload`, then open http://localhost:8000
- Test: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`

## Map
- src/brain_dock/: the app (main.py routes, templates/ for Jinja2 HTML)
- tests/: pytest tests
- .claude/skills/: repeatable session routines (/resume, /learn, /wrap-up, /explain-diff, /adr)
- docs/decisions/: ADRs
- Personal working notes are local-only and gitignored (see CLAUDE.local.md if present).
