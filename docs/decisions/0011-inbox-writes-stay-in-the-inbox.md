# 0011. Inbox approvals write only inbox data
**Status:** Accepted
**Date:** 2026-10-31

## Context
The inbox agent (ADR 0008, harness PR 5) suggests roles, and approving one is a `write` that runs through the approval path. A natural approval would save the job in job search as "interested" (ADR 0009). But ADR 0007 says a module never imports another one, and ADR 0008 treats calling another module's tool as a rogue action. So "approve" can't reach into job search directly, and the core has no handoff between modules yet.

## Decision
- **For now (option B):** the inbox's only write tool, `accept_suggestion(suggestion_id: int)`, marks the suggestion `accepted` in the inbox's own table. Nothing is written outside the inbox. I save the job in job search myself.
- **Shaped for a later handoff (option A):** an accepted suggestion keeps its normalized company, title, location and link and a stable id, and `accepted` is a final state. A future handoff would be its own record keyed by suggestion id, with no new inbox workflow state. So option A can be added in its own PR without changing the inbox's workflow or its existing rows.

## Options considered
- **A. A core-brokered handoff:** the inbox offers an accepted suggestion, and the core hands it to job search's own write tool, which waits for its own approval. This is the right long-term shape, but it needs a new core contract (who may offer what to whom, typed payloads, a second approval or a combined one) and its own tests. Too big to fold into PR 5.
- **The inbox writes job search's tables directly:** this breaks ADR 0007's boundary and the rogue-agent rule.
- **No write tool at all, so approve is only a page action:** this skips the approval path (exact input, HMAC, at most once, crash-safe) that PR 4b built for exactly this.

## Consequences
- Good: the first agent uses the full approval path with no cross-module write, and a test proves job search's tables are unchanged by an approval.
- Good: option A stays additive. It adds a handoff record and a core contract, not a migration of inbox rows.
- Trade-off: saving an approved job takes a manual step until option A exists (or until the PR 0b form, prefilled from the suggestion).
