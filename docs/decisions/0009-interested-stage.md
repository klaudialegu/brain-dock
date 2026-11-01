# 0009. Saved jobs: the "interested" stage
**Status:** Accepted
**Date:** 2026-10-26

## Context
I want to save jobs I'm considering before I apply, and the triage agent (ADR 0008) needs somewhere to put a job I approve. Today every row is an application: `applied_on` is required, and the stats, the pipeline chart and the list all assume it. A saved job must not change any of those numbers, and existing databases must behave exactly as before.

## Decision
- A saved job is an `Application` row with **`applied_on` empty** and a new first stage, **`interested`**. Its saved date is the date of its "interested" stage event, so there is no new column. `mark_applied()` turns it into an application (applied date on or after the saved date).
- **It isn't an application yet:** the list, the company page, the stats row (response and interview rates, totals, days since last application) and the edit and stage forms leave it out. The forms answer 404 until saved jobs get their own UI.
- **The pipeline chart has no "Interested" node.** The chart shows how applications flow, and every path starts at Applied. A job saved first joins at Applied, and one only saved adds nothing. An "Interested" node would mix two groups on the left edge (saved first, applied directly).
- **Backups** gain an optional `interested_on`, mirroring `applied_on`: a saved job has `interested_on` and no `applied_on` (and no events), and an application saved first has both.
- **Migration 0002** makes `applied_on` nullable and adds the stage. SQLite's batch mode copies, drops and renames tables that other tables point at, so `migrate()` now follows SQLite's documented procedure: foreign keys off before the transaction, `foreign_key_check` before commit (any broken reference rolls everything back), then back on. Downgrading refuses while saved jobs exist.

## Options considered
- **A separate "saved jobs" table:** keeps applications pure, but approving or applying would move rows between tables. A company holding only saved jobs would also hit the ADR 0006 delete rule, which is a decision deliberately postponed.
- **A separate "saved on" column:** duplicates the date the stage event already holds.
- **Keeping foreign keys on and deferring them during migrations:** SQLite counts every broken reference while a table is dropped and doesn't clear them when the copy is renamed back, so every batch migration on a referenced table fails at commit.

## Consequences
- Good: databases without saved jobs look exactly the same. This was rehearsed on copies of the real and demo databases: row checksums before and after, and every page compared with the previous release.
- Good: every future batch migration on a referenced table works, and still refuses to leave broken references.
- Trade-off: every query that means "applications" must leave out rows with no `applied_on`. Tests check the list, the company page, the stats, the chart and the forms.
- Trade-off: saved jobs have no UI yet (a follow-up slice adds the list section, saving, and "mark as applied").
- Update (PR 0b, 2026-10-31): that UI exists now: a "Saved jobs" section on the list, a save-a-job form, "mark applied", and a read-only list on the company page. Saved jobs still have no edit or stage forms (404).
