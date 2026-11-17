# Threat model

One page: what's sensitive in Brain Dock, what agents may never do, and what enforces each rule. Test IDs are under `tests/` unless they start with `e2e/`. The details behind the agent rules are in [docs/design/agent-harness.md](docs/design/agent-harness.md) (section 6) and [ADR 0008](docs/decisions/0008-agent-harness.md).

**Setting:** one person, on their own Mac. The app listens on `127.0.0.1` only. The database is the source of truth (ADR 0004). **Out of scope:** an attacker who already controls this machine. They could read the database, the audit key and `.env` directly, so nothing here claims to stop them.

## What's sensitive

| Data | Where it lives | Rule | Enforced by |
|---|---|---|---|
| Applications, companies, notes, stages | `data/brain_dock.db` | Never in git; tests and demos never open it | `test_importer.py::test_personal_data_files_are_gitignored`; `e2e/test_server.py::test_guard_refuses_repo_data_paths`; `test_inbox_triage.py::test_inbox_demo_writes_only_the_demo_database` |
| Backups, the import file | `data/backups/`, `data/my_applications.json` | Never in git; backups owner-only; the importer never wipes without a full backup | `test_importer.py::test_personal_data_files_are_gitignored`; `test_export.py::test_backup_file_is_owner_only`; `test_importer.py::test_failed_backup_aborts_without_wiping` |
| Personal settings (location, salary thresholds) | `config.toml` | Never in git; errors name the key, never the value | `test_importer.py::test_personal_data_files_are_gitignored`; `test_inbox_config.py::test_config_errors_name_the_key_never_the_value` |
| Secrets (API keys, tokens) | `.env` or the macOS keychain | Never in git, logs or output | `test_importer.py::test_personal_data_files_are_gitignored`; GitHub secret scanning and push protection |
| Audit key | next to the database | Owner-only, never shown, never in git | `test_audit_log.py::test_key_is_made_once_owner_only_and_stays_out_of_git`, `::test_a_key_others_can_read_is_refused`, `::test_key_never_shows_in_repr_or_logs` |
| Anything typed into a form | the request | Never logged | `test_application_form.py::test_typed_values_never_appear_in_logs`; `test_edit_and_stages.py::test_edit_never_logs_typed_values` |
| Not built yet: real email, wellbeing data | — | Gmail read-only with a narrow query (its own ADR first). Wellbeing data stays local, never goes to any API, deletable in one click | Nothing yet: each feature lands with its own row here and a test ID |

## What agents may never do

| Never | Enforced by (code) | Test |
|---|---|---|
| Send data out, delete anything, or publish | Tool policy: no `outbound` or `delete` effect without an Accepted ADR (`core/agents/tools.py`); the dispatcher refuses them even on a pass | `test_agent_tools.py::test_forbidden_effects_need_an_exception`, `::test_an_exception_needs_an_accepted_adr`, `::test_names_that_hide_their_effect_are_refused`; `test_capability_pass.py::test_a_forbidden_tool_never_runs_even_on_a_pass` |
| Reach the network, start a process or load native code | Network guard during whole runs (`core/agents/guard.py`) | `test_network_guard.py::test_dns_for_a_host_not_on_the_allowlist_is_refused`, `::test_connecting_to_a_literal_ip_is_refused`, `::test_starting_a_process_is_refused`, `::test_threads_started_in_a_run_are_guarded_too`; `test_runs.py::test_the_whole_run_is_guarded_not_just_tool_calls` |
| Write without my approval, or approve its own write | Writes become pending approvals; approve runs once, with the exact input, never during a run (`core/agents/approvals.py`) | `test_capability_pass.py::test_write_tool_never_runs_inside_a_run`; `test_approvals.py::test_an_agent_cannot_approve`, `::test_a_changed_input_is_refused`, `::test_approve_runs_the_tool_exactly_once`; `test_inbox_triage.py::test_approve_is_refused_while_a_run_is_active` |
| Use another module's tools, or write outside its own module | Capability passes list one module's declared tools (`core/agents/passes.py`); ADR 0011 | `test_capability_pass.py::test_pass_lists_only_its_modules_tools`, `::test_tools_outside_the_pass_are_blocked_and_audited`, `::test_a_pass_a_module_builds_itself_is_rejected_and_audited`; `test_inbox_workflow.py::test_accepting_writes_only_inbox_data` |
| Send unredacted text to a model | The gateway accepts only `Redacted` text (`core/agents/gateway.py`) | `test_gateway.py::test_plain_strings_are_refused_and_audited`, `::test_planted_personal_values_never_reach_the_client` |
| Spend past its budget | Worst case checked before every attempt (`core/agents/gateway.py`, with `ledger.py`) | `test_ledger_budget_retries.py::test_the_worst_case_is_checked_against_the_budget_first`, `::test_a_timeout_can_use_up_the_budget` |
| Keep running after I switch agents off | Kill-switch files, checked before every call; an error counts as off | `test_kill_switches.py::test_switch_works_mid_run_and_can_be_turned_back`, `::test_an_error_while_checking_means_agents_off` |
| Act without a trace | Audit before anything runs (fail closed); keyed hashes, no content; hash chain | `test_capability_pass.py::test_if_the_audit_write_fails_the_tool_does_not_run`; `test_gateway.py::test_if_the_audit_write_fails_nothing_is_sent`; `test_inbox_workflow.py::test_decisions_leave_no_content_or_thresholds_in_core_tables_audit_or_logs`; `test_audit_log.py::test_tampering_is_detected` |

## The web app

| Threat | Enforced by | Test |
|---|---|---|
| Another site posting to the app (CSRF) or reaching it by DNS rebinding | CSRF token + Origin check, Host allow-list (ADR 0005) | `test_application_form.py::test_every_post_route_checks_csrf`, `::test_foreign_or_missing_origin_is_refused`, `::test_unknown_host_is_refused` |
| Script or HTML injected through stored data or an email | Escaped output, strict CSP, `safe_link` for every link | `test_applications_page.py::test_html_in_data_is_escaped`, `::test_safe_link_drops_everything_else`; `test_security_headers.py::test_every_response_has_the_policy`; `e2e/test_safari_checklist.py::test_10_no_csp_violations_or_console_errors` |
| A module reaching into another module | Core and module boundaries (ADR 0007) | `test_module_contract.py::test_imports_no_other_module`; `test_core_boundaries.py::test_core_never_imports_a_module` |
| A workflow that can push or leak | CI is `contents: read`, actions pinned to SHAs, no secrets; secret scanning, push protection, CodeQL, Dependabot | Settings and `.github/workflows/ci.yml`, no test |

## Known gaps (honest limits)
- **No injected-email rogue test yet.** The structure above leaves an injected email no way out, but the end-to-end test (an email asks the agent to send data out) comes with the model judge (PR 6).
- **The model-SDK import check isn't built.** No SDK is installed yet, so nothing can import it. The contract test comes with the SDK (PR 9).
- **Deleting the newest audit rows isn't detected** by the hash chain alone. The daily brief's audit anchor (Phase 3b) closes this.
- **The network guard is Python-level,** not an operating-system sandbox: a compiled extension making raw system calls could slip past.
- **Binding to `127.0.0.1` is a documented command, not code:** nothing stops running the app with `--host 0.0.0.0`. The Host check and CSRF still apply.
- **The CSP template scan is case-sensitive** (CodeQL alert #1): `<SCRIPT>` would slip past `test_templates_have_no_inline_scripts_or_styles`. The live CSP still blocks it; the fix is parked.
- **Personal data in commits** is caught by gitignore and by GitHub for secrets, not by a scan for names or numbers. Reviews check by hand (`.claude/agents/reviewer.md`).

**Keeping this page true:** a change that adds sensitive data, an agent capability or an outside service adds or updates a row here, with the code and test that enforce it. The reviewer checks every change against this page.
