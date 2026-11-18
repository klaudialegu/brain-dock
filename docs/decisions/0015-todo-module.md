# 0015. To do, module #3, and the one free-text exception in the brief
**Status:** Accepted
**Date:** 2026-11-17
**Changes:** extends ADR 0013 point 1 and ADR 0014 point 2 (what the brief and the script may hold).

## Context
Brain Dock needs a place for small tasks: some for today, some that can wait, some broken into steps with their own minutes. The morning show (ADR 0014) should say how many tasks today holds, and read a few of them aloud. The visual design (a dot meter for estimates, Focus mode for one task at a time, the home layout) comes in a later UI slice, which should need no migration of its own.

Task titles are a new kind of personal data. Until now the brief held counts and dates only, never free text, because ElevenLabs keeps what it receives by default.

## Decision
1. **A module of its own**, code name `todo`, display name "To do" (ADR 0012).
   - **Tables:** `todo_task` and `todo_step` (ADR 0007), in one migration on the module's own branch.
   - **Task fields:** title, due date, done, `done_at`, `ok_to_read_aloud`, estimate in minutes, bucket (`today` or `can_wait`), and created time.
   - **Step fields:** position, title, minutes and done.
   - `done_at` and the step `done` flag are there for the UI slice: "done today" on the card, and Focus mode's "Done, next step".
2. **Today and Can wait.**
   - Today shows tasks in Today, plus any task due today or overdue wherever it sits, plus tasks done today.
   - "Done today" is the local date of `done_at`, which is stored in UTC.
   - Can wait shows the rest with a loose "when": someday, this week, or "by Nov 30".
3. **Titles are spoken only when marked.**
   - The brief counts today's open tasks.
   - Titles are read only for tasks with `ok_to_read_aloud` on. It is off by default, and the add form never pre-checks it.
   - At most 2 titles, each masked first (`core/masking.py`: secret shapes, then `redact()`), then cleaned (letters in any language, digits, basic punctuation) and trimmed to 40 characters. Masking comes first, because cleaning removes the "@" or "=" the masking looks for, and trimming can cut an address in half. Workout names get the same order.
   - With nothing for today, the module adds no line at all.
   - This is the one exception to "counts and dates only" (ADR 0013), and only for tasks the owner marks.
4. **The show's order:** greeting, weather, workout, to-dos, job counts, sign-off. If the script is over the cap, to-do titles are dropped first; the count stays. Module lines are kept per module so the show can place them.
5. **No delete in this slice.** To-dos aren't in any backup yet: `brain_dock.export` covers Career Radar only. A deleted task couldn't come back, so deleting tasks waits for the delete/remove slice, which plans an export first. Removing a step is allowed.
6. **Plain form posts, no scripts:** CSRF on every post (ADR 0005), errors next to their fields, never echoing what was typed.

## Options considered
- **Read every title for today:** why not: a title can be anything ("call the clinic about the results"). Marking a task is a deliberate yes.
- **Backups now:** why not: it changes the backup format the importer reads and needs a restore path. Backups for every module are their own slice. Until then there is no delete, so nothing is lost by a click.
- **Steps as one free-text list on the task:** why not: steps need their own minutes and done state, and an order that can change.

## Consequences
- Good: the UI slice gets every field it needs without a migration.
- Good: turning the module off (`BRAIN_DOCK_MODULES`) hides it and its line in the brief, and keeps its data.
- Trade-off: marked titles go to ElevenLabs, which keeps them by default. The README and THREAT_MODEL say so, and the checkbox label says the title is then sent to the voice service.
- Trade-off: to-dos aren't backed up by `brain_dock.export` until the backups slice.
