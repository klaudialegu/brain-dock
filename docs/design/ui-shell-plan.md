# Plan: UI shell, module system, stationery look and dot language

**Status:** approved by the owner on 2026-11-18 with D1–D8 all A (D1 changed: PR 1 waits for a visual check before merging), after one review round (🟡, fixes applied). PR 1 also adds the "Repo wording" section to CLAUDE.md.

**What:** a calm home page and app shell.
- **Rail:** a side rail lists the enabled modules.
- **Cards:** every module shows a card the same way (washi-tape label, size, three states).
- **Look:** a warm stationery look (paper, cards, pill buttons, highlighters) and a small dot language: logo mark, play orb, dot halo, dot meter, dot ring, dotted rules, dot-grid empty pages.
- **New modules:** a scratchpad and a brain-break placeholder.
- **To do:** gains its full card and a focus mode.

**Wording:** the "Repo wording" section in CLAUDE.md (added in PR 1), plus ADR 0012 (code names stay, display names are wording).
- Before each merge, the diff is grepped for the private term list, which is kept locally and never committed. Hits are reported with context.
- Expected and fine: stage names like "applied" or "interview", and the display name "Career Radar".

## Open decisions
- **D1: delivery.**
  - A: five PRs in the order below, approved once here. PR 1 stops before merge for the owner's visual check (screenshots from the demo data, kept locally). PRs 2–5 are merged when review is clean and CI is green, each report with the same local screenshots.
  - B: one PR for everything. It would be very large: fonts, a migration, two new modules, and many templates and scripts.
- **D2: where layout and settings live** (module order, on/off, sizes, the highlighter of the day).
  - A (recommended): in the database, in two small core tables. The database is the source of truth (ADR 0004), so settings survive a browser change.
  - B: in the browser's localStorage. No migration, but per browser and invisible to backups.
- **D3: turning a module off in Settings.**
  - A (recommended): soft. It leaves Home, the rail, the text brief and the morning show (so a hidden module's counts never reach ElevenLabs). Its own pages and data stay. `BRAIN_DOCK_MODULES` remains the hard switch that removes routes (ADR 0007).
  - B: hard. Settings would change the enabled list and need an app restart.
- **D4: Play brief in the browser.**
  - A (recommended): the orb plays today's audio if it was already generated (cached, no credits). When there's none, it says "No brief audio yet" and shows the command. The web server never calls ElevenLabs (ADR 0014 point 7).
  - B: the orb can also generate, by starting the voice command as a separate process. The guard stays per process, and the daily and monthly caps are unchanged. One click can cost up to 420 credits.
- **D5: the display name of `job_search`.** "Job explorer" on the card and "Jobs" in the rail, or "Career Radar" as the repo and README say now (ADR 0012).
  - A (recommended): keep "Career Radar" everywhere. Its tape color is sage.
  - B: show "Job explorer" (card and page) and "Jobs" (rail). This is a wording change in README, CLAUDE.md and the templates; the code name stays.
- **D6: the Follow-ups card.**
  - A (recommended): a second card from Career Radar, built from the follow-up dates applications already have. Ticking one clears that date. No new data.
  - B: a new module with its own items and a new table.
- **D7: scratchpad pens while typing.**
  - A (recommended): one pen per page. The page's text takes the selected pen's style.
  - B: a pen per line or word, which needs a small rich-text editor in the browser.
  - With either: inks are adjusted so typed text reads at 4.5:1 or better on every paper. A light pencil gray would be too faint. The highlighter pen is ink text on a sage swipe. The eraser shows as "for drawing, later" until the ink layer exists.
- **D8: dark mode** (the app has a dark variant today).
  - A (recommended): light only for this slice; a dark version of the stationery palette is parked.
  - B: design a dark variant in this slice.

## The pieces, by PR (D1 A)

### PR 1: shell, look and module system
1. **Fonts:** Inter (400/500/600), Newsreader Light (300, 400), Geist Mono (400/500) and Kalam Light (300), as WOFF2 files.
   - Vendored under `static/vendor/fonts/<family>/`, each with its OFL license.
   - Taken from the pinned `@fontsource` npm packages, and checksummed in `test_vendor.py` like ECharts.
   - No CDN. The CSP stays the same: `default-src 'self'` already covers fonts.
2. **Tokens** in `app.css`:
   - ink `#1D1B18`, secondary `#6B6862`, paper `#F8F5EF`, card `#FFFEFB` with a 1px `#E9E3D8` ring, 24px radius, no shadows;
   - pill buttons 44px tall (primary near-black, secondary cream);
   - Newsreader Light for big headings, Inter for reading, Geist Mono through a `.mono` class for times, dates, counts and IDs;
   - dotted rules; the highlighter swipe (`<mark class="swipe">`, ink on top);
   - `prefers-reduced-motion` respected everywhere.
3. **Palette** (`core/palette.py`): seven named colors, each with a tint, an ink (for dots and rings), and a dark tape-text ink. Values are fixed in the module. A test checks contrast:
   - tape text on its tint is at least 4.5:1;
   - ring and dot inks on the card are at least 3:1 (WCAG's minimum for non-text UI).
   - `/palette.css` is generated from it, like `/stages.css`.
4. **Manifest fields** (`core/modules.py`). The existing fields stay.
   - `label` (display name), `color` (palette name), `icon` (an SVG path), `settings` (an optional page path) and `off_by_default`.
   - `cards`: a tuple of `Card`s. Each has an id, a label, a color, `sizes` and `default_size` (S = 3, M = 4, L = 5, W = 8 columns; W is for To do), `side` (playful cards go in the side area), a render function (returning template, context and state), and an optional `attention` check. A module can have more than one card; Career Radar gets Follow-ups in PR 5 without reshaping anything.
   - `capture`: an optional path that accepts a quick note. Home's quick-capture field and Focus mode's "Park a thought" bar appear only when an enabled module provides one, and they post to that path. So the core never hard-codes a module's URL (ADR 0007), and with the Scratchpad off, neither form shows.
5. **Layout and settings** (D2 A): `core_layout` (card id, position, shown, size) and `core_setting` (key, value; for now only `highlighter`), in one core migration. A module is hidden when all its cards are hidden; that also takes its lines out of the brief (D3 A).
   - Defaults come from the manifests, so a fresh database needs no rows.
6. **Shell** (`base.html`):
   - The rail: the dot-cluster mark, Home, then the enabled modules in layout order, each with its icon and ink dot, then Settings at the bottom. The rail is 44px-target buttons with labels for screen readers.
   - Each page's own heading.
   - Narrow screens get a top bar in place of the rail.
7. **Home** (`/`, no longer a redirect): a 12-column grid of cards in layout order, with the playful modules (`side`) in a 4-column side area.
   - Every card is rendered by one shell partial: the tape label (tint, soft diagonal stripes, tilted 1–3° by position), the size, and one of three states. The states are calm, empty (a dot-grid page with one friendly line), and needs-attention (a 2px ring in the module's ink, never red or blinking).
   - There's a greeting placeholder; the orb and halo come in PR 4.
   - The last tile is "Add module", which links to Settings.
8. **Settings** (`/settings`):
   - Each installed module can be shown or hidden (D3 A), moved up or down, and given a size it supports.
   - The highlighter of the day is chosen from the palette.
   - Plain form posts with CSRF, no scripts.
9. **Existing modules get the new fields and a card:**
   - Career Radar: a sage card with recent applications (D5).
   - Inbox: a card with the number of roles waiting. The inbox's own behavior is untouched.
   - To do: a simple card for now; the full card comes in PR 3.
   - Brief: a core card and page, not a module. A module would need every other module's lines, and importing the registry from a module breaks ADR 0007 and creates an import cycle. The core already holds the enabled manifests (`app.state.modules`), so `build_brief` and its helpers move into `core/brief.py`. `/brief` shows today's text brief, and its card lists the lines. `brain_dock/brief.py` keeps the command, and the voice command stays as it is.
10. **Existing pages:** restyled to the tokens (fonts, cards, buttons). Their structure doesn't change.

### PR 2: Scratchpad module (and quick capture)
1. **Tables:**
   - `scratch_page`: day, position within the day, paper, pen and size.
   - `scratch_layer`: page, kind (`text` now; `ink` later for drawing), position and content. A page is a stack of layers, so a drawing layer can be added later without a migration.
2. **`/scratchpad`:**
   - Day tabs, with "+" for a new page that day.
   - A pen tray: fineliner, gel blue, pencil, brush sepia, rose gel, highlighter, and the eraser shown for later (D7).
   - Paper: blank, lined, squared, dotted or kraft, as CSS backgrounds.
   - Size: card, wide or full.
   - Pen, paper and size are saved per page. Text is typed into a textarea in Kalam Light, using the page's pen ink, and saved with a small script (a POST with the CSRF token) plus a Save button that works without scripts.
   - Pointer events and 44px touch targets throughout; responsive down to 375px.
3. **Quick capture:** a field on Home, and ⌘K / Ctrl+K focuses it from any page. It appends a line to today's top page and creates the page if needed.
4. **Card:** in the side area on Home, showing the last few lines on the page's paper, with "Expand" to the page.
5. **Privacy:** scratchpad text is personal data. It stays local, is never logged, and never reaches the brief. THREAT_MODEL gets a row.

### PR 3: the To do card and Focus mode
1. **The Home To do card (W, 8 columns):**
   - **Today:** each task has a real checkbox (a form post), its title, and a dot meter (one dot per 15 minutes of the estimate, at most 4) with "~45 min · due Fri" in Geist Mono.
   - **Steps:** "Break into steps" opens the steps inline (`<details>`, no script) with an inline add-step form.
   - **Read aloud:** a small speaker toggle (`aria-pressed`, labelled "Ok to read aloud", off by default) sets `ok_to_read_aloud`.
   - **Focus:** a link per task.
   - **Can wait:** a quieter section with the "when" label and "↑ Today".
2. **Focus mode** (`/todo/{id}/focus`):
   - One task, its current step, and a dot-ring timer: one dot per minute. The length is the current step's minutes, else the task's estimate, else 25. Elapsed dots fade, and the current minute glows in the highlighter of the day.
   - Pause/Resume, and "Done, next step" (a post that marks the step done).
   - The step list, and a "Park a thought" bar that posts to `/scratchpad/capture` (a plain URL, so the module boundary holds, like ADR 0011).
   - The timer is a small script; with reduced motion the ring updates without animating.

### PR 4: Brief, the play orb and the greeting
1. **Greeting:** the date in Geist Mono, then "Good morning / afternoon / evening, <name>." The name gets a highlighter swipe in the highlighter of the day.
   - The name is `greeting_name` from config.toml. It shows only when the app runs on the real database (`data/brain_dock.db`). With `data/demo.db`, the browser tests' temp database or any other `BRAIN_DOCK_DB`, there's no name. So screenshots never show one, even from a local browser-test run on a Mac with a real config.toml.
   - Behind it, the dot halo: a static radial dot field fading out, `aria-hidden`.
2. **The play orb:**
   - A real `<button>` labelled "Play brief" or "Pause brief", containing one `aria-hidden` `<canvas>`, in the header. Plain script, no libraries.
   - **Idle:** slow breathing.
   - **Hover:** the dots lean toward the cursor.
   - **Playing:** ripples driven by the audio's loudness (a Web Audio `AnalyserNode` on an `<audio>` element), and the outer dots tint toward the highlighter of the day.
   - **Reduced motion:** no movement; it only changes color when playing.
   - Hidden tab: the drawing loop stops.
   - **Audio** (D4 A):
     - After each successful show, the voice command writes `data/voice_cache/today.json` (owner-only), holding only the date and the audio file's name.
     - `/brief/audio` reads that pointer and serves the file only when the date is today and the name is a bare cache file name (64 hex characters + `.mp3`) inside `data/voice_cache/`, with `Cache-Control: no-store`.
     - The server never rebuilds the script, reads the keychain or touches the network.
     - With no file, the button says "No brief audio yet" and the brief page shows the command.
     - THREAT_MODEL gets a row: the audio holds the greeting name and the workout name, and it's served on 127.0.0.1 only, from that one pointer.
3. **The Brief card:** today's lines, with counts in Geist Mono, and one "In short" line built from the counts by fixed rules (no model).

### PR 5: Follow-ups, Schedule, Brain break, screenshot
1. **Follow-ups card** (D6 A, apricot): follow-up dates due today or overdue, from Career Radar. Ticking one clears that date. It shows the attention ring when one is due today.
2. **Schedule card** (sky): no data source yet (meetings come with the schedule slice), so it always shows the friendly empty state. It's off Home by default until then.
3. **Brain break** (rose): a placeholder card in the side area with one line. No game.
4. **README screenshot:** taken from the e2e demo run (CI has no config.toml, so there's no name). It's cropped, its metadata stripped, and it's checked for real data before committing.
5. **Docs:** README (the look and the modules), CLAUDE.md (the map), CHANGELOG, and THREAT_MODEL (rows in the PRs that add data).
   - ADR 0016 (the shell and module system) lands in PR 1; ADR 0017 (the scratchpad) in PR 2.

## Test IDs (planned; each PR's `--collect-only` diff goes in that PR)
Today 673. Per-module and per-template tests grow on their own (each new template adds 2, each new module 10). Each PR states its exact count.

**PR 1:**
- `test_palette.py::test_tape_text_reads_at_4_5_to_1_on_its_tint`, `::test_ring_and_dot_inks_read_at_3_to_1_on_the_card`, `::test_palette_css_has_every_module_color`
- `test_vendor.py`: the fonts join `VENDORED` (checksum, license, served: 3 per file).
- `test_module_contract.py::test_manifest_declares_shell_fields` (once per module)
- `test_layout.py::test_defaults_come_from_the_manifests`, `::test_order_on_off_and_size_are_saved`, `::test_a_size_the_card_doesnt_support_is_refused`, `::test_hidden_module_keeps_its_page_and_data`, `::test_hidden_module_leaves_the_brief`, `::test_highlighter_of_the_day_is_saved_and_must_be_a_palette_color`
- `test_home.py::test_no_capture_field_when_no_module_captures`
- `test_brief_core.py::test_brief_card_uses_the_apps_modules_not_the_registry`
- `test_home.py::test_home_renders_a_card_per_shown_module_in_order`, `::test_card_states_calm_empty_attention`, `::test_attention_is_a_ring_not_red`, `::test_rail_lists_modules_in_order_with_settings_last`
- `e2e/test_shell.py::test_module_off_and_on_in_settings`, `::test_layout_persists_after_reload`, plus the new pages in the narrow-window and CSP checklist items.

**PR 2:**
- `test_scratchpad.py::test_pages_by_day_and_new_page`, `::test_pen_paper_and_size_are_saved_per_page`, `::test_text_is_a_layer_and_layers_keep_their_order`, `::test_capture_appends_to_todays_page`, `::test_typed_text_never_appears_in_logs`, `::test_pen_inks_read_at_4_5_to_1_on_every_paper`, `::test_scratchpad_never_reaches_the_brief`
- `e2e/test_scratchpad.py::test_paper_switching_is_remembered`, `::test_quick_capture_shortcut_lands_on_the_scratchpad`

**PR 3:**
- `test_todo_card.py::test_dot_meter_is_one_dot_per_15_minutes_max_4`, `::test_speaker_toggle_sets_read_aloud_and_defaults_off`, `::test_focus_timer_length_uses_step_then_estimate_then_25`, `::test_done_next_step_marks_the_step`, `::test_park_a_thought_posts_to_the_capture_path`, `::test_no_park_bar_when_no_module_captures`
- `e2e/test_todo_card.py::test_read_aloud_toggle`, `::test_focus_ring_has_one_dot_per_minute`

**PR 4:**
- `test_brief_core.py::test_audio_is_todays_cached_file_only`, `::test_audio_pointer_outside_the_cache_is_refused`, `::test_voice_writes_the_today_pointer_owner_only`, `::test_no_audio_says_how_to_make_it`, `::test_greeting_name_only_on_the_real_database`, `::test_in_short_line_follows_the_counts`
- `e2e/test_orb.py::test_reduced_motion_keeps_the_orb_still`, `::test_button_label_switches_play_and_pause`, `::test_drawing_stops_when_the_tab_is_hidden`
- `e2e/test_shell.py::test_planted_greeting_name_never_renders_in_browser_tests`: the e2e server reads a temp config with a planted name, and the name must not appear.

**PR 5:**
- `test_follow_ups.py::test_card_lists_due_and_overdue_follow_ups`, `::test_ticking_clears_the_date`, `::test_ring_when_one_is_due_today`
- `test_home.py::test_schedule_is_empty_and_off_by_default`, `::test_brain_break_is_a_placeholder`

**Break tests** (each reverted and recorded in its PR):
- Lower a tape ink's contrast, and the palette test fails.
- Pre-check the speaker toggle, and the read-aloud test fails.
- Keep the orb animating under reduced motion, and the orb test fails.
- Drop the layout save, and the persistence test fails.

## PR 1 as built (2026-11-18)
- **Tests:**
  - `uv run pytest`: 673 → 749. 78 new: 42 font checks, 3 palette, 6 layout, 5 Home, 1 core brief, 3 manifest-field checks, and 16 per-template checks for the 8 new templates.
  - 2 renamed:
    - `test_home.py::test_home_redirects_to_the_pipeline` → `::test_home_is_a_page_of_cards_not_a_redirect`.
    - `test_stages.py::test_css_has_light_and_dark_colors_for_every_stage` → `::test_css_has_a_color_for_every_stage_light_only` (D8 A).
  - `uv run pytest e2e`: 32 → 40. Home, Settings and Brief join items 9 and 10 (6), plus `e2e/test_shell.py` (2).
- **Changed, not renamed:**
  - `test_db.py` and `test_migrations.py` list the two new core tables.
  - `test_applications_page.py`'s nav test finds the rail.
  - `test_home.py` and `test_stages.py` use the `client` fixture, because every page reads the layout.
  - `e2e` item 2 finds "Save a job" in Career Radar's own menu.
  - `scripts/check_quickstart.sh` checks Home at `/` and Career Radar at `/applications`.
- **Found during the build:**
  - The butter ink needed darkening to `#9E7F24` to reach 3:1 on cards.
  - Cards got a default `rank`, so a fresh Home shows To do, then Brief, then Career Radar, then Inbox.
  - The table classes went into their own file (`core/layout_tables.py`) to avoid a circular import with the database module.
  - The inbox card uses sky for now.
- **Not yet in PR 1:**
  - The greeting name and the dot halo (PR 4).
  - Quick capture (PR 2: the Scratchpad declares `capture`).
  - The README screenshot (PR 5).

## Privacy and safety
- The server stays on 127.0.0.1. There are no inbox or email changes.
- Scratchpad text and layout are local. Scratchpad text is never logged, sent, or put into the brief.
- The web server never calls ElevenLabs (D4 A). `/brief/audio` serves only today's cached file, owner-only, with no caching.
- Fonts and scripts are self-hosted, and the CSP is unchanged.
- The README screenshot uses demo data only, with no name.

## Not in this slice
- Drawing (the ink layer).
- The brain-break game.
- Meetings data (the schedule slice).
- A dark palette (D8 A).
- Backups for every module.
- Deleting tasks and pages (the delete/remove slice).
