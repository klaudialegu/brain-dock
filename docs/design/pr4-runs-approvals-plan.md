# Plan: harness PR 4, durable runs, parking and approvals
**Status:** 4a merged (PR #37), real database migrated 2026-10-26. 4b in progress.

Approved 2026-10-26. Design: [agent-harness.md](agent-harness.md), sections 2 and 4. Decision: ADR 0008. Previous: [pr3-gateway-plan.md](pr3-gateway-plan.md).

**Why:** today a run lives only in memory. PR 4 makes it safe to stop at any moment:
- a pending approval survives a restart;
- nothing is dropped silently;
- the same email never makes two suggestions;
- the **whole run** sits inside the network guard, not just each tool call (this closes the PR 3a limit about threads a tool leaves running).

## PR 4a: unknown costs, runs, work items, parking
1. **Ledger: unknown is NULL, 0 means free** (migration `core_0003`).
   - An attempt that got no answer (started, timeout, server error, unexpected error) records its cost as NULL. A `budget_stopped` attempt records 0, because nothing was sent.
   - Old rows are converted.
   - Budget math stays worst-case.
   - Cost per route reports known micro-dollars and the number of attempts with an unknown cost.
2. **Runs and work items** (migration `core_0004`):
   - **`core_agent_run`:** status, budget limit and **spent** (persisted, so a resumed run keeps its spending).
   - **`core_work_item`:** module, idempotency key (unique per module; it must be a hex digest, so it can't be content), state, reason code, attempts.
   - **`core_run_step`:** the flight recorder's storage. Steps are numbered per run, and any detail must be `Redacted`.
3. **`core/agents/runs.py`:**
   - **A `Workflow` each module declares:** allowed state changes, final states (always including `needs_review`), waiting states (like `pending_approval`), and a step function per working state.
   - **`receive`** returns the existing item for a duplicate key. **`advance`** refuses an illegal state change. **`park`** sets `needs_review` and keeps the reason.
   - **The runner** runs the whole run inside `guarded_run`. It turns `NeedsReviewError`, or any step error, into parking (never a silent drop), a budget stop into a `budget_stopped` run, and a kill switch into a `stopped` run whose items wait. **`resume`** continues an interrupted run after a restart, with its spending.
   - **The invariant:** after a run, every item is in a final or waiting state.

## PR 4b: approvals (migration `core_0005`)
0. **Two gaps found while reviewing 4a, closed first:**
   - **Kill switches at the very start of a run, including a resume.** A resumed run checked them before its first item, so nothing ran, but no test covered a resume. `run()` now checks first, before the pass, the gateway or any step. With a switch set, new keys are still recorded as `received` (storing them isn't an agent action, and dropping them would lose work), and then the run stops. With a resume test.
   - **Item keys are keyed hashes**, like the audit log: `key_for()` makes an HMAC with the local audit key, wrapped in an `ItemKey` type (like `Redacted`). `receive()` refuses plain strings, so a module can't use a plain, guessable hash. `test_keys_must_be_hashes_never_content` keeps its 4 IDs; its body changes to "a plain string is refused".
1. **`core_approval`:** item, run, module, tool, the exact tool input (JSON) and its **HMAC**, status, decided time, decided by, reason code.
   - **Policy:** write-tool inputs are ids, not free text (a contract-test check).
2. **A write tool call creates a pending approval** instead of being refused, and the item moves to `pending_approval`.
3. **`approve` / `reject`** are audited as actor "human":
   - **"executing" before the tool runs:** approve marks the approval `executing` and commits that **before** running the tool, then `executed` (or `failed`) after.
   - **Crash safety:** on restart, an approval still `executing` is **parked for review and never rerun**, because the tool may or may not have run.
   - **The exact input that was approved:** before running, approve recomputes the HMAC of the stored input and **refuses to run if it differs** from the HMAC recorded when the approval was created.
   - **Each approval runs at most once:** a second approve is refused. Approve re-checks the kill switch, re-validates the input, and runs the tool inside the guard.
   - **Rejecting** never runs the tool and keeps its reason code.
   - **No agent tool can approve.**
4. **No UI in PR 4.** The PR 5 triage page adds the approve and reject buttons and gets a Safari check.

## Planned test IDs (estimates; each PR lists exact IDs; nothing removed or renamed)
- **4a (~21):**
  - **costs:** unknown cost is NULL and free is 0;
  - **items:** a duplicate key gives the same item; keys must be hashes; an illegal state change is refused; parking keeps its reason;
  - **parking and the invariant:** every item ends final or waiting; step errors park; `NeedsReviewError` parks;
  - **restart:** resume after a restart; no step redone after resume; the budget persists across a restart;
  - **stops:** a budget stop ends the run; a kill switch stops the run and items wait;
  - **guarding:** the whole run is guarded; a thread left by a tool stays guarded for the rest of the run;
  - **recording:** step details must be redacted; core tables hold no content; steps are numbered in order; workflow definitions are checked;
  - **migrations:** `core_0003` marks unknown costs NULL; `core_0004` keeps every row.
- **4b (~16):**
  - **pending:** a write creates a pending approval; it survives a restart and runs after approve;
  - **running once:** approve runs once; **a crash between running and "done" parks the approval on restart and never reruns it**; **a changed input is refused**;
  - **reject and safety:** reject never runs the tool; kill switch re-checked; runs inside the guard; audit actor "human"; an agent can't approve;
  - **policy and migration:** the write-input policy flags free text; `core_0005` keeps every row.

**Every slice:** the test-ID diff, break tests in one final run, and a rehearsal on copies of the real and demo databases, shown **before** the real database is touched. CI logs are read for the PR's current head SHA, and nothing merges without approval.
