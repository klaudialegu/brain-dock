# Plan: harness PR 5, the inbox module (rules only) and the triage page
**Status:** 4c merged (#43). 5a merged (#44); real database migrated to `inbox_0001` 2026-10-31 after a clean rehearsal. 5b in review.

Design: [agent-harness.md](agent-harness.md), sections 2 to 4. Decisions: ADR 0008, [ADR 0011](../decisions/0011-inbox-writes-stay-in-the-inbox.md) (what "approve" writes). Previous: [pr4-runs-approvals-plan.md](pr4-runs-approvals-plan.md).

**Why:** the harness (PRs 2 to 4) has no agent yet. PR 5 adds the first one with no model: synthetic job-alert emails are parsed, plain-Python rules decide, and anything that passes waits for my approval. PR 6 then adds the model judge for the cases the rules can't settle.

All data is synthetic. No API key, no network, no model call in this PR.

## The split
- **4c: a small core fix that goes first** (below). A decided approval moves its work item out of `pending_approval`.
- **5a: the inbox engine, no UI.** Proven by tests only.
- **5b: the triage page.** Proven by tests and by my Safari check.
- **Fallback split point if 5a runs past one session:** stop after step 4 below and open it as **5a-1** (module, tables, fixtures, parser, role key). Config, rules and the workflow become **5a-2**. All of 5a's tables are in 5a-1's migration, so 5a-2 needs no migration and the real database is migrated once. The check: when half the session is gone, is 5a-1 green with its test-ID diff matching? If not, cut there.

## Decisions in this plan
1. **What "approve" writes (ADR 0011, option B):** the inbox declares one write tool, `accept_suggestion(suggestion_id: int)`. It only marks the suggestion `accepted` in the inbox's own table. Nothing is written into job search. I save the job myself (the PR 0b form, until a handoff exists). The full approval path still runs: pending approval, HMAC'd input, `executing` before the tool runs, at most once. ADR 0011 shapes this so a core-brokered handoff (option A) can be added later in its own PR, without changing the inbox's workflow or its existing rows.
2. **The work item is a role, not an email.** A job alert usually lists several roles, and each one needs its own decision and approval. The email is stored once (unique Message-ID) and links to the roles it contained.
3. **The role dedupe key (detail below):** the normalized `(company, title, location, link)`. When unsure, a duplicate beats a merge: a duplicate I can reject in one click, but a wrong merge hides a role, which breaks "never drop silently".
4. **Missing data never skips:** a missing or unreadable salary, location or seniority sends the role to `needs_review` with a reason code. Only a field that is **present and clearly fails** can skip a role. When one field clearly fails and another is missing, the role is skipped: the failing field is enough evidence on its own (confirmed 2026-10-31; one test pins this order).
   - **Salary uses the top of the range:** a role passes when the range's top is at or above the floor, so a range that straddles the floor passes. A single value is its own top, and "up to X" has top X. An open-ended "from X" has no top, so it goes to review (`salary_no_top`).
   - **"Remote" and "Hybrid – <city>" are valid locations, not missing ones.** The parser reads `Remote`, `Hybrid – <city>` (en dash or hyphen) and a plain city. Matching: a remote role passes when `remote` is in my configured locations, and a hybrid or onsite role passes when its city is. A bare "Hybrid" with no city counts as missing.
   - **Skipped roles stay visible:** a rule skip keeps its reason code on the role, and the rejection log (5b) lists rule skips next to my rejections, each labeled by where it came from (rules or me).
5. **A missing local config fails closed:** the run refuses to start before anything is received, and it never falls back to the example values.
6. **Ask first (CLAUDE.md, new personal data):** the rules need my home location(s), accepted seniority levels and a salary floor. They live **only** in gitignored `config.toml` (`[inbox]` section), next to a committed `config.example.toml` with fake values. They're never stored in the database, the audit log, the flight recorder or logs. Rules run locally, so they're never sent to any API. Error messages name the key, never the value. Confirmed 2026-10-31 (`config.toml` checked as ignored by `.gitignore:49` and never tracked).

## The role dedupe key
- **Fields:** company, title, location, link. A missing field counts as `""`, never NULL (SQLite treats NULLs as all different, so a unique constraint would let duplicates in).
- **Normalizing:**
  - **All text:** Unicode NFKC, casefold, punctuation turned into spaces, whitespace collapsed, trimmed.
  - **Company:** a trailing legal suffix from a short fixed list (`inc`, `llc`, `ltd`, `gmbh`, `corp`, `co`) is dropped.
  - **Title:** `sr` becomes `senior`, `jr` becomes `junior`. No other rewording.
  - **Link:**
    - Scheme becomes `https`, the host is lowercased with `www.` dropped, and the fragment and a trailing slash are dropped.
    - **Known tracking parameters are dropped**, matched without regard to case: any `utm_*`, plus `trackingId`, `refId`, `trk`, `trkInfo`, `ref`, `source`, `src`, `gclid`, `fbclid`.
    - **Every other parameter stays**, including identifying ones (`gh_jid`, `jobId`, `currentJobId`) and any parameter that isn't on the list. The remaining parameters are sorted.
    - The drop list names what to remove, not what to keep: an unfamiliar parameter is kept, so the worst case is a duplicate, never a merge.
- **Where it's enforced, twice:**
  - **The core:** the work item's key is `Items.key_for("inbox", canonical_json(fields))`, a keyed hash (PR 4b), so the same role is one item.
  - **The inbox:** `inbox_role` has a unique constraint on the four normalized columns. These are plain columns, not a hash: the inbox's own table holds the role anyway, and plain columns are readable and debuggable.
- **Two emails, one role:** the second email links to the existing role through `inbox_role_source (role_id, email_id)`, which is unique per pair. The same email received twice changes nothing.

## PR 5a: the inbox engine (migration `inbox_0001`, new tables only)
1. **The module:** `src/brain_dock/modules/inbox/`: `manifest.py` (agent tool `accept_suggestion`, effect `write`, int input only), `models.py`, `migrations/` (its own branch) and an entry in `registry.py`. Add its folder to `version_locations` in `alembic.ini`. A folder missing from there is the known raw-traceback follow-up in NEXT.md, so this PR hits it on purpose and checks the message.
   - **Tables:** `inbox_email` (message-id hash, received date, parse status, reason code; **no body**), `inbox_role` (normalized and display fields, parsed salary min/max/currency/period, location, seniority, status, reason code), `inbox_role_source`.
2. **Synthetic fixtures:** `tests/fixtures/inbox/*.eml`, on reserved domains only (`example.com`, `.test`), each with an `X-Synthetic: true` header. A fixture guard test enforces both (pulled forward from Phase 3b, because these are the first email fixtures).
3. **The parser:** `inbox/parser.py`. An alert becomes one or more roles. An unreadable value (salary "competitive", a blank location) becomes **missing**, never a guess. An email with no roles is stored as `needs_review` (`no_roles_found`), never dropped. Only the parsed fields are kept, never the body.
4. **The role key:** `inbox/roles.py`, as above.
   *(Fallback split point: 5a-1 ends here.)*
5. **Local config:** `inbox/config.py` loads and validates `[inbox]` from `config.toml` (path passed in; tests use `tmp_path`). Plus `config.example.toml` (fake values) and a README setup line.
6. **The rules and the workflow:**
   - **Rules:** `inbox/rules.py` returns `pass`, `skip(reason)` or `review(reason)` per role.
   - **Reason codes:** `location_mismatch`, `seniority_mismatch`, `salary_below_floor`, `missing_salary`, `missing_location`, `missing_seniority`, `salary_no_top`, `salary_other_currency`, `salary_not_annual`.
   - **Salary math:** the top of the range against the floor (decision 4). No currency conversion: another currency goes to review.
   - **Workflow:** `inbox/agent.py`. The workflow is `received → ruled → pending_approval | skipped | needs_review`, then `pending_approval → approved | rejected` (final states, required by 4c). `ruled` calls `accept_suggestion` through the dispatcher, which creates the pending approval. `run_inbox()` loads the config first, then parses, receives and runs. PR 6 adds `judged` between `ruled` and `pending_approval`.

### 5a test IDs (466 → 548, after 4c; none removed or renamed)
**`tests/test_module_contract.py` and `tests/test_modules_off.py`, `[inbox]` (+10, automatic):**
- `test_manifest_is_complete`, `test_routes_stay_in_declared_paths`, `test_post_routes_check_csrf`, `test_tables_match_the_manifest_and_are_prefixed`, `test_imports_no_other_module`, `test_migrations_are_a_branch_of_their_own`, `test_migrations_match_the_models`, `test_agent_tools_follow_the_policy`, `test_core_runs_with_module_disabled`, `test_disabling_keeps_the_data`

**`tests/test_inbox_parser.py` (+14):**
- `test_parses_a_synthetic_alert_into_roles`
- `test_an_alert_with_several_roles_gives_one_role_each`
- `test_unreadable_values_become_missing_not_guessed[salary_competitive|salary_no_currency|location_blank|hybrid_without_city|no_seniority_word]` (5)
- `test_location_formats_are_read_not_missing[remote|hybrid_en_dash_city|hybrid_hyphen_city|plain_city]` (4)
- `test_an_email_with_no_roles_is_parked_not_dropped`
- `test_email_bodies_are_not_stored`
- `test_fixtures_are_synthetic_and_use_reserved_domains`

**`tests/test_inbox_role_key.py` (+22), decision 3:**
- `test_role_key_normalizes[case_and_spaces|company_suffix|fragment_and_trailing_slash|scheme_and_www]` (4)
- `test_link_drops_tracking_params[utm_prefix|trackingId|refId|trk|gclid]` (5)
- `test_link_keeps_identifying_and_unknown_params[gh_jid|jobId|currentJobId|unknown_param]` (4)
- `test_role_key_keeps_different_roles_apart[title|location|link|company|job_id_query_param]` (5)
- `test_the_same_role_in_two_emails_is_one_item_with_both_sources_linked`
- `test_the_same_email_twice_changes_nothing`
- `test_a_missing_field_counts_as_empty_not_unique`
- `test_role_item_keys_are_keyed_hashes`

**`tests/test_inbox_config.py` (+10), decisions 5 and 6:**
- `test_missing_config_refuses_the_run_before_anything_is_received`
- `test_incomplete_or_invalid_config_refuses_the_run[missing_section|missing_key|negative_floor|unknown_currency|empty_locations|unknown_seniority]` (6)
- `test_never_falls_back_to_the_example_file`
- `test_config_errors_name_the_key_never_the_value`
- `test_the_example_config_is_complete_and_valid`

**`tests/test_inbox_rules.py` (+21), decision 4:**
- `test_a_clear_miss_is_skipped_by_rules[location|seniority|salary_below_floor]` (3)
- `test_missing_data_goes_to_needs_review_never_skipped[salary|location|seniority]` (3)
- `test_a_clear_miss_wins_over_a_missing_field`
- `test_unclear_salary_goes_to_needs_review[other_currency|not_annual]` (2)
- `test_salary_floor_boundary[top_at_floor_passes|top_below_floor_skips]` (2)
- `test_salary_compares_the_top_of_the_range[straddles_floor_passes|single_value_is_the_top|up_to_value_is_the_top|open_ended_goes_to_review]` (4)
- `test_remote_and_hybrid_locations_are_matched[remote_listed_passes|remote_not_listed_skips|hybrid_listed_city_passes|hybrid_other_city_skips]` (4)
- `test_a_skipped_role_keeps_its_reason_code`
- `test_a_role_that_passes_every_rule_is_suggested`

**`tests/test_inbox_workflow.py` (+5):**
- `test_inbox_workflow_definition_is_sound`
- `test_a_suggestion_waits_for_approval_and_nothing_is_written`
- `test_accepting_writes_only_inbox_data` (the approval runs once; every job search table is unchanged: option B's proof)
- `test_every_email_ends_suggested_skipped_or_needs_review` (the invariant, over every fixture)
- `test_decisions_leave_no_content_or_thresholds_in_core_tables_audit_or_logs`

**If cut at the fallback point:**
- **5a-1:** contract +10, parser +14, role key +22 (466 → 512).
- **5a-2:** config +10, rules +21, workflow +5 (512 → 548).

The real counts come from `pytest --collect-only` at the end of each PR, diffed against main.

**Changes found while building 5a (reported in the PR):**
- **A status page:** the module contract needs a route, a nav entry and a home page, so 5a has a counts-only `/inbox` page (no role content). The 5b triage page replaces it at the same path. +1 test (`test_inbox_status_page_shows_counts_only`) and +2 automatic template checks.
- **No double asks on resume:** if a run crashes after the approval is created but before the item moves on, the resumed run must not create a second approval. +1 test (`test_a_resumed_run_never_asks_twice_for_the_same_role`).
- **Every trailing legal suffix is dropped,** not just one: "Corp" is itself a suffix, so "Example Corp" and "Example Corp, Inc." only agree if both lose all of them.
- **Not done:** the plan said 5a would check the error message for a module migration folder missing from `alembic.ini`. That stays the open follow-up in NEXT.md; 5a lists its folder correctly and the contract test checks it.
- **Actual count:** 466 → 552 (+86 = 82 planned + 4 above), none removed or renamed.

**Real database:** `inbox_0001` adds tables only. Same routine as PRs 0 to 4: backup with main's code, rehearse on copies (row checksums and every page compared with main), migrate, `verify_audit`, recount.

## PR 4c: decided approvals move their work item (core fix, goes first, no migration)
**Why:** found while planning PR 5. `approve()` and `reject()` update the approval, but its work item stays in `pending_approval` forever, so the "every item ends final or waiting" invariant hides items that were already decided. **Checked 2026-10-31:** the real database has 0 runs, 0 work items and 0 approvals (counts only, read-only), so nothing is stuck and no data repair is needed.
1. **The core moves the item in the same decision:**
   - executed → `approved`;
   - rejected → `rejected` (keeping the reason code);
   - failed, or parked as `input_changed` or `interrupted` → `needs_review`.
2. **The definition check:** a workflow with a waiting state must declare `approved` and `rejected` as final states. The test workflow in `tests/test_runs.py` gains both. That changes a fixture, not a test ID.

### 4c test IDs (462 → 466)
- **`tests/test_approvals.py` (+3):**
  - `test_an_executed_approval_moves_its_item_to_approved`
  - `test_a_rejection_moves_its_item_to_rejected_with_its_reason`
  - `test_a_failed_or_parked_approval_parks_its_item`
- **`tests/test_runs.py` (+1):** `test_a_workflow_with_waiting_states_declares_approved_and_rejected`

## PR 5b: the triage page (no migration)
1. **The triage page `/inbox`:** pending suggestions with their parsed fields and the rule outcome. **Approve** and **Reject** are CSRF-protected form posts that call `approve()` and `reject()`. Reject offers a fixed list of reason codes (`not_a_fit`, `wrong_location`, `wrong_level`, `pay_too_low`, `duplicate`), never free text. The page says so when the rules aren't configured.
2. **Needs review `/inbox/review`:** parked roles and emails, with reason codes.
3. **The rejection log:** reason codes and counts on the triage page. It has two sources, each labeled: my rejections (from the approvals table) and **rule skips** (from the roles' reason codes), so a skipped role never disappears. Prompt version and model join it in PR 6.
4. **Safari check (mine):** approve once, reject once, double-submit approve, and the console stays clean under the CSP.

### 5b test IDs (552 → 565, exact, fixed when 5b started)
**Removed (1):** `tests/test_inbox_workflow.py::test_inbox_status_page_shows_counts_only`. 5a's counts-only page is replaced by the triage page at the same path, as 5a planned, so "counts only" can't stay true. The counts stay on the triage page, and its template keeps the name `index.html`, so its two template checks stay.

**Added (14):**
- **`tests/test_inbox_triage.py` (+12):**
  - `test_triage_page_lists_pending_suggestions`
  - `test_approve_button_runs_the_approval_once`
  - `test_reject_accepts_only_listed_reason_codes`
  - `test_approve_is_refused_while_a_run_is_active`
  - `test_review_page_shows_reason_codes_only`
  - `test_rejection_log_counts_reason_codes`
  - `test_rejection_log_includes_rule_skips_with_their_reason_codes`
  - `test_triage_page_says_when_rules_are_not_configured[missing|broken]` (2)
  - `test_the_app_starts_without_inbox_config` (promised during the 5a migration review)
  - `test_triage_forms_only_decide_inbox_approvals` (new: the page can't decide another module's approval)
  - `test_inbox_demo_writes_only_the_demo_database` (new: the demo loader, below)
- **Templates (+2):** `review.html` in `test_security_headers.py` and `test_vendor.py`.

**Also in 5b, found while building:**
- **A demo loader:** `uv run python -m brain_dock.modules.inbox.demo` runs the synthetic alerts (moved from `tests/fixtures/inbox/` to `demo/inbox/`) through the rules into `data/demo.db` with `config.example.toml`, passed explicitly. It always targets the demo database and refuses one that isn't migrated. This is what the Safari check uses.
- **Test runs now sign approvals with the database's own key file:** the triage page refused approvals a test runner had signed with a fixed test key (`input_changed`). That's the HMAC check working as designed.
