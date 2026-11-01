# Plan: Brain Dock as a modular daily-efficiency assistant; job search shown as Career Radar

**Status:** approved by Klaudia (2026-11-01), with her changes to the description, topics, planned modules and wording check. Branch `docs/modular-assistant`.

**Why:** Brain Dock is a core plus modules (ADR 0007), but it still introduces itself as a job-search tracker. It is **a modular personal daily-efficiency assistant**. The job search module is shown as **Career Radar**: keeping an eye on the job market, skills in demand, and interesting roles. Today it covers applications, saved jobs, the pipeline and stats. The market and skills views are planned.

**Wording only.** Code folders, module names (`job_search`, `inbox`), routes, table names, behaviour and data stay the same. The repo stays public.

## Steps
1. **ADR 0012 (display names are not module names):** a module has a code name (`job_search`, which is stable: it's the folder, the template prefix, `BRAIN_DOCK_MODULES` and the migration branch) and a display name (Career Radar), which is wording and free to change. It records why the folder isn't renamed. (0010 stays reserved for the Gmail brief.)
2. **UI labels and nav (job search templates + manifest strings only):**
   - Nav: `Applications` → `Career Radar` (same link, /applications). `Add application`, `Save a job` and `Inbox` stay.
   - /applications: `<h1>Career Radar</h1>`, then one line: "Keeping an eye on the job market, skills in demand, and interesting roles. Market and skills views are planned."
   - Then `<h2>Applications</h2>` directly above the "N applications, newest first" line and the table, after "Pipeline". The table then sits under its own heading, not under "Pipeline". The heading also shows before the "No applications yet" line, so the empty state isn't read as part of "Saved jobs".
   - **The quick-start smoke script:** `scripts/check_quickstart.sh:76` checks for `<h1>Applications</h1>` and becomes `<h1>Career Radar</h1>`. CI runs it on a fresh clone; pytest doesn't.
   - Page titles in the module get "· Career Radar" before "· Brain Dock": the list, add, edit, save a job, the company page. Inbox titles stay the same.
   - The modules-off home page (core `home.html`) gets the tagline under its `<h1>`: "A modular personal daily-efficiency assistant."
   - The manifest `description` strings are updated to the new wording (not shown in the UI; no behaviour change).
3. **README:** the tagline. "Features" becomes "Modules":
   - **Career Radar** (code name `job_search`): what's built (applications, saved jobs, pipeline, stats), plus market trends and skills in demand *(planned)*.
   - **Inbox:** job-alert triage, with a link to save a role in Career Radar (it writes nothing into Career Radar itself, ADR 0011).
   - **Planned:** daily brief, projects and learning, each marked *(planned)*. (Interview prep is not listed.)
   - What every module gets from the core.
   - The screenshot caption and alt text name Career Radar. **`docs/screenshot.png` is retaken after the UI change** from the demo database, the same way as PR #50: cropped to the page, metadata stripped, checked for real data before committing. Klaudia takes it during her Safari check (Claude can't drive Safari). "Why I built it" stays in Klaudia's words except its last sentence, which becomes "Career Radar is the first module." (her choice). The ADRs stay as they are (historical records).
4. **Docs:**
   - CLAUDE.md "What this is" and the Map line (job_search is shown as Career Radar).
   - docs/usage.md "Modules" intro.
   - The pyproject `description`.
   - CHANGELOG `[Unreleased]`.
5. **GitHub repo description and topics** (a repo setting, so Klaudia's OK first):
   - Description (Klaudia's wording): "A modular personal daily-efficiency assistant. Local-first. First module: Career Radar (saved roles, pipeline and stats today; market and skills views planned). Python, FastAPI, SQLite, and a safety-first agent harness, built with Claude Code."
   - Topics: productivity, personal-assistant, local-first, python, fastapi, sqlite, ai-agents, claude-code. (No job-search or career.)
6. **Checks:**
   - Tests, ruff, `uv lock --check`.
   - CI logs for the head SHA, including the **quickstart job** (`scripts/check_quickstart.sh`, which now checks `<h1>Career Radar</h1>`).
   - Klaudia's Safari check of the nav, the /applications headings and a narrow window, plus the new screenshot.

## Test IDs (578 → 586; 1 renamed, none removed)
Renamed (the parameter is the visible label, so the ID follows it):
- `tests/test_applications_page.py::test_nav_on_every_page_marks_the_current_one[/applications-Applications]` → `[/applications-Career Radar]`

Changed assertion, same ID:
- `tests/test_company_page.py::test_company_name_is_escaped_in_title_and_heading`: the title assertion becomes `· Career Radar · Brain Dock`.

New (each fails before the change):
- `tests/test_applications_page.py::test_applications_page_is_career_radar`: the `<h1>Career Radar</h1>`, the planned-views line, and `<h2>Applications</h2>` placed after the "Pipeline" heading and before the table (it checks the order, so a misplaced heading fails).
- `tests/test_applications_page.py::test_module_pages_title_career_radar[...]`: 5 cases (the list, add, edit, save a job, company page), each `<title>` ending `· Career Radar · Brain Dock`.
- `tests/test_applications_page.py::test_applications_heading_shown_when_empty`: with no applications, `<h2>Applications</h2>` comes before "No applications yet". (Added after review round 2.)
- `tests/test_modules_off.py::test_home_without_modules_shows_tagline`: the modules-off home page shows "A modular personal daily-efficiency assistant."

Promised without a test, on purpose: the README, docs and GitHub description are wording, checked in review and with `git grep -n -i -E "job[- ]search|interview|job hunt"` for leftover wording (outside ADRs, docs/design, the v0.1 CHANGELOG entry and code comments); each remaining hit is listed in the PR.

## Not in this slice
- Renaming `job_search` in code (ADR 0012 says it stays).
- The market trends and skills views themselves (Phase 4).
- Playwright tests: the next slice (dependency approved 2026-11-01). They'll use these labels.
- Also on this branch: the CLAUDE.md rule on triaging scanner alerts (approved at the 2026-11-01 wrap-up).
