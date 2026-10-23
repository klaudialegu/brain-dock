# 0001. Stack
**Status:** Accepted
**Date:** 2026-10-19

## Context
Brain Dock is a single-user, local-first app built in small slices that must be visible in the browser. The builder's strongest languages are Python and SQL, so the stack should stay in Python as much as possible, be well documented, and avoid a separate frontend build. Some views need Sankey and funnel charts.

## Decision
Python 3.12 with FastAPI, SQLite via SQLModel, server-rendered Jinja2 templates with HTMX, Apache ECharts for charts, and pytest + ruff for tests and linting.

## Options considered
- Django: full-featured but heavy (admin, ORM, conventions) for a one-user app; more to learn before the first visible slice.
- Flask: simple, but no built-in request validation or typed models; FastAPI gives both through Pydantic.
- React / Next.js frontend: a second language and a build pipeline; HTMX keeps interactivity inside server-rendered HTML.
- PostgreSQL: needs a running server; SQLite is one local file, which fits local-first and is easy to back up or delete.
- Plain SQLAlchemy or raw SQL: possible, but SQLModel reuses the same Pydantic models FastAPI already uses, so less duplicate code.
- Chart.js: lighter, but no built-in Sankey or funnel.
- Plotly: has Sankey, but heavier and mostly built around Python-generated figures.
- unittest, flake8 + black: pytest needs less boilerplate; ruff replaces flake8 and black in one fast tool.

## Consequences
- Good: one language end to end, no frontend build step, data stays in a single local file, and the tools are widely documented.
- Good: Pydantic models are shared between the API and the database.
- Trade-off: SQLite has one writer at a time, which is fine for one user but would need revisiting for multi-user.
- Trade-off: HTMX suits server-driven pages; a very interactive UI later could outgrow it.
- Trade-off: SQLModel is younger than SQLAlchemy; we can drop down to SQLAlchemy (which it is built on) if needed.

## Update 2026-10-22
HTMX hasn't been needed so far: forms are plain HTML posts with a redirect after success, and the one interactive view (the pipeline chart) is a small script reading a JSON block. HTMX is not a dependency; it stays an option if a page needs partial updates later. The rest of this decision stands.
