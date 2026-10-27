# Agent harness: design
The details behind [ADR 0008](../decisions/0008-agent-harness.md). The ADR records the decision; this file records how it's built, and changes as the PRs land.

**First agent:** inbox triage. It reads synthetic job-alert emails and suggests matching roles (Forward Deployed Engineer, senior support engineering).
**Second agent (later):** a read-only daily brief of real Gmail, in its own phase and ADR.

## 1. LLM gateway (core)
- **The only code that talks to a model.** A contract test fails if any module imports the model SDK. The gateway checks the global and per-module kill switches (ADR 0007) before every call.
- **Three clients behind one interface:**
  - *scripted*: a fake agent follows a script; used for rogue-agent tests;
  - *replay*: answers from recorded responses; the default in tests and CI;
  - *live*: the real API, used only on purpose.
- **Redaction before any call:** the gateway only accepts `Redacted` text, made by one redaction step that removes email addresses, phone numbers, signatures and anything else not needed for the task. Plain strings are refused, so forgetting to redact fails loudly. A test spies on the client and plants personal-looking values; none of them may reach it.
- **Prompt caching:** the stable parts come first (the system prompt, then the tool definitions, frozen and in a fixed order), with a cache breakpoint after them. The email text goes after the breakpoint. Each model has a minimum prefix length below which nothing is cached. The ledger records cache reads and writes, so a prompt too short to cache shows up in the numbers instead of being assumed.
- **Ledger per call:** run, step, module, route, model, prompt version, input/output/cache-read/cache-write tokens, and cost. Cost comes from a dated price table in the repo, never hard-coded in logic.
- **Hard budget stop:** each run has a budget. Before a call, the gateway works out the worst case (input tokens plus `max_tokens` at output price). If that would go over the budget, the call isn't made: the run stops as `budget_stopped` and the stop is audited.
- **The gateway owns retries** (the SDK's own retries are off), so every attempt is ledgered and audited. Timeouts, server errors and malformed output are retried with exponential backoff and jitter, up to a limit; then the item is parked (section 4).
- **Audit log entry per call:** who (run, module), what (model, route, prompt version), outcome and cost. It never stores email bodies, tokens or personal details; payloads are referenced by a keyed hash (section 2, "The audit log").

## 2. Capability passes
- A module's manifest declares its **agent tools**. Each has a name, a schema and an **effect**: `read`, `draft` or `write`.
- Each run gets a **pass** from the core that lists exactly the declared tools of that module (no other module's tools) and the run's budget. A tool call outside the pass is not run: it is blocked, audited, and the agent gets an error result.
- **Only passes the core issued are honored.** The core keeps its own copy of every pass it issues. A pass a module builds itself, or one whose fields were changed after it was issued, is rejected and audited. Like every in-process check, this stops mistakes and honest bugs; code that runs inside the app could still reach anything, which is why the network guard (PR 3) is the guarantee.
- **Fail closed:** every call is audited **before** anything runs. If the audit row can't be written, the tool doesn't run and the run stops.
- **Second line:** even if an `outbound` or `delete` tool reached a pass, the dispatcher won't run it.
- A `write` tool never runs inside an agent run. Calling one creates a **pending approval**. Only the approval route (a CSRF-protected form post by me) runs it. (Until approvals arrive in PR 4, a write is refused and audited.)
- **The audit log** (`core_audit_event`, the core's own migration branch):
  - **No inputs, only keyed hashes:** HMAC-SHA256 of the input with a local key. The key is random, made on first use, kept next to the database (for the real one, in gitignored `data/`), owner-only, and never logged or printed. A plain hash of a short input (a salary, a city) could be guessed by trying values; a keyed hash can't without the key.
  - **Append-only triggers stop bugs:** UPDATE and DELETE on the table are refused by the database. Someone with the database file and a SQL prompt can drop the triggers, so they aren't a defense against tampering.
  - **The hash chain detects tampering:** each row holds the previous row's hash, and its own hash is an HMAC over its fields. `uv run python -m brain_dock.verify_audit` walks the chain and reports where it breaks (positions only, never contents). It detects a row that was changed, removed from the start or middle, or added by anyone without the key.
  - **Honest limits:** removing the *newest* rows leaves a shorter chain that still verifies. The key lives on the same disk as the database, so someone with full access to this machine could rebuild the chain. The chain catches bugs, careless edits and tools that write to the database; it doesn't stop a compromised machine.
- **Outbound tools are forbidden:** no tool that sends email, makes arbitrary web requests, or deletes anything. The contract test fails if a manifest declares a tool with an `outbound` or `delete` effect, unless a core exceptions table lists it with the ADR allowing it, and that ADR is **Accepted** (a Proposed or missing ADR doesn't count).
- **Tool names are a tripwire, not the guarantee.** Tool names must be snake_case, and a name containing a word like `send`, `fetch`, `webhook` or `delete` must declare the matching effect, so a mislabeled tool fails the contract test. A determined or careless author can still pick an innocent name, so this only catches mistakes. **The guarantee is the network guard in the gateway (PR 3):** during agent runs, every connection except the model API fails.
- **Rogue-agent tests** (scripted client); each must be blocked, audited, and leave the data unchanged:
  - calls a tool it didn't declare;
  - calls another module's tool;
  - calls a `write` tool directly (it becomes a pending approval; nothing is written);
  - goes over its budget (the call is never made; the client spy sees no extra call);
  - follows an injected email that asks it to send data out: it tries a send tool, a web request and a delete, and has no way to do any of them (section 6).

## 3. Model routing
- **Deterministic rules decide first, in plain Python:** location, seniority, and salary math against my thresholds from the gitignored local config. A clear "no" never reaches a model: that's route `rules`.
- Otherwise a **cheap model** (`claude-haiku-5-5`) judges fit and returns structured output: label, confidence, reasons and an "injection suspected" flag. The output is checked against a strict schema. Forced tool choice is not used; current models reject it.
- **Confidence is not trusted on its own.** The model's self-reported confidence is only a signal. The escalation threshold is **set from eval results** (the point where cheap-model labels stop matching the expected labels) and is recorded together with the prompt version and model it was measured on. Until live evals exist, the threshold is a **placeholder**, labeled as one in config, in the ledger and in the eval comment.
- Below the threshold, the email goes to a **stronger model** (`claude-sonnet-5-5`): that's route `escalated`.
- The ledger shows **cost per email per route**. Prompt caches belong to one model, so a cascade gives up cache reuse between models. The eval compares the cascade with a single stronger model at low effort, and routing stays config-driven so the cheaper winner can be chosen.

## 4. Agent behavior
- **Read → draft → act:** the agent reads and drafts suggestions; marking a job "interested" is a `write` and waits for my approval in the triage page. Prerequisite: the "interested" stage (PR 0).
- **Rules in code, judgment in the model:** the model never does salary math or location matching, and its output can't carry actions, only a label and reasons.
- **Idempotency:**
  - each email gets a key from its Message-ID (for mock emails, a hash of its normalized headers and body), and each role a key from normalized company, title and link;
  - database uniqueness constraints make "the same email twice" give one suggestion, and "the same role in two emails" give one suggestion with both source emails linked.
- **Persisted workflow state:**
  - each email moves through `received → ruled → judged → pending_approval → approved | rejected`, plus `retrying` and `needs_review`;
  - the state is stored in the database, and every step is safe to repeat;
  - on startup, unfinished work picks up from its last state. A pending approval survives a restart, and approving it afterwards finishes the run (tested with a fresh app instance).
- **Never drop silently:** after the retries run out (timeout, malformed output, refusal), an email is parked as `needs_review` with its reason, on its own page. One invariant is tested: every email that came in ends up suggested, skipped by a rule, rejected, or in `needs_review`.
- **Email is data, never instructions:** email text goes in a clearly marked untrusted block, and the system prompt says so. The real defense is structural: no outbound tools, writes need approval, and the output is a fixed schema.

## 5. Proof
- **Flight recorder:**
  - every run stores its ordered steps: the inputs it saw (redacted), tool calls (allowed or blocked), model, route, tokens, cost, prompt version, decision and reason;
  - it is shown as a timeline page per run;
  - **replay** re-runs a recorded run against its recorded responses and reports any decision that changed.
- **Versioned prompts:** prompts are files with a version in their header, plus a lock file of their hashes. Changing a prompt without bumping its version fails a test. Every eval result and ledger row records the prompt version and the model.
- **Eval set:** 30–50 synthetic emails with expected labels. They include clear fits, clear misses, edge cases for the rules, duplicates, prompt-injection attempts (including one asking the agent to send data somewhere) and failure cases (timeout, malformed output, refusal).
- **CI eval (offline, $0):**
  - scores the eval set from recorded responses, and scores `main` in the same run;
  - posts one updatable PR comment: accuracy, injection catch rate (flagged **and** label unchanged), needs-review rate, and cost per email per route, each compared to `main`. It also says whether the escalation threshold is still a placeholder.
- **CI security for the eval workflow:**
  - it triggers on `pull_request` only, never `pull_request_target`, so code from a PR never runs with the base repository's write token;
  - the **eval job** has read-only permissions (`contents: read`) and **no secrets**. It writes its results as an artifact;
  - a separate **comment job** depends on the eval job and is the only job with `pull-requests: write`. It reads the artifact and posts the comment, and runs no code from the PR. GitHub sets permissions per job, not per step, so this split is what keeps the write permission small;
  - every action is pinned to a full commit SHA (as in ci.yml), and Dependabot keeps the pins current;
  - when the token can't comment (for example, a pull request from a fork), the comment job skips cleanly and the scores stay in the job log.
- **Recorded responses are honest about where they came from:** until there is an API key, they are hand-written and labeled `source: hand-written`. Once the live eval has run, they are labeled `source: recorded` with model and date. The eval comment and the flight recorder show the source.
- **Live eval command:** it refuses to run without credentials, estimates the run's cost first (token counting), and refuses if the estimate would go over the **monthly cap** still left in the ledger.
- **Rejection log (design only):** when I reject a suggestion, the reason, prompt version, model and the agent's reasons are stored. A later, human-gated loop can propose prompt or rule changes as a draft PR. A change merges only with my approval and no eval regression.

## 6. Threat model
**The lethal trifecta:** an agent becomes dangerous when it combines **private data** (my applications, later my real email), **untrusted content** (any email can contain instructions), and **a way to send data out**. Brain Dock keeps the first two by design, so it removes the third:
- **No outbound tools:** no send-email, no arbitrary web requests, no delete. The contract test enforces this for every module, with an Accepted ADR exception as the only way around it. The tool-name check is a tripwire; the network guard is the guarantee.
- **One exit only:** the gateway's call to the model API, carrying redacted, minimal text. The **network guard** (`core/agents/guard.py`, PR 3a) enforces it:
  - It uses Python audit hooks, which are called before every DNS lookup, socket connect, UDP send, process start and `ctypes` library load, and can't be removed once added.
  - While a run is active, in every thread of the process:
    - a lookup of any host not on the run's `host:port` allowlist is refused;
    - a connect is allowed only to an address an allowed host resolves to, on its port, so literal IPs and Unix sockets are refused;
    - UDP sends, process starts (`subprocess`, `os.system`, `exec`, `fork`, `spawn`) and native libraries (`ctypes.dlopen`) are refused.
  - Every refusal is audited, and it stands even if the audit write fails.
  - Tool calls run with an empty allowlist. Only the gateway's model calls (3b) get one, and only for the model API (PR 9).
- **Kill switches** (files next to the database): `data/agents-off` stops every agent, and `data/agents-off-<module>` stops one module. They're checked before every tool call and model call, so they work mid-run. **Fail closed:** if checking fails, agents count as off.
- **Honest limits of the guard:**
  - Audit hooks see Python-level calls, so a compiled extension making raw system calls could slip past.
  - An IP allowlist can't tell two sites on one shared CDN address apart; the DNS check is the main line.
  - A thread a tool leaves running after its call is unguarded once the call ends, until whole runs are guarded (PR 4).
  - This is the strongest guard inside Python, not an operating-system sandbox. A container whose only network is the model API belongs to the Deployment Day phase.
- **No exfiltration through the page:** suggestions are shown as escaped text. Links pass `safe_link` and are never auto-loaded, and the CSP already blocks images and scripts from other sites.
- **Proof:** the injected-email rogue test (section 2) shows the agent has no way to send data out, and that the attempt is audited.

## 7. Second agent: daily Gmail brief
The harness is generic (an agent is a manifest, tools, prompts and a run function), so a read-only daily brief can plug in right after triage. It needs its own ADR (0010, the next free number; 0009 is the interested stage) and an "ask first" (CLAUDE.md privacy rules) before it's built.
- **Access:** metadata first, a body only when needed, with the narrowest Gmail scope that works and a narrow search query. The OAuth token is kept in the keychain.
- **Real email:**
  - never committed;
  - never stored unredacted in the flight recorder;
  - responses recorded from real email stay in gitignored `data/`.
- **Fixture guard:** a test checks that every fixture in the repo uses only reserved domains (`example.com`, `.test`) and is marked synthetic.

## 8. PR plan
PR 3 (gateway and network guard) has its own detailed plan, with a status line: [pr3-gateway-plan.md](pr3-gateway-plan.md).

Every PR merges green without an API key. No test is removed or renamed. Counts are estimates; each PR's plan lists its exact test IDs.

| PR | Scope | Test IDs (planned) |
|---|---|---|
| 0 | "Interested" stage, with a migration (Phase 2 slice) | +~6 |
| 1 | ADR 0008 and this design (docs only) | 283 → 283 |
| 2 | Capability passes, audit log, no-outbound contract test (`[job_search]`) | +~10 |
| 3 | Gateway with the scripted client: redaction spy, ledger math, budget stop, retries with a fake clock, network guard | +~14 |
| 4 | Workflow engine: approval survives a restart, idempotency, needs-review parking, the invariant, rogue "write without approval" | +~12 |
| 5 | Inbox module, rules only, plus triage page and rejection log | +~18, +10 `[inbox]` module tests, +2 per new template |
| 6 | Model judge: versioned prompts, routing with a placeholder threshold, replay client, rogue exfiltration test | +~12 |
| 7 | Flight recorder timeline page and replay command | +~8 |
| 8 | Eval set, offline eval job and comment job (section 5 CI security) | +~6 (the eval itself runs as a CI job) |
| 9 | Live client and live eval command (asks first: model SDK dependency; refuses without a key; monthly cap) | +~6 |
