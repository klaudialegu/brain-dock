# Remove and exit: plan
Remove controls with Undo, a shared message bar that closes with × or Esc, and clean exits.

## Decisions (approved)
- **D1 = A: remove hides, Undo brings it back.**
  - A removed task, step or scratchpad page gets a `removed_at` time. It stays in the local database, out of every list, card, count and brief.
  - The next page shows "Removed: *title* · Undo · ×". Undo is a plain form button: it works with the keyboard and without scripts.
  - The message stays until × or Esc closes it, or another page loads. No timer.
- **D2 = A: Career Radar removal waits for the delete/remove slice.** That covers applications, saved jobs and recorded stages. The same slice adds "Recently removed / restore" and permanent delete.

## Steps
1. **Message bar (core).** `core/flash.py` holds a one-time message in a short-lived cookie.
   - The cookie carries only a kind and an id, never text. A route sets it on its redirect; the next page reads it, shows it once, and clears it, so a reload never repeats it.
   - `templates/partials/message.html` is the bar (`role="status"`), with an optional Undo form and a × link that reloads the page without the message. `static/messages.js` makes Esc and × close it in place. While focus is in a text field, Esc only leaves the field; a second Esc closes the bar, so leaving a field never loses the Undo.
   - **The look:** a cream pill bar at the top of the page column, ink text, an Undo pill and a ×.
2. **To do.**
   - **Migration `todo_0002`:**
     - adds `removed_at` to `todo_task` and `todo_step`;
     - adds `removed_position` to `todo_step`;
     - makes `todo_step.position` nullable (a batch migration).
     - **Downgrade:** refuses while any task or step is removed, and gives the count, like job_search 0002. Otherwise it would fail part-way on an empty position, or quietly bring removed items back. `scratchpad_0002` refuses the same way while a page is removed.
   - **Task:** "Remove task" on the task's edit page. Undo puts the task back as it was. Every query skips removed tasks: `todays_open`, `card`, the list, "Done recently", the brief lines and the morning brief, including a read-aloud title.
     - One live-task loader serves every route that changes a task: edit, Done, Can wait/Today, and the step routes. A removed task is refused with "This task was removed", with Undo and the typed values kept. Never a bare 404.
     - Undo accepts only an item that is removed. Undo on a live task, step or page changes nothing.
   - **Step:** a removed step leaves the numbering. Its `position` becomes NULL, which the unique rule allows any number of times, and its old place goes to `removed_position`. The steps after it move up.
     - Undo shifts the steps at and after the old place down by one, highest first, so no two ever share a place. Then it puts the step back, clamped to the end if the list got shorter.
     - Every read of a task's steps goes through `live_steps(task)`, which skips removed ones: `add_step`'s numbering (models.py:109), `move_step` (:120), `remove_step`'s renumbering (:137), `total_minutes` (:187), `load_step` (routes.py:67, removed is refused), the edit page's list (routes.py:99) and the list page (index.html:39–41).
   - **"Done recently":** a collapsed list on /todo of tasks done in the last 7 days before today, each with "Not done".
3. **Scratchpad.**
   - Migration `scratchpad_0002` adds `removed_at` to `scratchpad_page`.
   - "Remove page" in the page header, with Undo.
   - Removed pages leave the tabs, the Home card, `latest`, `latest_on` and quick capture, so a note never lands on a removed page.
   - New page numbers come from `next_position(day)`, the highest position that day, removed or not. A removed page's number is never reused, so the day+position rule can't fail.
   - **A removed page still open in another tab:** its save and style posts are refused (410), never a bare 404.
     - Save shows "This page was removed", with what was typed kept and an Undo.
     - Autosave says "This page was removed: select Save" and holds other changes, like a refused save.
   - Empty pages from earlier days aren't listed as tabs. `latest` skips them too, so /scratchpad and the Home card never open a page without a tab. `pages_by_day` filters before it counts its 7 days, so a hidden day takes no slot.
   - Opening a removed page (Back after Remove, an old link) shows "This page was removed" with Undo and no editor.
4. **Inbox.** "Approved / Rejected" moves from `?done=` in the address to the message bar: × and Esc close it, and a reload doesn't repeat it.
5. **Quick capture.** Esc leaves the field and keeps what was typed.
6. **Morning brief.** Ctrl+C during playback stops the audio and prints "Stopped." with exit code 130, not a Python trace.
   - Reproduced first, offline: a temporary config, local sources, a `say` clip and real `afplay`. SIGINT went to python and afplay 2.5 s into playback. The result was a 20-line `KeyboardInterrupt` trace, exit −2. The same run follows the fix.
7. **Docs.**
   - ADR 0018 (remove with Undo; `removed_at`).
   - **THREAT_MODEL:**
     - The known gap at line 58 is rewritten: removed items stay on disk; Undo is the only way back in the app until the delete/remove slice; To do and Scratchpad aren't backed up.
     - The To do row cites `test_remove_task_hides_it_everywhere` for read-aloud titles.
   - CHANGELOG, README and this plan's "as built" notes.

## Tests (each must be able to fail; each gets a break test)
- **Message bar** (`tests/test_flash.py`):
  - `::test_message_shows_once_then_clears` (a reload doesn't repeat it);
  - `::test_message_cookie_holds_no_text_and_rejects_junk`.
- **To do** (`tests/test_todo.py`):
  - `::test_remove_task_hides_it_everywhere` (list, card, brief lines, the morning brief count, and a removed read-aloud task whose title never appears);
  - `::test_undo_brings_a_task_back_as_it_was`;
  - `::test_remove_step_renumbers_and_undo_restores_its_place`: remove two steps that held the same place, then Undo both; reorder and add a step after a remove; total minutes skips removed steps;
  - `::test_done_recently_lists_last_week_and_not_done_reopens`;
  - `::test_removed_task_refuses_edits_keeps_typed_values_and_offers_undo`;
  - `::test_undo_and_changes_refuse_items_in_the_wrong_state`: Undo on a live task, step or page changes nothing; Done and bucket on a removed task are refused.
- **Scratchpad** (`tests/test_scratchpad.py`):
  - `::test_remove_page_hides_it_and_undo_restores`;
  - `::test_capture_never_lands_on_a_removed_page`: remove today's only page, then capture: a new page (position 2) holds the note. The same for New page;
  - `::test_removed_page_refuses_edits_and_keeps_typed_text` (410 for Save, autosave and style; typed text and Undo on the page; opening the removed page shows the notice, no editor);
  - `::test_empty_pages_from_earlier_days_are_not_tabs`: covers `latest` (/scratchpad and the Home card), and a hidden day takes none of the 7 slots.
- **Inbox** (`tests/test_inbox_triage.py`): `::test_decision_message_shows_once`.
- **Morning brief** (`tests/test_voice.py`): `::test_ctrl_c_during_playback_stops_cleanly` (exit 130, "Stopped.", no trace).
- **Other tests whose expectations change, none renamed:** `test_inbox_triage.py` (redirects to `/inbox` instead of `?done=`), and `test_todo.py` (positions after a step is removed).
- **Migrations** (`tests/test_migrations.py`):
  - `::test_migration_todo_0002_keeps_every_task_and_step_visible`;
  - `::test_migration_scratchpad_0002_keeps_every_page_visible`;
  - `::test_downgrade_todo_0002_refuses_while_removed_items_exist`;
  - `::test_downgrade_scratchpad_0002_refuses_while_removed_pages_exist`.

  Each seeds rows at 0001, upgrades, and checks every row is still there and not removed. The existing model-matches-migration checks also run.
- **Browser** (`e2e/test_remove.py`, WebKit), each with the keyboard only (Tab, Enter, Esc):
  - `::test_remove_a_task_and_undo`;
  - `::test_remove_a_step_and_undo`;
  - `::test_remove_a_page_and_undo`;
  - `::test_esc_and_close_dismiss_the_message` (Esc in a text field leaves the field first; the bar stays);
  - `::test_reload_does_not_repeat_the_message`;
  - `::test_removed_page_in_another_tab_keeps_its_text`;
  - `::test_quick_capture_esc_leaves_the_field`;
  - `::test_done_recently_not_done`.
- **After the fix:** the offline Ctrl+C reproduction is run again, and its output goes in the PR text.

## Privacy and safety
- No new personal data and no new outside service. The cookie holds a kind and an id only.
- Removed text stays on disk until permanent delete (THREAT_MODEL known gap; the delete/remove slice).
- Undo and Remove are CSRF-protected POSTs. Undo restores only an item that is removed.

## Before running the migration
Copy `data/brain_dock.db` first: To do and Scratchpad aren't in `brain_dock.export` yet. The PR text says so.

## Then
Merge this PR when review is clean and CI is green. Then rebase `feat/todo-card-focus` onto main and continue with UI shell PR 3.

## As built (2026-11-18)
- Built as planned. Changes found while building:
  - **The message bar's variable is `message_bar`:** the error page already uses `message`.
  - **Save and autosave share one queue.** Pressing Save while an autosave was pending sent two saves at once, and one got a 409 (found by the browser tests).
    - Save now finishes through the queue. If the page was showing a notice (changed or removed elsewhere), it reloads to the clean page.
    - If the save is refused, the form posts so the page can say why.
  - **Added after the look review:**
    - a "Remove" on every task row (Today, Can wait, Done recently), next to Edit;
    - Undo on a removed page also keeps the words typed in the old tab, merged like a refused save.
    - Tests: `test_todo.py::test_every_task_row_has_remove_with_undo`, `test_scratchpad.py::test_undo_keeps_the_words_typed_in_the_old_tab` and `e2e/test_remove.py::test_remove_from_a_task_row_and_undo`; `e2e/test_remove.py::test_removed_page_in_another_tab_keeps_its_text` now also presses Undo.
  - **From the PR review:**
    - Save never triggers the browser's "Leave this page?" prompt. Choosing "Stay" there used to leave a page that no longer autosaved.
    - × on a page drawn for a form post (a removed step in an old tab) goes to a real page, not a POST-only address.
    - Undo on an item that's already back goes where Undo would have gone, instead of a bare 409 page.
    - The backup command in the PR uses a timestamped name, so running it twice never overwrites the copy from before the migration.
    - Tests: `test_todo.py::test_message_close_works_without_scripts_on_pages_drawn_for_a_post`; `e2e/test_remove.py::test_removed_page_in_another_tab_keeps_its_text` now fails on any dialog; `test_todo.py::test_undo_and_changes_refuse_items_in_the_wrong_state` checks the redirect.
  - **The To do demo has two tasks finished two days ago,** so "Done recently" has something to show.
  - **Changed, not renamed:**
    - `test_todo.py::test_todo_page_shows_today_and_can_wait` (an older done task is now under "Done recently", not gone);
    - `::test_steps_keep_their_order_when_added_moved_and_removed` and `::test_edit_task_and_its_steps` (read live steps);
    - `test_scratchpad.py::test_pages_by_day_and_new_page` (its earlier page has text now);
    - `test_inbox_triage.py` (redirects to `/inbox` with the message cookie);
    - `test_todo_brief.py::test_todo_demo_writes_only_the_demo_database` (7 demo tasks).
- **Tests:**
  - `uv run pytest`: 782 → 809 (806, then 2 after the look review, then 1 from the PR review). That's the plan's 18 tests plus 6 per-template security checks for the three new templates. None removed or renamed.
  - `uv run pytest e2e`: 64 → 73: the plan's 8 in `e2e/test_remove.py`, plus the row test.
- **Break tests** (each restored, then rerun and seen passing; compiled caches cleared each run):
  - 17 unit guards: hiding, restore, step place, done recently, the removed-task and removed-page refusals, page numbering, `latest`, both migrations, both downgrades, the message cookie and Ctrl+C.
  - 6 browser guards: Esc in a field, Esc on the bar, quick capture Esc, autosave on a removed page, the bar shown at all, and the Save race.
- **Ctrl+C**, the same offline run (temporary config, `say` clip, real `afplay`):
  - before: a 20-line `KeyboardInterrupt` trace, exit −2;
  - after: "Stopped.", exit 130.
