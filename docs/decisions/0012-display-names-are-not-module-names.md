# 0012. Display names are not module names
**Status:** Accepted
**Date:** 2026-11-01

## Context
Brain Dock is now presented as a modular personal daily-efficiency assistant, and the job search module is shown as "Career Radar" (the job market, skills in demand, interesting roles). The module's code name, `job_search`, is used in many places that hold state or configuration: the package folder, the template prefix (`job_search/...`), the static path, `BRAIN_DOCK_MODULES` values, the module's Alembic migration branch, and the legacy table names ADR 0007 allows. Renaming all of these to match a new display name would be a migration-sized change that alters no behaviour.

## Decision
A module has two names. The **code name** (`job_search`) is stable and is what code, configuration and migrations use. The **display name** ("Career Radar") is wording: nav labels, headings, page titles and docs, and it can change without touching code.

## Options considered
- Rename the package and everything keyed on it to `career_radar`: why not: it touches migration history and users' `BRAIN_DOCK_MODULES` settings, for no behaviour change.
- Add a `display_name` field to the Manifest now: why not: the nav label and templates already carry the wording; add the field when a page needs to list modules by name (for example the daily brief).

## Consequences
- Good: the product can be renamed or repositioned in templates and docs alone; data, migrations and settings are untouched.
- Trade-off: code says `job_search` while the UI says "Career Radar". CLAUDE.md, docs/usage.md and the README name both, so the mapping stays easy to find.
