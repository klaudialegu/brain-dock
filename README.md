# Brain Dock

[![CI](https://github.com/klaudialegu/brain-dock/actions/workflows/ci.yml/badge.svg)](https://github.com/klaudialegu/brain-dock/actions/workflows/ci.yml)

**A local-first job-search tracker, built by a support engineer moving into Forward Deployed Engineering.**

Track applications, record each stage, and see your pipeline and response rates. Everything stays on your own machine: no accounts, no cloud, and pages load nothing from other sites.

## Why I built it

<!-- DRAFT for Klaudia to rewrite in her own voice. -->
My job search was spread across spreadsheets, emails and notes, and I wanted one place that showed where everything stood. I also wanted to practise the work I'm moving toward: take a real, fuzzy need, ship it in small verified slices, and own the whole thing end to end, including the security and data-safety parts that a customer would rely on.

## Quick start (demo data)

<!-- quickstart:start -->
```sh
uv sync
uv run python -m brain_dock.importer --demo
BRAIN_DOCK_DB=data/demo.db uv run uvicorn brain_dock.main:app --host 127.0.0.1
```
<!-- quickstart:end -->

Then open http://127.0.0.1:8000. A banner marks the fake demo data. CI runs exactly these commands on a fresh clone (`scripts/check_quickstart.sh`), so this section can't quietly break. You need [uv](https://docs.astral.sh/uv/) (on macOS: `brew install uv`).

## What it does

- **Applications**: add, edit, and record stages (screen, interview, onsite, offer, rejected, ghosted, withdrawn), with each application's stage history.
- **Pipeline**: a Sankey chart of how applications moved from stage to stage. Repeated or backwards steps are left out, so the chart has no loops.
- **Stats**:
  - **Response rate**: applications that got any reply (screen, interview, onsite, offer or rejected) out of those at least 14 days old. Ghosted and withdrawn don't count as replies; newer applications haven't had a fair chance yet.
  - **Interview rate**: applications that reached interview, onsite or offer, out of those at least 14 days old.
  - **Since last application**: days since the most recent applied date.
- **Backups**: one command writes a complete, validated JSON backup.

## Engineering highlights

- **The database is the source of truth**, with Alembic migrations, atomic validated backups (temp file in the same folder, checked with the importer's own parser, then renamed; owner-only), and an importer that won't wipe a non-empty database without a backup first. [ADR 0004](docs/decisions/0004-database-as-source-of-truth.md), [PR #11](https://github.com/klaudialegu/brain-dock/pull/11), [PR #12](https://github.com/klaudialegu/brain-dock/pull/12).
- **Form security on a localhost app**: CSRF (double-submit token, Origin/Referer checks, cross-site requests refused), a host allowlist against DNS rebinding, a strict Content-Security-Policy with no inline scripts or styles, and error messages that never echo typed values. [ADR 0005](docs/decisions/0005-form-security-on-a-localhost-app.md), [PR #14](https://github.com/klaudialegu/brain-dock/pull/14), [PR #15](https://github.com/klaudialegu/brain-dock/pull/15).
- **Tests that prove they work**: every security and data-writing check was confirmed by removing it and watching the tests fail; every commit passes the suite on its own; any warning fails the tests.
- **Supply chain**: Apache ECharts is vendored at a deliberately chosen version with a pinned checksum, GitHub Actions are pinned to commit SHAs with version comments, and Dependabot proposes updates. [PR #16](https://github.com/klaudialegu/brain-dock/pull/16), [PR #18](https://github.com/klaudialegu/brain-dock/pull/18).

## What I decided vs. what Claude built

<!-- DRAFT for Klaudia to rewrite in her own voice. -->
Brain Dock is built with Claude Code as a pair programmer. Claude wrote most of the implementation, the tests, and first drafts of the ADRs and PR descriptions. I set the direction, scope and requirements, and reviewed every change. The decisions that shaped it most:

1. **Making the database the source of truth.** When the add/edit form arrived, a JSON file as the source of truth would have meant edits silently disappearing on the next import. I changed the foundation: migrations, validated atomic backups, and an importer that refuses to wipe data. ([ADR 0004](docs/decisions/0004-database-as-source-of-truth.md))
2. **CSRF hardening beyond the first plan.** Reusing the token so two open tabs both work, accepting both `127.0.0.1` and `localhost`, refusing a post with neither Origin nor Referer, `Cache-Control: no-store` on personal pages, and a strict CSP. ([ADR 0005](docs/decisions/0005-form-security-on-a-localhost-app.md))
3. **Break tests required for security and data-writing code.** No check counts as done until removing it makes a test fail.
4. **Supply-chain choices.** Vendoring instead of a CDN, picking the ECharts version deliberately, pinning actions to SHAs with version comments, and making warnings fail the tests.
5. **A human-in-the-loop improvement loop.** At the end of each session, Claude's mistakes become proposed one-line rules in [CLAUDE.md](CLAUDE.md); I approve, rewrite or reject each one, and it ships with the work. For example: "confirm a check actually ran before reporting it."

The other decisions, with their trade-offs, are in [docs/decisions/](docs/decisions/). Two early commits carry a `Co-Authored-By` trailer and the rest don't; this section is the disclosure for all of them.

## Where it's going (roadmap)

- A modular core, with job search as the first module.
- A daily brief that pulls from every module.
- Evals and guardrails for the AI-assisted parts, so they can be measured and trusted.

## Using your own data

1. Create your database: `uv run python -m brain_dock.db` (in `data/brain_dock.db`, gitignored). Run the same command after pulling changes with new migrations; the app won't start on an out-of-date database.
2. Run the app: `uv run uvicorn brain_dock.main:app --host 127.0.0.1 --reload`. It only listens on this machine.
3. Add applications with **Add application**. The database is the source of truth, so the form is how real data comes in.
4. Back up any time: `uv run python -m brain_dock.export` writes `data/backups/applications-<date>-<time>.json`.

The importer (`uv run python -m brain_dock.importer`) is only for first-time setup from a JSON file in the backup format; it refuses to replace a database that already has applications unless you pass `--force`, which writes a backup first. Open the app at `http://127.0.0.1:8000` or `http://localhost:8000`; other host names are refused on purpose.

## Development

Every push to `main` and every pull request runs CI (`.github/workflows/ci.yml`): `uv sync --locked`, ruff lint and format checks, the tests, and the quick start on a fresh clone.

- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Quick start check: `scripts/check_quickstart.sh`

## How it was built

Small slices, each with a plan, a review and a PR. [CLAUDE.md](CLAUDE.md) holds the working rules, [.claude/skills/](.claude/skills/) the session routines (resume, wrap-up, explain-diff, ADRs), and [docs/decisions/](docs/decisions/) the design decisions.

## License

[MIT](LICENSE)
