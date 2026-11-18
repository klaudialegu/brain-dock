# 0016. The shell: a rail, a Home of cards, and modules that declare them
**Status:** Accepted
**Date:** 2026-11-18

## Context
Each module had its own pages and a shared text nav, and `/` jumped to the first module. With three modules and more planned (a scratchpad, a brain-break card, a schedule), the app needs one calm place that shows a little of each, and a way to turn modules on and off and reorder them without code. Every module should look the same on that page, so adding one never makes Home noisy.

## Decision
1. **The shell:**
   - **Rail:** a side rail lists Home, then each shown module in layout order (an icon with the module's ink dot), and Settings at the bottom. On narrow screens it becomes a top bar.
   - **Sub-nav:** a module's own links (like "Save a job") are on its pages, in a small sub-nav named after the module.
2. **Home** (`/`) is a 12-column grid of cards:
   - **Sizes:** S = 3, M = 4, L = 5 and W = 8 columns.
   - **Side area:** playful cards (`side`) share a 4-column side area.
   - **Every card is drawn by one partial:** the cream card, a washi-tape label in the card's color, the size, and one of three states.
     - **calm**
     - **empty:** a dot-grid page with one line.
     - **needs attention:** a 2px ring in the card's own ink, with "Needs you". Never red, never blinking.
3. **Modules declare cards in their manifest.**
   - **Manifest fields:** `label`, `color`, `icon`, `cards`, `settings`, `off_by_default` and `capture`.
   - **Each `Card`:** an id, a label, a color, its sizes, a render function that returns a template, context and whether it's empty, an optional `attention` check, and a default rank.
   - A module can have several cards. The layout is saved by card id.
4. **Layout and settings live in the database** (`core_layout`, `core_setting`; ADR 0004).
   - With no saved row, a card uses its manifest's defaults.
   - Settings shows, hides, reorders and resizes cards, and picks the highlighter of the day.
5. **Hiding is soft.** A module whose cards are all hidden leaves Home, the rail and the brief, including the spoken one, so its counts never reach ElevenLabs. Its pages and data stay. `BRAIN_DOCK_MODULES` is still the hard switch that removes routes (ADR 0007).
6. **The Brief card and page are in the core.** The brief needs every shown module's lines, and only the core holds them all (`app.state.modules`). A module importing the registry would break ADR 0007. `brain_dock/brief.py` keeps the command.
7. **The look:**
   - **Colors:** paper `#F8F5EF`, cards `#FFFEFB` with a 1px `#E9E3D8` ring and a 24px radius, ink `#1D1B18`, secondary text `#6B6862`, and pill buttons.
   - **Fonts:** Newsreader Light for big headings, Inter for reading, Geist Mono for times, dates and counts, and Kalam Light only for margin notes and the scratchpad. All four are self-hosted (OFL), with checksums like ECharts. The CSP is unchanged.
   - **Seven module colors** (`core/palette.py`), each with a tint, an ink and a tape-text ink:
     - tape text reads at 4.5:1 or better on its tint;
     - inks read at 3:1 or better on cards and paper (WCAG's level for non-text UI). The butter ink is darker than its tint for that reason.
   - **One light look for now.** A dark palette is parked.
   - **Motion:** `prefers-reduced-motion` turns animation off everywhere.

## Options considered
- **Layout in localStorage:** why not: per browser, invisible to backups, and the database is the source of truth.
- **Hiding a module unmounts its routes:** why not: it needs a restart, and `BRAIN_DOCK_MODULES` already does that.
- **Brief as a module:** why not: it would import every other module's lines through the registry (ADR 0007).
- **Fonts from a font CDN:** why not: the app loads nothing from other sites (ADR 0005's CSP).

## Consequences
- Good: a new module appears on Home, in the rail, in Settings and in the brief by declaring a card. The contract test checks the fields.
- Good: one partial draws every card, so states and styles stay the same everywhere.
- Trade-off: every page reads the layout (two small queries) through an app-wide dependency.
- Trade-off: the stage colors and the pipeline chart lost their dark variants.
- Trade-off: error pages for addresses that don't exist are drawn outside the routes, so their rail lists every enabled module, hidden or not. Hiding is a layout choice, not a privacy control, so this is accepted.
