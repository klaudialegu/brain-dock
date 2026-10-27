# Plan: harness PR 3, the LLM gateway and network guard
**Status:** 3a merged (PR #34, 2026-10-26). 3b in review (all 19 break tests caught). 3c not started.

Approved 2026-10-26. Design: [agent-harness.md](agent-harness.md), sections 1 and 6. Decision: ADR 0008.

**Why:** PR 2 controls which *tools* an agent may call. PR 3 controls the only other way out, the model call itself. Every model call goes through one gateway, and while an agent runs, the process can't reach anywhere else. This is the guarantee the tool-name tripwire (PR 2a) points to.

Split into three PRs, each about an hour. Only 3c changes the database. Every PR merges green without an API key.

## PR 3a: network guard and kill switches (no database)
1. **`core/agents/guard.py`, Python audit hooks (PEP 578):** installed once, can't be removed, and only acts while an agent run is active. "Active" is a process-wide counter, so threads a tool starts are covered too while the run lasts.
   - **DNS:** a lookup for any host not on the run's allowlist (`host:port` pairs) is refused.
   - **Connections:** only to an address an allowed host resolves to, on its allowed port. A literal IP, `localhost`, Unix sockets and UDP sends are refused.
   - **Processes:** `subprocess`, `os.system`, `os.exec*`, `os.posix_spawn`, `os.spawn*` and `os.fork` are refused.
   - **Native code:** `ctypes.dlopen` is refused.
   - Every refusal raises `NetworkGuardError` and is audited. If the audit write fails, the refusal still stands.
2. **Kill switches as files:** `data/agents-off` stops every agent, and `data/agents-off-<module>` stops one module. They're checked before every tool call (and every model call from 3b), so they work mid-run without a restart. **Fail closed:** if checking a switch fails, agents are treated as off.
3. **The dispatcher** checks the kill switches first and runs each tool inside the guard.
4. **Honest limits (design doc):**
   - Audit hooks see Python-level calls. A compiled extension making raw system calls could slip past.
   - An IP allowlist can't tell two sites on one shared CDN address apart; the DNS check is the main line.
   - A thread a tool leaves running after its call is no longer guarded, until whole runs are guarded (PR 4).
   - A real sandbox (a container whose only network is the API) belongs to the Deployment Day phase.

## PR 3b: the gateway with a scripted client (no database)
1. `core/agents/gateway.py` is the only code that talks to a model. Its request is our own dataclass, so no SDK is needed yet; the SDK arrives in PR 9.
2. **`Redacted`:** only `redact()` makes it. It strips email addresses, phone numbers, signatures after `-- `, tokens in URL query strings, and extra terms from the caller (personal values come from the gitignored local config in PR 5). The gateway refuses plain `str`.
3. **Cache layout:** the API renders the cached prefix as tools (in a fixed order), then the frozen system prompt. The cache breakpoint closes the system prompt. Untrusted text comes after it, in the messages, inside a marked block it can't close. (Corrected while building 3b: the first version of this plan had system before tools.)
4. **Clients:** `Scripted` (replays scripted responses or errors) and the client interface. Replay comes in PR 6, live in PR 9.
5. **Audit entry per call, written before the call** (fail closed). The kill switches are checked first, and the call runs inside the guard.

## PR 3c: ledger, prices, budget, retries (database change, rehearsed)
1. **`core_llm_call` table:** run, step, module, route, model, prompt version, input/output/cache-read/cache-write tokens, attempt, outcome, and cost in integer micro-dollars.
2. **`core/agents/prices.toml`:** prices per model, each with `verified_on` and `source`. Values not confirmed from the pricing page (Haiku 5.5's cache prices, pricing above 100K tokens) are marked unverified, and the live client (PR 9) refuses unverified prices.
3. **Hard budget stop:** the worst case is `input tokens × input price + max_tokens × output price`. If that would go over budget, the call isn't made: the run stops with "budget_stopped", and the stop is audited.
4. **Retries owned by the gateway:** timeouts, server errors and malformed output get exponential backoff with jitter (injectable clock and sleep). A refusal is never retried. Every attempt is ledgered and audited. When the attempts run out, the gateway raises `NeedsReview`; parking comes in PR 4.
5. **Rehearsal** on copies of the real and demo databases (row checksums, every page compared with `main`), then the real migration with approval.

## Planned test IDs (estimates; each PR lists exact IDs; nothing removed or renamed)
- **3a (~14):**
  - DNS refused for a non-allowed host; literal IP refused; an allowed `host:port` works; another port refused; an allowed host whose address changed still works;
  - Unix socket and UDP send refused; process starts refused; `ctypes.dlopen` refused;
  - threads started in a run are guarded; guard off after a run, even after an exception; refusals audited;
  - a tool that reaches out is refused and audited;
  - kill switches: global, per module, mid-run, and an error while checking means off.
- **3b (~15):**
  - `str` refused; each redaction rule; planted values never reach the client;
  - cache breakpoint placement; audit before the call (audit failure means no call);
  - kill switch blocks the call; a scripted call works inside the guard.
- **3c (~16):**
  - ledger math with cache tokens; unverified prices refused for live use;
  - budget stop before the call; worst-case estimate;
  - retry with backoff on timeout and malformed output; no retry on refusal; `NeedsReview` after the limit;
  - every attempt ledgered; ledger has no prompt text;
  - core migration branch extended; migration keeps every row.
