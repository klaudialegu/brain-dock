# Plan: Playwright tests for the Safari checklist

**Status:** approved by Klaudia (2026-11-01), after two review rounds (both 🟡, all fixes applied). Build it in the next Brain Dock session. `e2e` is not a required check at first: watch it for a week of PRs, then decide. Branch `test/playwright-checklist`, cut from main after PR #52 merges (the tests use the Career Radar labels). Dependency approved by Klaudia on 2026-11-01.

**Why:** every UI PR ends with the same 10-item check in Safari, done by hand. Playwright drives a real browser engine, so the checklist can run in CI on every PR and leave one screenshot per item to glance at. WebKit is Safari's engine, so it's the closest match short of Safari itself.

## Steps
1. **Dependency (dev group only):** `playwright` (Microsoft), pinned in uv.lock. Without the pytest-playwright plugin, which adds python-slugify and its own fixtures, a small `e2e/conftest.py` does the same in about 40 lines. The browser is installed separately with `uv run playwright install webkit` (CI adds `--with-deps`).
2. **Folder and run:** the tests live in `e2e/`, outside `testpaths = ["tests"]`, so `uv run pytest` stays as it is (586 tests, no browser needed). The browser tests run with `uv run pytest e2e`.
3. **Fixtures (`e2e/conftest.py`), demo data only:**
   - **Real-data guard, `guard_temp_db(path)`:** an allow-list, not a deny-list. The resolved path must be inside pytest's temp folder and outside the repo, or it raises before anything opens the file. It is the **first line of the database fixture** (before `get_engine`, `migrate` or `rebuild_db`, which deletes rows when unlocked), and it runs again in the server fixture. (Review round 2.)
   - A throwaway database in that temp folder: migrate, then the job search demo set (`rebuild_db` + `DEMO_JSON`), then the inbox demo (`load_demo(path)`).
   - A real uvicorn server **as a subprocess** (like scripts/check_modules_off.sh), on `127.0.0.1` and a free port, with `BRAIN_DOCK_DB` (the temp file) and `BRAIN_DOCK_MODULES` in its environment. A thread inside pytest would be too late: `db.DB_PATH` is fixed when the module is imported (core/db.py:30). One server for the whole run; tests that write use their own uniquely named rows, so order doesn't matter.
   - Before startup, a random marker company goes into the temp database, and the fixture checks that a page from the running server shows it. Without the marker, no test gets the server.
   - Teardown: the server is stopped with `terminate()`, then `wait(timeout)`, then `kill()`; the browser and Playwright are closed at session end. Otherwise `filterwarnings = ["error"]` turns a ResourceWarning into a flaky failure. (Review round 2.)
     - The server reads the local `config.toml` if there is one; the inbox only shows its key names (routes.py:5), and screenshots come from CI, which has no config.toml. (Review round 1.)
   - One WebKit browser for the run; a fresh page per test at 1280×900.
   - On every page: listeners that record `securitypolicyviolation` events (sent to Python with `page.expose_binding`, so they survive navigation), console errors and uncaught JavaScript errors (`pageerror`). Playwright's `bypass_csp` stays off, and a test asserts that. **Every test's teardown fails if anything was recorded**, so the pages after a form post (400 errors, /inbox after an approval, the prefilled form) are checked too. (Review round 1.)
4. **Screenshots:** every test saves `e2e-artifacts/NN-name.png` (full page); the parametrized items include the page in the name (e.g. `09-narrow-inbox.png`), so nothing overwrites. It's saved on failure too, so a red run shows the broken page. A session-end hook writes `e2e-artifacts/index.html`: the 10 items in order, each with its screenshots (items 9 and 10 group their 7 pages) and pass/fail; the detector and guard tests are listed separately, so one page is all there is to glance at. `e2e-artifacts/` is gitignored.
5. **Tests (`e2e/test_safari_checklist.py`), one per checklist item:**
   1. A "Saved jobs" section with saved rows, kept out of the table and the stats. The test saves its own uniquely named job, then checks that the stats are the same before and after and that the name isn't in the applications table.
   2. The "Save a job" nav entry and button.
   3. Save a job, and it lands in Saved jobs.
   4. A bad link or no company: errors show next to the fields, and nothing is saved. Use inputs the browser accepts but the server rejects (WebKit's own `required` and `type=url` checks would block an empty or malformed submit): a company of only spaces, and `ftp://example.com` as the link. Check `.field-error` and `aria-invalid` on those fields, and that the saved-row count is unchanged.
   5. Mark applied too early, and an error shows next to that row.
   6. Mark applied with a valid date: the job moves to the table and its Edit page opens. The app redirects to /applications, so the test checks that the name is in the table and gone from Saved jobs, then clicks that row's Edit link and gets the edit form (for a saved job, that page is a 404).
   7. The company page shows a read-only saved list.
   8. /inbox → Accepted → "Save as interested" opens a prefilled form. The demo inbox has 3 roles waiting and none accepted, so the test first approves one waiting role, then checks that the form is prefilled with that role's company, title and link.
   9. A narrow window (375 px wide): no page scrolls sideways. Wide tables scroll inside `.table-wrap`, which is allowed.
   10. No CSP violations or console errors on any page, and the pipeline chart draws (proof the scripts ran under the CSP).
6. **Detector self-checks** (the tests must be able to fail):
   - Item 9's check flags a page after the test injects a 2000 px wide element.
   - Item 10's listeners: after an injected inline script there must be an entry **of type `securitypolicyviolation`** (not just the console error WebKit also prints), recorded before a navigation and read after it; a thrown error gives a `pageerror`; and `bypass_csp` is off.
7. **CI job `e2e`** (ubuntu-latest, 15-minute timeout, `contents: read`):
   - Steps: checkout (with `persist-credentials: false`, like the other jobs) and setup-uv (same pinned SHAs as now), `uv sync --locked`, `uv run playwright install --with-deps webkit`, `uv run pytest e2e`.
   - Then `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2` with `if: always()`, artifact name `safari-checklist`, kept 14 days. The SHA was checked against the upstream tag on 2026-11-01.
8. **Docs:** README (Development: how to run the browser tests locally), CHANGELOG `[Unreleased]`, and the CLAUDE.md Commands section.

## Test IDs
`uv run pytest`: **586 → 586**, unchanged (nothing added, renamed or removed under `tests/`).

`uv run pytest e2e`: **0 → 27**, all new (8 + 7 + 7 + 1 + 2 + 2):
- `e2e/test_safari_checklist.py::test_01_saved_jobs_kept_out_of_table_and_stats`
- `::test_02_save_a_job_nav_entry_and_button`
- `::test_03_save_a_job_lands_in_saved_jobs`
- `::test_04_bad_link_or_no_company_shows_field_errors_and_saves_nothing`
- `::test_05_mark_applied_too_early_shows_row_error`
- `::test_06_mark_applied_moves_job_to_table_and_opens_edit`
- `::test_07_company_page_lists_saved_jobs_read_only`
- `::test_08_inbox_accepted_save_as_interested_prefills_form`
- `::test_09_narrow_window_nothing_clipped[<page>]`: 7 pages (applications, add, save a job, edit, company, inbox, inbox review)
- `::test_10_no_csp_violations_or_console_errors[<page>]`: the same 7 pages
- `::test_10_pipeline_chart_draws_under_csp`
- `e2e/test_detectors.py::test_overflow_detector_catches_a_wide_element`
- `e2e/test_detectors.py::test_csp_listener_catches_an_inline_script` (also covers `pageerror`)
- `e2e/test_server.py::test_e2e_server_uses_a_temp_database`: reports the fixture guard (the target is in the temp folder, and the marker company is served); the guard itself runs before any write.
- `e2e/test_server.py::test_guard_refuses_repo_data_paths`: `guard_temp_db` refuses `data/demo.db`, `data/brain_dock.db` and a path in the repo, without opening any of them. (Review round 2; replaces the manual break test.)

**Added during the build (2026-11-17): 27 → 28.** WebKit logs "Failed to load resource: … 400" for a page's own document when a form comes back with errors (items 4 and 5, which return 400 on purpose). Those two tests opt in with `recorder.expect_error_page(400)`, which excuses only that status line, only for that document's URL, and only when the navigation really returned 400. CSP violations, JavaScript errors and subresource failures on the page still fail.
- `e2e/test_detectors.py::test_error_page_opt_in_excuses_only_that_document`: the opt-in excuses that one line and nothing else (a subresource 400, a 500 on the same page, a CSP violation and a pageerror all still count).

Break tests before the PR, each reverted and recorded in the PR:
- Remove the Saved jobs heading, and test 01 fails.
- Add an inline `style=` to a template, and test 10 fails.
- Set a fixed 900 px width on the applications table's wrapper **in app.css** (an inline style would trip the CSP check first), and test 09 fails.

## Privacy
- Demo data only, in a temp database; `test_e2e_server_uses_a_temp_database` proves it.
- Screenshots show fake demo companies only. On a public repo, Actions artifacts can be downloaded by anyone logged in to GitHub, which is fine for demo data, and they're deleted after 14 days.
- No secrets; the job has only `contents: read`.

## Not in this slice
- Making `e2e` a required check (Klaudia decides; see the card).
- Real Safari: WebKit is close but not the same (for example the native date picker). A quick look in Safari stays worthwhile for UI-heavy PRs.
- Regenerating the README screenshot from this job (parked: it could replace the manual retake).
