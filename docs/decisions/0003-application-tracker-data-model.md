# 0003. Application tracker data model
**Status:** Accepted
**Date:** 2026-10-19

## Context
Phase 1 tracks job applications, and later views (list page, Sankey pipeline chart, stats, a morning brief) all read from the same data. Each application moves through stages over time, and the full path matters, not just where it ended. The data is local, single-user, and stored in SQLite.

## Decision
Three tables:
- **Company**: `name` (unique).
- **Application**: belongs to a company. Fields: `role_title`, `role_track` (support / fde / other), `applied_on`, `current_stage`, and optional `link`, `notes` and `follow_up_on`.
- **StageEvent**: belongs to an application. Fields: `stage` (applied, screen, interview, onsite, offer, rejected, ghosted, withdrawn), `happened_on`, optional `note`.

`current_stage` is stored for quick reading but written only by `record_stage()`, which sets it to the latest event (latest date; on the same day, the most recently recorded). New applications are created through `create_application()`, which also records the "applied" event. Foreign keys are enforced with `PRAGMA foreign_keys=ON` on every connection. Tables are created with `SQLModel.metadata.create_all`, with no migrations yet.

## Options considered
- Derive the current stage from events on every read: always correct, but every list query needs a "latest event" subquery. Storing it, with one helper as the only writer, gives the same correctness with simpler reads.
- One flat table (stage columns on the application): simpler, but it loses the path between stages that the pipeline chart needs, and can't record dates or notes per step.
- Alembic migrations from day one: more setup than the data needs while the model is still settling.

## Consequences
- Good: the full stage history is kept for the pipeline chart and stats, and the current stage is a plain column for lists and filters.
- Good: `follow_up_on` is a single date, so moving or snoozing a follow-up later is just changing that date.
- Good: foreign keys stop orphan rows (an application for a company that doesn't exist).
- Trade-off: `current_stage` can drift if code changes it directly instead of using `record_stage()`.
- Trade-off: without migrations, changing a table means rebuilding the database.
- Until migrations exist, data/my_applications.json is the source of truth; the database can be deleted and rebuilt from it at any time.
