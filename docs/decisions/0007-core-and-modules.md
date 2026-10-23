# 0007. Core + modules
**Status:** Accepted
**Date:** 2026-10-22

## Context
Brain Dock is one package where everything is job search: `main.py` holds every route, `db.py` imports the job-search models just to register their tables, and the templates assume one feature. The roadmap adds more areas (prep, inbox, a daily brief) and AI-assisted actions. Built the same way, each new area would import the others, share tables loosely, and bolt its own safety checks onto the app. The structure needs a boundary now, while there is only one feature to move.

## Decision
Brain Dock becomes a **core** ("the dock") plus **modules** that can be removed.

**Core services** (each one owned by the core, used by modules):
- **Security**: the existing host allowlist, CSRF, CSP and no-echo error pages, applied to every module's routes and templates.
- **Storage**: one SQLite database and the migration runner. Each module owns its own migrations.
- **Scheduler**: runs the jobs modules declare.
- **Event bus**: the only way modules talk to each other ("something happened" events). How modules feed the daily brief is an open question, below.
- **LLM gateway**: one way to call a model, with per-module budgets, a token ledger, logging without personal data, redaction before anything leaves the machine, and a model chosen per task.
- **Audit log**: a record of every agent action and every approval.
- **Kill switches**: one global and one per module, checked by the gateway, the scheduler and the routes.

**Modules** are plain Python packages under `brain_dock/modules/`, each with a **manifest** that declares:
- its name and description;
- its tables and its migrations folder;
- the permissions it needs (which core services, which events it publishes and subscribes to);
- its routes and nav entries;
- its scheduled jobs;
- later, the MCP tools it offers.

A **registry** lists the modules and which ones are enabled. Nothing else.

**Rules:**
1. **Modules never import each other**, and the core never imports a module. The registry passes manifests to the core. A test fails on any forbidden import.
2. **Each module owns its migrations**, as an Alembic branch of its own. New modules prefix their table names with the module name. **Documented exception:** job search keeps its existing unprefixed table names (`company`, `application`, `stageevent`) and revision `0001`, so existing databases stay at head; the contract test allows exactly these names for job search and nothing else.
3. **Disabling a module never touches its data.** It only hides the module's routes, nav entries and jobs. Only an explicit uninstall drops a module's tables, and only after a backup.
4. **Agent actions go read → draft → act.** Reading and drafting need no approval; acting needs my approval, recorded in the audit log.
5. **No plugin framework**: no entry points, no dynamic loading, no third-party plugin library. Just packages, a manifest and a registry.
6. **Build a core service only when its first real user arrives.** This ADR describes all of them; each one is built when the first module needs it. The LLM gateway, the audit log and the kill switches wait for the AI phase. The event bus waits for a second module.
7. **Every module passes the same contract test**, and CI checks that the core still starts and serves with each module turned off.

## Open questions
- **How do modules feed the daily brief?** Options: (a) request/reply on the event bus; (b) modules declare contributions in their manifest and the brief collects them from enabled modules; (c) the brief builds its own copy of the data from events. Decide when the daily brief is built. Whichever wins must keep working when a module is disabled.

## Options considered
- **Keep one package and add folders**: the least work, but nothing stops one area from importing another, and the AI safety rules would end up repeated in each feature.
- **A plugin framework** (entry points, pluggy, dynamic discovery): built for third parties installing plugins. Here every module is mine and lives in this repo, so it adds magic without a real user.
- **Separate services** per module: real isolation, but processes, ports and network calls for a single-user local app.
- **Modules sharing tables directly**: simpler queries, but removing a module would break the others, which defeats the point.

## Consequences
- Good: a module can be removed or turned off without breaking the rest, and that's tested in CI.
- Good: security, storage and, later, AI safety live in one place, so a new module can't skip them.
- Good: building services only when needed keeps the core small; the ADR stops them from being designed ad hoc later.
- Trade-off: the event bus adds indirection. "Who reacts to this?" is answered by the manifests and the bus, not by following imports.
- Trade-off: keeping a disabled module's data means its tables and migrations stay installed; only uninstall removes them.
- Trade-off: per-module migration branches are more Alembic setup than one linear history.
- Trade-off: modules share one process and one database file. Manifests and permissions are a design contract enforced by tests and review, not a sandbox. That's honest for trusted code of my own, and would need revisiting for third-party modules.
- ADR 0003's data model and ADR 0004's single source of truth still apply; the job-search tables simply move into module #1.
