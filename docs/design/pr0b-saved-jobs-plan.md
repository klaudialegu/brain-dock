# Plan: PR 0b, saved jobs UI
**Status:** merged (PR #46, 2026-11-01) after the Safari check. No migration.

Decision: [ADR 0009](../decisions/0009-interested-stage.md) (saved jobs), [ADR 0011](../decisions/0011-inbox-writes-stay-in-the-inbox.md) (the inbox's prefill link). Previous: [pr5-inbox-plan.md](pr5-inbox-plan.md).

**Why:** saved jobs exist in the data since PR 0a (an `Application` with no `applied_on` and an "interested" event), and `save_interested()` and `mark_applied()` are tested, but every page hides them. PR 0b gives them pages. It also gives an approved inbox suggestion somewhere to land, by hand, until a core-brokered handoff exists. No migration.

## Steps
1. **A "Saved jobs" section on `/applications`:** role (with link), company, saved date, and a **Mark applied** form (date, default today). Saved jobs stay out of the table, the stats and the chart.
2. **"Save a job" form** at `/applications/saved/new`, posting to `/applications/saved`:
   - the same fields and rules as Add application, with "Saved on" instead of "Applied on";
   - CSRF, post/redirect/get, and a nav entry.
   - These routes are declared before `/applications/{application_id}`, so "saved" is never read as an id.
3. **Mark applied** (`POST /applications/{id}/applied`):
   - a date before the saved date returns 400 with the message next to the form;
   - anything that isn't a saved job returns 404, including a second mark.
4. **Company page:** a "Saved jobs" list, separate from the application timelines, read-only. A company holding only saved jobs works (ADR 0006 deletes a company only when an edit moves its last application away, and saved jobs have no edit page).
5. **Demo data:** two fake saved jobs in `demo/applications.json`, using companies from the fake-company allowlist.
6. **The inbox prefill (ADR 0011):**
   - each accepted role gets a "Save as interested" link to `/applications/saved/new?company=…&role_title=…&link=…`;
   - the link is shown only while job search is enabled;
   - the form prefills only those three fields: text is trimmed and capped, and the link must be http(s).

## Test IDs (566 → 578, none removed or renamed)
- **`tests/test_saved_jobs_ui.py` (+8):**
  - `test_list_shows_saved_jobs_in_their_own_section`
  - `test_save_form_saves_a_job_as_interested`
  - `test_save_form_shows_errors_next_to_fields`
  - `test_mark_applied_turns_a_saved_job_into_an_application`
  - `test_mark_applied_refuses_an_earlier_date_or_a_second_time`
  - `test_company_page_shows_saved_jobs_separately`
  - `test_save_form_prefills_only_safe_values_from_the_link`
  - `test_inbox_links_accepted_roles_to_the_save_form`
- **Templates (+4):** `saved_form.html` and `partials/saved_jobs.html`, in `test_security_headers.py` and `test_vendor.py`.

**Mutation check:** four deliberate breaks, each now failing tests:
- prefilling any link;
- marking any application applied;
- showing the link while job search is off;
- listing applied jobs as saved. This one first survived. The company-page test now covers a job saved and then applied.
