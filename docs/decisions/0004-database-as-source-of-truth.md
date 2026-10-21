# 0004. Database as source of truth, with migrations and JSON backups
**Status:** Accepted (supersedes the schema-creation and source-of-truth parts of 0003)
**Date:** 2026-10-21

## Context
ADR 0003 made `data/my_applications.json` the source of truth: every import wipes the database and rebuilds it from the file. The next slice adds an add/edit form, which writes to the database. Under 0003, the next import would silently erase those edits. Tables were also created with `create_all`, which can't change an existing table, so any model change would mean rebuilding the database.

## Decision
- The local SQLite database (`data/brain_dock.db`) is the source of truth.
- Schema changes go through Alembic migrations. `create_all` is no longer used for the real database.
- A JSON export writes a backup of all applications and stage events into gitignored `data/`. It uses the same format the importer reads, so a backup can be restored.
- The importer stays for the demo and first-time setup. It refuses to wipe a database that already has applications unless `--force` is passed.

## Options considered
- Keep the JSON as source of truth and make the form write to the file: no migrations needed, but every edit rewrites the whole file and the database becomes a cache that can disagree with it.
- Database as source of truth without migrations: simpler now, but the first model change would force a rebuild and lose form edits.
- Back up by copying the `.db` file: exact, but opaque and tied to the current schema; JSON is readable, diffable and can be re-imported after schema changes.

## Consequences
- Good: form edits are permanent; one place holds the truth.
- Good: model changes become reviewed migration files instead of rebuilds.
- Good: backups are plain JSON that the importer can restore.
- Trade-off: Alembic adds a dependency, migration files to review, and a step after pulling model changes (`upgrade`).
- Trade-off: SQLite can't alter most column definitions in place, so migrations use Alembic's batch mode (copy the table, then swap).
- Trade-off: data is now only as safe as the latest export. Exporting before risky operations (like `--force`) matters.
- ADR 0003's table design and `record_stage()` rule still apply; only how the schema is created and which copy is the truth change.
