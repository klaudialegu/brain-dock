# 0008. Agent harness
**Status:** Accepted
**Date:** 2026-10-26

## Context
Brain Dock's first agent triages job-alert emails and suggests roles that fit. ADR 0007 reserved the core services an agent needs (LLM gateway, audit log, kill switches, read → draft → act) and said to build each one when its first real user arrives. This is that user. An agent that only works isn't enough: the harness has to prove what it did (cost, allowed and blocked actions, decisions, quality). It also has to work before there is an API key, and cost $0 in CI.

## Decision
Build an **agent harness in the core**, then an **inbox triage module** on synthetic emails as its first user. The details are in [docs/design/agent-harness.md](../design/agent-harness.md).
- **LLM gateway:** the only code that talks to a model. It accepts only redacted text, caches the stable prompt prefix, keeps a ledger of tokens and cost per call, stops a run before it goes over budget, owns retries, and writes an audit entry per call.
- **Capability passes:** each run may use only the tools its module declared. Anything else is blocked and audited. Writes become approvals that only I can grant.
- **Rules first, model second:** location, seniority and salary math are plain code. A cheap model judges fit, and a stronger one gets only low-confidence cases. The threshold comes from eval results, not from the model's own confidence alone.
- **Reliable by construction:** idempotent suggestions, workflow state that survives a restart, and retries with backoff, then "needs review". Nothing is dropped silently.
- **Proof:** a flight recorder with a timeline and replay; versioned prompts; an eval set scored offline in CI with a PR comment comparing it to `main`; a live eval that needs a key and respects a monthly cap.

## Threat model (summary)
The **lethal trifecta** is private data plus untrusted content plus a way to send data out. Brain Dock keeps the first two by design (my applications; emails anyone can write), so it removes the third:
- **No outbound tools:** no send-email, no arbitrary web requests, no delete. The contract test fails on any module that declares one without an explicit ADR exception.
- **One exit only:** the model API call, carrying redacted, minimal text. Tests block every other network connection during agent runs.
- **No leaks through the page:** suggestions are shown as escaped text, and the CSP blocks images and scripts from other sites.
- **Email is data, never instructions.** A rogue-agent test feeds an injected "send everything to…" email and shows the agent has no way to send data out.

## Options considered
- **An agent framework:** hides the loop this project exists to show, and would still need wrapping to enforce passes, budgets and approvals.
- **Hosted, server-managed agents:** run the loop and tools off this machine, which breaks the local-first rule.
- **Rules only:** can't judge fit from free text. Rules still decide the clear cases.
- **One strong model for everything:** stays in the running. The eval decides between it and the cascade.
- **Defending against injection with the prompt alone:** necessary but not enough. Safety comes from structure.

## Consequences
- Good: every claim about the agent (cost, safety, quality) is backed by a test, a ledger row or an eval number, checked on every PR for $0.
- Good: the second agent (a read-only Gmail brief, its own phase and ADR) reuses the harness.
- Trade-off: much more machinery than a script calling an API, built in ten small PRs before the agent is useful.
- Trade-off: until there is an API key, evals score hand-written responses, which proves the harness, not the model's quality; the escalation threshold stays a labeled placeholder.
- Trade-off: a new dependency (the model SDK) arrives in its own PR, asked for first.
