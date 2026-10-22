# 0006. Companies without applications are removed
**Status:** Accepted
**Date:** 2026-10-21

## Context
Editing an application can change its company. Company names are matched ignoring case and spaces, so "acme analytics" and "Acme Analytics" are one company, and a rename either moves the application to an existing company or creates a new one. That can leave the old company with no applications at all, for example after fixing a typo in its name. Today a company holds nothing but its name.

## Decision
- When an edit moves an application to a different company, and the old company has no applications left, the old company is deleted in the same transaction as the edit (`update_application()` in `models.py`).
- Renaming to a name that matches the current company (ignoring case and spaces) updates that company's spelling instead of creating a new one.
- Renaming one of several applications keeps the company; renaming to an existing company merges into it.

## Options considered
- Keep empty companies: harmless now, but typos would pile up as companies that hold nothing.
- Delete empty companies in a separate cleanup step: two places that change companies instead of one, and a window where the data is inconsistent.

## Consequences
- Good: the tracker never shows a company with nothing in it, and fixing a typo leaves no trace.
- Good: one transaction, so a failed edit leaves both the application and the company as they were.
- Trade-off: deleting is only right while a company has no data of its own.
- **Revisit when companies get their own data (Phase 2: prep folders, notes):** then a company with no applications may still hold prep material and must not be deleted. The same question applies to the parked "delete an application" feature.
