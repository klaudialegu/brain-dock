# 0017. Scratchpad: pages by day, stored as layers
**Status:** Accepted
**Date:** 2026-11-18

## Context
Quick notes need a home that's faster than a form: one line from anywhere, and a page to write freely on. Typing comes first. Drawing with a pen or pencil may follow later, and it shouldn't need a new data model when it does.

## Decision
1. **A module of its own,** code name `scratchpad`, shown as "Scratchpad" (ADR 0012).
   - Its tables are `scratchpad_page` (day, position within the day, paper, pen, size) and `scratchpad_layer` (page, kind, position, content), in one migration on the module's own branch.
2. **A page is a stack of layers.** Typing writes one `text` layer. A drawing (`ink`) layer can be added on top later, with no migration.
3. **Pages by day.** Today's page is made on the first note, and "New page" adds another for the same day; pen and paper carry over. Tabs list the last seven days that have pages.
4. **One pen per page.** The page's text takes the pen's style.
   - **Pens:** fineliner, gel pen, pencil, brush pen and rose gel, each an ink that reads at 4.5:1 or better on every paper. The highlighter is ink on a sage swipe. The eraser waits for drawing.
   - **Paper:** blank, lined, squared, dotted or kraft.
   - **Sizes:** card, wide or full.
   - Pen, paper and size are saved on the page. The writing is in Kalam Light.
5. **Saving:** the Save button is a plain form post with CSRF (ADR 0005). A small script also saves while typing, posting the same form; it gets a 204 back and no page.
6. **Quick capture:** the manifest's `capture` path (ADR 0016).
   - Home shows a capture field when an enabled module accepts notes. ⌘K or Ctrl+K focuses it, or opens Home with it focused from any other page.
   - A note becomes one line at the end of today's latest page.
   - Where the form returns to (`next`) must be a path on this app, never another site.
7. **Privacy:** scratchpad text is personal data. It stays in the local database and is never logged. It has no `brief` contributor, so it never reaches the brief, the morning brief or any outside service.

## Options considered
- **A pen per line or word:** why not: it needs a rich-text editor in the browser. One pen per page keeps a plain textarea.
- **Text in the page row:** why not: drawing would then need a migration and a second model. Layers hold both.
- **Notes as to-do tasks:** why not: a note isn't a task. Moving a note into To do can come later as an explicit action.

## Consequences
- Good: drawing can be added as a new layer kind, with no migration.
- Good: quick capture works from any page with one shortcut, and goes nowhere when the Scratchpad is off.
- Trade-off: one pen per page means a page can't mix pens yet.
- Trade-off: pages can't be deleted yet (the delete/remove slice), and scratchpad text isn't in `brain_dock.export` yet (backups for every module).
