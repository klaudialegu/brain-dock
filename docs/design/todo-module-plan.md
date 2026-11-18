# Plan: the to-do module

**Status:** approved by the owner on 2026-11-17 with D1 and D2 both A (after one review round, 🟡, fixes applied). Built on branch `feat/todo-module`; ADR 0015 records it.

**What:** module #3, code name `todo`, display name "To do" (ADR 0012).
- **Tasks:** each task has a title, a due date, done, an estimate, a bucket (Today or Can wait), "ok to read aloud" (off by default), and optional ordered steps with their own minutes.
- **The page:** one page with a simple card (Today and Can wait), an add form, and an edit page with steps.
- **Spoken brief:** tasks for today are counted, and only tasks marked "ok to read aloud" are read by name.
- **Not in this slice:** full visual polish (the dot meter, Focus mode, the home layout) waits for the UI slice. This slice puts every field the UI slice needs into the first migration, so that slice needs no migration of its own.

## Open decision
- **D1: backups.** `uv run python -m brain_dock.export` backs up Career Radar only, but the README says every module gets "one command writes a complete, validated JSON backup".
  - A (recommended): this slice says so plainly in the README and THREAT_MODEL Known gaps. A separate "backups for every module" slice follows: one backup file per module, each restorable.
  - B: add to-dos to the export now. This changes the backup format the importer reads, so the importer needs a restore path too, which makes this slice bigger.
- **D2: deleting a task.** With D1 A, a deleted task has no backup to restore from.
  - A (recommended): no task delete in this slice. Done tasks drop off the card the next day, and a task can be moved to Can wait. Delete comes with the delete/remove slice, which already plans "a confirm step, and an export first". Removing a step stays.
  - B: keep delete with a confirm page, and say plainly in the README and Known gaps that it's permanent and not backed up.

## Data (one migration, the module's own Alembic branch)
- **`todo_task`:**
  - `id`
  - `title` (1–200 characters)
  - `due_on` (date, optional)
  - `done` (false)
  - `done_at` (when it was marked done, optional). Stored in UTC like the core's timestamps, and compared as a local date: a task finished at 9 pm counts as done that day.
  - `ok_to_read_aloud` (false)
  - `estimate_minutes` (1–1,440, optional)
  - `bucket` (`today` or `can_wait`, default `today`)
  - `created_at`
- **`todo_step`:**
  - `id`
  - `task_id` (its task; deleting a task deletes its steps)
  - `position` (1, 2, 3…, unique within a task)
  - `title` (1–200)
  - `minutes` (1–1,440, optional)
  - `done` (false)
- **Two fields beyond the list you gave**, so the UI slice needs no other migration:
  - `done_at` lets the card show only tasks done today (struck through) and hide older ones.
  - The step `done` field is for Focus mode's "Done, next step".
- Table names have the module prefix (ADR 0007).
- Nothing here touches other modules' tables. `importer --force` deletes only Career Radar's tables, so to-dos survive it.

## Steps
1. **The module package** `src/brain_dock/modules/todo/`: `manifest.py`, `models.py`, `routes.py`, `brief.py`, `demo.py`, `migrations/`, `templates/`, plus a small `static/todo.css`.
   - It is registered in `registry.py`, and its nav entry is "To do".
   - Turning it off with `BRAIN_DOCK_MODULES` hides it without touching its data, as for every module.
2. **The page `/todo`:**
   - The heading "To do".
   - **The card:**
     - "Today": open tasks, plus tasks done today, struck through. Each row has a done checkbox button, the title, the estimate and due date ("~45 min · due Fri"), and its steps as a numbered list with minutes.
     - "Can wait": the title, a loose "when" (no due date means "someday"; due by Sunday means "this week"; otherwise "by Nov 30"), and a "↑ Today" button.
   - **Below the card:** an "Add a task" form with title, bucket, due date, estimate and "ok to read aloud". That checkbox is never pre-checked, and a post without it saves "off".
   - **Estimates:** when a task has no estimate but its steps have minutes, the card shows their sum.
3. **Edit page `/todo/{id}/edit`:**
   - Every field.
   - **Steps:** add (title and minutes), move up and down, mark done, remove.
   - **Delete:** none in this slice (D2 A).
   - Plain form posts with CSRF, no scripts (ADR 0001, 0005). Errors show next to their fields and save nothing, like the existing forms.
4. **Spoken brief** (`todo/brief.py`, through `Manifest.brief`):
   - **Today's tasks:** not done, and either in Today or due today or earlier.
   - **The lines:**
     - a count, like "On today's list: 3 things." With nothing for today, no to-do line at all, so the brief keeps saying "Nothing needs your attention today." when that's true.
     - then, only for tasks marked "ok to read aloud": "First up: <title>, and <title>." At most 2 titles, each cleaned (letters, digits, basic punctuation) and trimmed to 40 characters at a word boundary.
   - **In the morning brief:** the to-do sentence comes after the workout and before job counts. That needs module lines kept per module (`brief.module_lines` returns them by module name).
   - **Cap order:** to-do titles are dropped first (the count stays), as ADR 0014 planned.
   - Titles go through the same masking (secret shapes, then `redact()`) as the rest of the script.
5. **Demo and checks:**
   - `uv run python -m brain_dock.modules.todo.demo` loads fake tasks into `data/demo.db`. It always writes there, whatever `BRAIN_DOCK_DB` says, never to the real database, exactly like the inbox demo. `load_demo(path)` is what the e2e server calls with its temp database.
   - The e2e server loads that demo, and the checklist items 9 (narrow window) and 10 (CSP and console) gain the `/todo` page and the edit page.
   - `test_modules_off.py` and `scripts/check_modules_off.sh` get a `todo` seed and probe.
6. **Docs:**
   - ADR 0015 (the to-do module).
     - It records a new kind of personal data (task titles, stored locally only).
     - It records the one exception to "the brief holds counts and dates only": titles you mark "ok to read aloud".
   - THREAT_MODEL rows: task data in the local database, never in git and never logged; titles reach ElevenLabs only when marked; the D1 Known gap.
   - Every public statement about what reaches ElevenLabs, updated to "titles of tasks you mark ok to read aloud":
     - README: the morning brief's ElevenLabs list and its "Nothing else is sent" line.
     - THREAT_MODEL: the ElevenLabs row (its contents list and tests) and the "ElevenLabs keeps the script" Known gap.
     - The `Manifest.brief` comment in `core/modules.py` ("counts and dates only, never names or free text") gets the one exception.
     - The `morning_brief.py` docstring.
   - README (Modules, and the backup sentence), CLAUDE.md Map, CHANGELOG.

**Wording (ADR 0012 and the wording plan):** the code name `todo` is stable. "To do", "Today" and "Can wait" are wording. Labels and docs are neutral and general-purpose, with nothing about why the module was built.

## Test IDs
`uv run pytest`: **638 → 665** (27 added, none removed or renamed). The exact `--collect-only` diff goes in the PR.

10 come automatically from the per-module tests (each runs once more, with `[todo]`):
- `test_module_contract.py`: `test_manifest_is_complete`, `test_imports_no_other_module`, `test_agent_tools_follow_the_policy`, `test_tables_match_the_manifest_and_are_prefixed`, `test_routes_stay_in_declared_paths`, `test_post_routes_check_csrf`, `test_migrations_match_the_models`, `test_migrations_are_a_branch_of_their_own`
- `test_modules_off.py`: `test_core_runs_with_module_disabled`, `test_disabling_keeps_the_data`

`tests/test_todo.py` (12):
- `test_task_defaults_are_today_not_done_and_not_read_aloud`
- `test_task_and_step_fields_are_checked`
- `test_steps_keep_their_order_when_added_moved_and_removed`
- `test_marking_done_records_when_and_undoing_clears_it`
- `test_deleting_a_task_deletes_its_steps`
- `test_todo_page_shows_today_and_can_wait`: done-today struck through (including one finished in the evening, local time), older done hidden, the "when" labels.
- `test_add_task_from_the_form`
- `test_form_errors_show_next_to_fields_and_save_nothing`
- `test_done_and_bucket_buttons_change_only_that_task`
- `test_edit_task_and_its_steps`
- `test_add_form_never_pre_checks_read_aloud`: the rendered box isn't checked, and a post without it saves off.
- `test_typed_titles_never_appear_in_logs`

`tests/test_todo_brief.py` (5):
- `test_brief_counts_todays_open_tasks`
- `test_only_tasks_marked_read_aloud_are_named`
- `test_spoken_titles_are_cleaned_trimmed_and_at_most_two`
- `test_morning_brief_reads_todos_before_job_counts_and_drops_titles_first`
- `test_todo_demo_writes_only_the_demo_database`: whatever `BRAIN_DOCK_DB` says. Cited in THREAT_MODEL's row for tests and demos.

**Changed, not renamed:**
- `test_brief.py::test_brief_never_names_companies_roles_notes_or_links` also plants unmarked to-do titles. This was the review's pre-mortem: every module's data, run through the whole brief.
- The morning brief's tests and fixtures move to per-module lines.

**Found during the build: 665 → 671.** Two existing tests run once per template:
- `test_security_headers.py::test_templates_have_no_inline_scripts_or_styles`
- `test_vendor.py::test_templates_load_nothing_from_other_sites`

The module's three templates (`index.html`, `edit.html`, `task_fields.html`) add 6 test IDs. The `--collect-only` count is 671 = 638 + 17 new + 10 per-module + 6 per-template.

**Added after the PR review: 671 → 672.** The review found that titles were cleaned before they were masked. Cleaning removed the "@", "=" and "_" the masking looks for, so "Reply to sam@example.org" or "wifi pwd=…" in a marked title would have reached ElevenLabs. Workout names had the same order.
- The masking moved from `voice.py` to `core/masking.py` (`scrub()`), so a module can use it.
- To-do titles and workout names are now masked first, then cleaned and trimmed.
- New test: `test_morning_brief.py::test_free_text_is_masked_before_it_is_cleaned_or_trimmed`. Break-tested for both sources.
- A single long word was trimmed to 41 characters; it's now 40, with a case added to `test_spoken_titles_are_cleaned_trimmed_and_at_most_two`.

**Also changed during the build (not renamed):**
- `test_db.py::test_create_db_makes_the_file_and_tables` lists the two new tables.
- `test_modules_off.py` gets a `todo` seeder and the `/todo/1/edit` probe.
- `scripts/check_modules_off.sh` loads the to-do demo and probes `/todo/1/edit`.
- With nothing for today, the to-do module adds no line, so the text brief still says "Nothing needs your attention today." when that's true.

`uv run pytest e2e`: **28 → 32** (`todo` and `todo-edit` added to items 9 and 10).

Break tests, each reverted and recorded in the PR:
- Read titles regardless of the flag, and `test_only_tasks_marked_read_aloud_are_named` fails.
- Drop the CSRF check on the add route, and `test_post_routes_check_csrf[todo]` fails.
- Let the done button change every task, and `test_done_and_bucket_buttons_change_only_that_task` fails.
- Pre-check the "ok to read aloud" box in the add form, and `test_add_form_never_pre_checks_read_aloud` fails.

## Privacy
- Task titles and steps are personal data. They live only in the local database, never in git, logs or errors (tests plant a unique title).
- A title reaches ElevenLabs only when its task is marked "ok to read aloud" and voice is on. It's masked first, and at most 2 titles are read.
- Demo and test tasks are made up.

## Not in this slice
- **UI slice:** the visual polish (dot meter, washi-tape label, Focus mode, the home layout), and moving a task between Today and Can wait by dragging.
- Meetings (the schedule slice).
- Backups for every module (D1 A).
- Deleting a task (D2 A): it comes with the delete/remove slice.
- Repeating tasks and reminders.
