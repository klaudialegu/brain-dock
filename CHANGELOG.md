# Changelog

All notable changes to Brain Dock. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Each line links to the pull request that made the change.

## [Unreleased]

### Changed
- Brain Dock is described as a modular personal daily-efficiency assistant. The job search module is shown as **Career Radar** (nav, headings, page titles); its code name `job_search` stays (ADR 0012). Planned modules are marked as planned. No behaviour changes.

## [v0.1] - 2026-11-01

First tagged release: the job-search module, the core + modules layout, and the agent harness with its first (rules-only) agent. Local-first; 578 tests.

### Job search
- First running app ([#3](https://github.com/klaudialegu/brain-dock/pull/3)); data model for Company, Application and StageEvent ([#7](https://github.com/klaudialegu/brain-dock/pull/7))
- Import applications from JSON, with a demo dataset ([#9](https://github.com/klaudialegu/brain-dock/pull/9)); read-only applications page ([#10](https://github.com/klaudialegu/brain-dock/pull/10))
- Add-application form with CSRF and host protection ([#14](https://github.com/klaudialegu/brain-dock/pull/14)); edit applications and record stages, strict CSP ([#15](https://github.com/klaudialegu/brain-dock/pull/15))
- Pipeline chart and stats row ([#16](https://github.com/klaudialegu/brain-dock/pull/16)); company page with stage timelines ([#28](https://github.com/klaudialegu/brain-dock/pull/28))
- Saved jobs: "interested" stage ([#30](https://github.com/klaudialegu/brain-dock/pull/30)), saved jobs UI and inbox prefill link ([#46](https://github.com/klaudialegu/brain-dock/pull/46))

### Data safety
- Alembic migrations with a verified baseline ([#11](https://github.com/klaudialegu/brain-dock/pull/11))
- Atomic validated backups and an importer safety lock ([#12](https://github.com/klaudialegu/brain-dock/pull/12))

### Core and modules (ADR 0007)
- Job search becomes a module; shared services move to core ([#24](https://github.com/klaudialegu/brain-dock/pull/24))
- Manifest, registry and module-owned migrations ([#25](https://github.com/klaudialegu/brain-dock/pull/25)); modules-off check ([#26](https://github.com/klaudialegu/brain-dock/pull/26))

### Agent harness (ADR 0008)
- Tool policy ([#32](https://github.com/klaudialegu/brain-dock/pull/32)); capability passes and a hash-chained audit log ([#33](https://github.com/klaudialegu/brain-dock/pull/33))
- Network guard and kill switches ([#34](https://github.com/klaudialegu/brain-dock/pull/34)); LLM gateway with redaction and a scripted client ([#35](https://github.com/klaudialegu/brain-dock/pull/35))
- Ledger, prices, budget and retries ([#36](https://github.com/klaudialegu/brain-dock/pull/36)); durable agent runs and parking ([#37](https://github.com/klaudialegu/brain-dock/pull/37))
- Approvals and run-start kill switches ([#38](https://github.com/klaudialegu/brain-dock/pull/38)); decided approvals move their work item ([#43](https://github.com/klaudialegu/brain-dock/pull/43))

### Inbox (first agent, rules only)
- Inbox module: parser, dedupe, rules ([#44](https://github.com/klaudialegu/brain-dock/pull/44))
- Triage page, review page and rejection log ([#45](https://github.com/klaudialegu/brain-dock/pull/45))

### Code quality and CI
- GitHub Actions for lint, format and tests ([#18](https://github.com/klaudialegu/brain-dock/pull/18)); setup-uv bump ([#41](https://github.com/klaudialegu/brain-dock/pull/41))
- HTML error pages, sync POST routes, one company key ([#20](https://github.com/klaudialegu/brain-dock/pull/20))
- Public-ready: demo works on a fresh clone, MIT license ([#19](https://github.com/klaudialegu/brain-dock/pull/19))

### Removed
- World clocks ([#5](https://github.com/klaudialegu/brain-dock/pull/5)), removed in [#19](https://github.com/klaudialegu/brain-dock/pull/19)

### Docs and working rules
- ADRs, README and usage docs: [#21](https://github.com/klaudialegu/brain-dock/pull/21), [#22](https://github.com/klaudialegu/brain-dock/pull/22), [#23](https://github.com/klaudialegu/brain-dock/pull/23), [#29](https://github.com/klaudialegu/brain-dock/pull/29), [#31](https://github.com/klaudialegu/brain-dock/pull/31), [#42](https://github.com/klaudialegu/brain-dock/pull/42), [#47](https://github.com/klaudialegu/brain-dock/pull/47), [#49](https://github.com/klaudialegu/brain-dock/pull/49), [#50](https://github.com/klaudialegu/brain-dock/pull/50)
- Claude Code rules, skills and the reviewer subagent: [#1](https://github.com/klaudialegu/brain-dock/pull/1), [#2](https://github.com/klaudialegu/brain-dock/pull/2), [#4](https://github.com/klaudialegu/brain-dock/pull/4), [#6](https://github.com/klaudialegu/brain-dock/pull/6), [#8](https://github.com/klaudialegu/brain-dock/pull/8), [#13](https://github.com/klaudialegu/brain-dock/pull/13), [#17](https://github.com/klaudialegu/brain-dock/pull/17), [#27](https://github.com/klaudialegu/brain-dock/pull/27), [#39](https://github.com/klaudialegu/brain-dock/pull/39), [#48](https://github.com/klaudialegu/brain-dock/pull/48)

[v0.1]: https://github.com/klaudialegu/brain-dock/releases/tag/v0.1
