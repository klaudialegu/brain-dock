# Brain Dock

[![CI](https://github.com/klaudialegu/brain-dock/actions/workflows/ci.yml/badge.svg)](https://github.com/klaudialegu/brain-dock/actions/workflows/ci.yml)

**A local-first job-search tracker, built to production standards: tested, secured, and shipped in small reviewed slices.**

## Quick start (demo data)

<!-- quickstart:start -->
```sh
uv sync
uv run python -m brain_dock.importer --demo
BRAIN_DOCK_DB=data/demo.db uv run uvicorn brain_dock.main:app --host 127.0.0.1
```
<!-- quickstart:end -->

Open http://127.0.0.1:8000. Needs [uv](https://docs.astral.sh/uv/). CI runs these exact commands on a fresh clone.

## Features

- **Applications**: add, edit and record stages, with each application's history.
- **Pipeline**: a Sankey chart of how applications moved through stages.
- **Stats**: response rate, interview rate, days since the last application.
- **Backups**: one command writes a complete, validated JSON backup.
- **Local only**: no accounts, no cloud; pages load nothing from other sites.

## Engineering highlights

- **Database as source of truth**: migrations, atomic validated backups, an importer that won't wipe data. ([ADR 0004](docs/decisions/0004-database-as-source-of-truth.md))
- **Localhost security**: CSRF, DNS-rebinding protection, strict CSP, errors that never echo input. ([ADR 0005](docs/decisions/0005-form-security-on-a-localhost-app.md))
- **Tests that prove themselves**: every security and data-writing check is broken on purpose once to show the tests catch it.
- **Supply chain**: vendored, checksummed chart library; SHA-pinned actions; Dependabot.
- **Agentic workflow**: Claude Code guided by project rules ([CLAUDE.md](CLAUDE.md)), skills, ADRs and CI gates, in small reviewed slices.

## Why I built it

<!-- DRAFT for Klaudia to rewrite in her own voice. -->
I'm a support engineer moving into Forward Deployed Engineering. My job search was spread across spreadsheets, emails and notes, so I built one place for it, and a real project to practice the work I'm moving toward: take a fuzzy need and ship it end to end, in small verified slices.

## Where it's going (roadmap)

- A modular core, with job search as the first module.
- A daily brief that pulls from every module.
- Evals and guardrails for the AI-assisted parts.

## More

- [Using it with your own data, backups, stats](docs/usage.md)
- [Design decisions](docs/decisions/)
- Development: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`, `scripts/check_quickstart.sh`

## License

[MIT](LICENSE)
