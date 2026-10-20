# 0002. uv for Python and dependencies
**Status:** Accepted
**Date:** 2026-10-19

## Context
The project needs a way to pin the Python version, install dependencies into an isolated environment, and get the exact same versions on another machine or in CI. The tool should be simple to learn and fast.

## Decision
Use uv: `pyproject.toml` lists dependencies, `uv.lock` pins exact versions, `.python-version` pins Python 3.12, and every command runs through `uv run`.

## Options considered
- pip + venv: built in, but no lock file by default and separate steps to create and activate the environment.
- Poetry: has a lock file, but slower and its own config conventions; uv covers the same needs with fewer steps.

## Consequences
- Good: one tool for Python version, environment and dependencies; `uv sync` reproduces the setup exactly.
- Good: `uv run` always uses the project's environment, so there's no "forgot to activate the venv" mistake.
- Trade-off: contributors need uv installed; it's a single binary, so the setup cost is small.
