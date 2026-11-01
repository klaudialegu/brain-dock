# Using Brain Dock

## Your own data

1. Create your database: `uv run python -m brain_dock.db` (in `data/brain_dock.db`, gitignored). Run it again after pulling changes with new migrations; the app won't start on an out-of-date database.
2. Run the app: `uv run uvicorn brain_dock.main:app --host 127.0.0.1 --reload`, then open http://127.0.0.1:8000.
3. Add applications with **Add application**. The database is the source of truth ([ADR 0004](decisions/0004-database-as-source-of-truth.md)), so the form is how real data comes in.

The app only listens on this machine. Open it at `http://127.0.0.1:8000` or `http://localhost:8000`; other host names are refused on purpose, and forms only accept posts from the app's own pages ([ADR 0005](decisions/0005-form-security-on-a-localhost-app.md)).

## Inbox rules

The inbox's rules read your own thresholds from a local `config.toml` (gitignored): copy `config.example.toml` to `config.toml` and edit its `[inbox]` section. Without it, an inbox run refuses to start (the app itself still runs). To fill the demo's inbox with synthetic job alerts: `uv run python -m brain_dock.modules.inbox.demo` (demo database only).

## Backups and import

- **Back up**: `uv run python -m brain_dock.export` writes a complete, validated JSON backup to `data/backups/applications-<date>-<time>.json` (owner-only).
- **Check the audit log**: `uv run python -m brain_dock.verify_audit` checks that the agent audit log's hash chain is intact. Its key sits next to the database (`<database>.audit-key`, owner-only); without it, the log can't be verified.
- **Stop agents**: `touch data/agents-off` stops every agent at its next step, even mid-run; `touch data/agents-off-<module>` stops one module's. Delete the file to turn them back on. If the check itself fails, agents count as off.
- **Import**: `uv run python -m brain_dock.importer` is for first-time setup from a JSON file in the backup format. It refuses to replace a database that already has applications unless you pass `--force`, which writes a backup first.
- **Demo data**: `uv run python -m brain_dock.importer --demo` loads `demo/applications.json` into `data/demo.db`. Start the app with `BRAIN_DOCK_DB=data/demo.db` to use it; a banner marks it as fake.

## Stats

- **Response rate**: applications that got any reply (screen, interview, onsite, offer or rejected) out of those at least 14 days old. Ghosted and withdrawn don't count as replies; newer applications haven't had a fair chance yet.
- **Interview rate**: applications that reached interview, onsite or offer, out of those at least 14 days old.
- **Since last application**: days since the most recent applied date.

The pipeline chart leaves out repeated or backwards steps, so it has no loops.

## Companies

Moving an application to another company reuses that company (names are matched ignoring case and spaces). A company left with no applications is removed ([ADR 0006](decisions/0006-companies-without-applications.md)).

## Modules

Brain Dock is a core plus modules ([ADR 0007](decisions/0007-core-and-modules.md)). Job search is the first module.

- `BRAIN_DOCK_MODULES` picks the enabled modules, comma-separated (for example `BRAIN_DOCK_MODULES=job_search`). Unset means all installed modules; empty means none. An unknown name stops the app with an error listing the installed modules.
- Turning a module off hides its pages, nav and files. Its data and migrations are never touched; turn it back on and everything is there.

### Adding a module

1. Create `src/brain_dock/modules/<name>/` with a `manifest.py` (see `job_search/manifest.py`), its routes, templates and models. Prefix its tables with `<name>_`.
2. Give it its own migrations folder, starting a branch labelled `<name>`, and add that folder to `version_locations` in `alembic.ini`.
3. Add it to `INSTALLED` in `src/brain_dock/registry.py`, and a seeder for fake data in `tests/test_modules_off.py`.
4. If its agents use tools, declare them in `agent_tools` (see `core/agents/tools.py`): snake_case names, an effect each, no `outbound` or `delete` tools without an Accepted ADR exception.
5. Run the tests: the module contract (`tests/test_module_contract.py`) and the modules-off checks cover it automatically. It may only import the core, never another module.

