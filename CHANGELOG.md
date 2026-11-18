# Changelog

All notable changes to Brain Dock. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Each line links to the pull request that made the change.

## [Unreleased]

### Added
- Home and the shell: a side rail of modules, a Home of module cards on a 12-column grid (washi-tape labels; calm, empty and needs-attention states), and Settings to show, hide, reorder and resize cards and pick the highlighter of the day, saved in the database. A new look: paper and cream cards, pill buttons, self-hosted Newsreader, Inter, Geist Mono and Kalam, eight module colors checked for contrast, warm stage colors, and a Play brief pill with a dot orb (display-only until playback arrives). The Brief card and page live in the core (ADR 0016).
- Browser tests for the 10-item Safari checklist: Playwright drives WebKit (Safari's engine) against the real app on a throwaway demo database, fails on any CSP violation or console error, and saves one screenshot per item. Runs locally with `uv run pytest e2e` and in CI as the `e2e` job, with the screenshots as an artifact. ([#54](https://github.com/klaudialegu/brain-dock/pull/54))
- THREAT_MODEL.md: one page on what's sensitive, what agents may never do, and the code and test ID that enforce each rule, with its known gaps. A test checks every cited test ID exists, and the reviewer checks every change against the page. ([#55](https://github.com/klaudialegu/brain-dock/pull/55))
- A daily brief as text: each module adds counts and dates through its manifest (`uv run python -m brain_dock.brief`). The first answer to how modules feed the brief (ADR 0013).
- Optional spoken brief: `uv run python -m brain_dock.voice` reads the brief aloud with ElevenLabs text-to-speech. Off by default; only the masked brief text is sent, the key lives in the macOS keychain, mood stays local, and audio is cached so the same brief is never generated twice (ADR 0013).
- The spoken brief becomes the morning brief: a short spoken script with a greeting, today's weather (Open-Meteo, rounded coordinates), today's Runna workout (calendar feed, address in the keychain), job counts and a sign-off. Eleven v3 with a fallback, a 420-character cap and a monthly budget that fits the free plan, `--voices` to list usable voices. The mood question is removed for now (ADR 0014).
- To do, module #3: tasks in Today and Can wait with optional due dates, estimates and ordered steps with their own minutes, on its own page with a simple card. The morning brief counts today's tasks and reads a title only when that task is marked "ok to read aloud" (off by default). A demo set, and the to-do pages in the browser checklist (ADR 0015).

### Security
- opentelemetry-api 1.45.1 → 1.45.2 (a FastAPI dependency; GHSA-mf5v-w3w3-f6cg, a denial of service when parsing `traceparent`). ([#53](https://github.com/klaudialegu/brain-dock/pull/53))

### Changed
- Wide windows: one centered content column that grows to 1600px, with Home's grid and header filling it; checked in the browser at 1440, 1920 and 2560px wide. "Morning show" is now "morning brief" everywhere (the code module is `morning_brief.py`).
- The `e2e` CI job runs inside Microsoft's Playwright image, pinned by tag and digest, so WebKit's system packages aren't installed with apt on every run (a slow Ubuntu mirror stalled that step past the time limit). A test fails if the image's Playwright version and uv.lock's ever differ.
- Brain Dock is described as a modular personal daily-efficiency assistant. The job search module is shown as **Career Radar** (nav, headings, page titles); its code name `job_search` stays (ADR 0012). Planned modules are marked as planned. No behaviour changes. ([#52](https://github.com/klaudialegu/brain-dock/pull/52))

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
