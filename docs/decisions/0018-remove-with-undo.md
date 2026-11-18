# 0018. Remove with Undo
**Status:** Accepted
**Date:** 2026-11-18

## Context
To do tasks and Scratchpad pages had no way to be removed, and removing a step deleted it for good. Removing should be as safe as typing: a slip shouldn't lose anything. Messages after an action ("Approved", "Removed") also need a visible way to close, and they shouldn't come back on reload.

## Decision
1. **Remove hides; it doesn't delete.**
   - Tasks, steps and Scratchpad pages get a `removed_at` time (migrations `todo_0002` and `scratchpad_0002`).
   - A removed item stays in the local database. It's out of every list, card, count, tab, quick capture and brief.
2. **Undo, from a one-time message bar.**
   - The next page shows "Removed: *title* · Undo · ×". Undo is a plain form button, so it works with the keyboard and without scripts.
   - The bar stays until × or Esc closes it, or another page loads. It has no timer.
   - Esc inside a text field only leaves the field; a second Esc closes the bar.
3. **The message rides in a short-lived cookie** (`core/flash.py`).
   - The cookie holds a kind and maybe an id, never text; the page looks the title up.
   - The next rendered page clears it, so a reload never repeats it.
   - The Inbox's decision messages use the same bar instead of `?done=` in the address.
4. **Steps:** a removed step leaves the numbering.
   - Its `position` becomes empty, which the unique rule allows, and its old place is kept in `removed_position`.
   - Undo moves later steps down one, highest first, then puts the step back.
   - Every read of a task's steps goes through `live_steps`.
5. **Pages:** a new page's number counts removed pages too, so a number is never reused. Empty pages from earlier days aren't listed as tabs.
6. **A removed item refuses changes, never with a bare 404.** This covers a page left open in another tab, the Back button, or an old link.
   - The item answers 410 with "This … was removed", Undo, and anything just typed shown so it isn't lost.
   - Undo on an item that isn't removed changes nothing (409).
7. **Downgrades refuse while anything is removed.** Going back would fail part-way, or quietly bring removed items back.

## Options considered
- **A confirm step, then delete:** why not: one wrong click still loses the item, and a confirm dialog is easy to click through.
- **Messages in the address (`?done=`):** why not: they repeat on every reload and end up in bookmarks.
- **A timer that hides the bar:** why not: someone reading slowly loses the Undo.

## Consequences
- Good: nothing is lost by a click; Undo is one keypress away.
- Trade-off: removed isn't erased. Removed text stays on disk until permanent delete. Once the bar is closed, it can't be restored from the app. "Recently removed / restore" and permanent delete come with the delete/remove slice.
- Trade-off: To do and Scratchpad aren't in `brain_dock.export` yet, so copy `data/brain_dock.db` before running these migrations.
