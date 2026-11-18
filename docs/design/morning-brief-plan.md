# Plan: the morning brief, a short spoken script

**Status:** approved by the owner on 2026-11-17 with D1–D3 all A (after one review round, 🟡, fixes applied).

**Order after this PR:**
1. The to-do module.
2. Its UI slice.
3. Meetings, the schedule slice.

**To-do fields, all in the first migration so the UI slice needs no other:** title, due date, done, `ok_to_read_aloud` (off by default), `estimate_minutes`, `bucket` (`today` / `can_wait`), and an optional ordered list of steps, each with its own minutes.

**What:** the voice feature reads a short, warm, conversational script instead of a list of counts. The sections come in this order:
1. greeting
2. weather
3. today's workout
4. schedule
5. to-dos
6. job counts
7. sign-off

The mood question goes away for now.

## Facts from current docs (read 2026-11-17)
- **ElevenLabs:**
  - **The model is `eleven_v3`**, with a limit of 5,000 characters per request. It doesn't support SSML `<break>` tags, so punctuation and ellipses carry the rhythm. Audio tags like `[laughs]` count as billed characters, so the script uses none.
  - **Cost:** the website charges 1 credit per character for v3, and "API generations are discounted". The exact API rate isn't published, so the budget below assumes 1 credit per character, the worst case.
  - **Free plan:** 10,000 credits a month, with no rollover.
  - **When v3 isn't available:** ElevenLabs answers HTTP 403 `model_access_denied`, `feature_not_available` or `subscription_required`, or HTTP 400 `unsupported_model`.
  - **Voice settings for v3:** the docs don't say whether `stability` takes any value or only 0.0/0.5/1.0, or whether v3 accepts `style`, `speed` or `use_speaker_boost`. We send only `stability: 0.5` and `similarity_boost: 0.75`, which is safe either way.
  - **Default voices:** these include Sarah (`EXAVITQu4vr4xnSDxMaL`), Jessica (`cgSgspJ2msm6clMCkdW9`) and Laura (`FGY2WhTYpPnrIDTdsKH5`). They are available only to accounts created before March 2026, and **expire on December 31, 2026**. The docs say Voice Library voices can't be used through the API on the free plan.
- **Open-Meteo:**
  - **Request:** `https://api.open-meteo.com/v1/forecast` takes `latitude`, `longitude`, `current=temperature_2m,precipitation`, `hourly=precipitation_probability`, `daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max`, `temperature_unit`, `timezone=auto` and `forecast_days=1`.
  - **Access:** free with no key, for non-commercial use.
  - **What they keep:** their server logs may hold the coordinates, and are deleted after 90 days.
- **Runna:**
  - **The feed:** the app offers an iCalendar feed under Connected Apps & Devices → Calendars → Other Calendar.
  - **Event types:** an all-day event means a workout with no set time.
  - **Title format:** not documented, so the parser is tolerant and `--dry-run` shows what it found.

## Open decisions
- **D1: the schedule section waits for its own slice (recommended), or is built now with two new dependencies.**
  - Most meetings are repeating events. Counting them right needs repeating rules, skipped dates, moved instances, cancelled events and Outlook's Windows time-zone names. A small hand-written reader would miscount ("no meetings" on a day full of standups).
  - A: this PR ships greeting, weather, workout, jobs and sign-off. A schedule slice follows, using `icalendar` and `recurring-ical-events`, with tests for each of those cases. Only the meeting count and first start time would go into the script.
  - B: add those two dependencies now and build the schedule in this PR. That makes the PR bigger, and the Runna reader would use them too.
- **D3: voices after December 31.** Sarah and the other default voices expire then. Free-plan keys can't use Voice Library voices through the API.
  - A (recommended): build with Sarah as the default, plus `--voices`, which lists the names and IDs your key can actually use (one GET, nothing of yours sent). Decide the 2027 voice by December 15: a paid plan, your own voice, or macOS `say`. NEXT.md gets that date.
  - B: pause the build until you've checked your account's voices.
- **D2: where to-dos come from.** Brain Dock has no task list, so the per-task "ok to read aloud" flag needs one.
  - A (recommended): a second PR right after this one, a small to-do module. Each task has a title, a due date, done, and "ok to read aloud" (off by default), on its own page. That PR gets its own short plan. Until it lands, the show has no to-do section.
  - B: one PR for everything, which is much bigger and includes a UI and a migration.

## Decided by this plan (no need to choose)
- **City:** the coordinates come from `config.toml`, not code, because a home city is a personal value (CLAUDE.md). They are rounded to 1 decimal (about 10 km) before sending. The script never names the city.
- **Name:** `greeting_name` goes in `config.toml [voice]`. When it's set, the name is in the script sent to ElevenLabs, and the README says so. Empty means "Good morning, it's …".
- **What the script sends to ElevenLabs:**
  - your name (if set)
  - the weather numbers and tip
  - the workout name, duration and distance
  - the meeting count and first time (once the schedule slice lands)
  - the to-do count, plus titles only of tasks marked ok to read aloud (PR 2)
  - job counts
- **Nothing else goes in:** no event titles beyond the workout, no feed URLs, no coordinates. Secret shapes are masked, then `redact()` runs, as now.
- **Budget:**
  - The script is capped at 420 characters, so 23 weekdays × 420 = 9,660 credits, under 10,000 even at 1 credit per character.
  - Each section has its own limit:
    - The workout name keeps only letters, digits and basic punctuation, trimmed to 40 characters at a word.
    - Job counts are at most 2 sentences.
  - If the script is still over, the workout detail drops to "a run today". The greeting and sign-off always stay, so the script always fits.
  - A local monthly counter stops sending at 9,800 characters in a calendar month.
  - The daily limit of 3 attempts stays.
  - Weather is cached for the morning, so re-runs before noon produce the same script, hit the audio cache and cost nothing.
- **Model:** the default is `eleven_v3`. On the not-available answers listed above, it falls back once to `eleven_multilingual_v2`, also 1 credit per character. A refused request generates nothing, so it costs no credits. `model_id` in config still overrides the default.
- **Voices to compare:** Sarah `EXAVITQu4vr4xnSDxMaL` (warm, soft), Jessica `cgSgspJ2msm6clMCkdW9` (upbeat, conversational) and Laura `FGY2WhTYpPnrIDTdsKH5`. All three are default voices, so they work until December 31, 2026. Choosing a voice for 2027 goes in NEXT.md.

## Steps (PR 1)
1. **Remove mood:**
   - No prompt and no playback rate.
   - Delete the THREAT_MODEL mood row.
   - ADR 0014 supersedes ADR 0013 point 5.
   - Park the idea in NEXT.md.
2. **`brain_dock/outbound.py`:** `fetch(url, send, guard)` for read-only GETs.
   - HTTPS only; `webcal://` becomes `https://`.
   - The network guard allows only that URL's host on port 443.
   - Errors name the source ("Runna feed", "weather"), never the URL or the response body.
3. **`brain_dock/weather.py`:**
   - The request, a parse into a small `Weather` value, and a spoken sentence.
   - It always asks Open-Meteo for Fahrenheit, so the tip rules have one scale. Only the spoken numbers are converted when `temperature_unit = "celsius"`.
   - Deterministic tips, first match wins:
     - rain ≥ 50% before noon: "grab a hood before noon"
     - rain ≥ 50% later: "keep a hood handy for the afternoon"
     - high ≤ 40°F: "bundle up"
     - high ≥ 85°F: "bring water"
     - otherwise: "a nice one for a walk"
   - Cached for the morning (before noon) in `data/voice_cache/`, owner-only.
4. **`brain_dock/ics.py`:** a small iCalendar reader (standard library only, no new dependency).
   - Handles folded lines, `DTSTART` and `DTEND` as all-day dates, UTC `Z` times or `TZID` times (via `zoneinfo`), plus `SUMMARY` and `DESCRIPTION`.
   - Keeps only today's events, in memory, and never stores the feed.
   - Workout: the name, a duration from the start and end times (or from the text, like "40 min"), and a distance from text like "5 km" or "3.1 mi". No workout today means "rest day".
   - The Runna feed URL comes from the keychain (`brain-dock-runna-ics`). A missing entry skips that section with a one-line note on stderr.
5. **`brain_dock/morning_brief.py`:** the script, one short spoken sentence per section, with natural connectors.
   - Each section is optional: a source that is off or failed just isn't mentioned.
   - Job counts reuse the modules' `brief` lines ("On the job front, …").
   - When over 420 characters, it drops whole sentences in this order: to-do titles (PR 2), then job lines from the end, then the weather tip. The greeting and sign-off always stay.
6. **`voice.py`:**
   - It speaks the script, with the model default and fallback, the v3 settings and the monthly budget.
   - `--dry-run` with voice on fetches weather and the Runna feed (read-only), prints the exact script and its length, and sends nothing to ElevenLabs.
   - With voice off, it reaches no network at all: the script comes from local data only, and it says so.
   - `--voices` lists the names and IDs your key can use (D3 A).
   - Plays at normal speed.
7. **Config and docs:**
   - `config.example.toml [voice]` gets `greeting_name`, `weather_latitude`, `weather_longitude` and `temperature_unit` (fake values).
   - ADR 0014 lists every ADR 0013 point it changes: 1 and 3 (the script now holds a name and a workout title), 5 (mood removed), 6 (model and cap) and 7 (more hosts, each fetched under the guard with only that host allowed).
   - THREAT_MODEL's Known gaps line "the brief is counts and dates only" gets rewritten.
   - THREAT_MODEL rows (Open-Meteo, the two feed URLs, what the script holds; the mood row removed), README, CLAUDE.md and CHANGELOG.
   - NEXT.md parks mood and the 2027 voice choice.

## Test IDs (PR 1)
`uv run pytest`: **615 → 638** (26 added, 3 removed). This assumes D1 A and D3 A. With D1 B, the schedule tests come along: +4 for repeating, skipped, moved and cancelled meetings.

Removed (mood is gone):
- `test_voice.py::test_mood_changes_only_local_playback`
- `test_voice.py::test_mood_is_never_stored_or_logged`
- `test_voice.py::test_mood_is_asked_at_a_prompt_never_a_flag`

Changed, not renamed:
- `test_request_body_is_only_the_masked_brief`: now v3 and its two settings.
- `test_masking_keeps_ordinary_brief_text`: now covers script sentences.

Added, `tests/test_voice.py` (7):
- `test_default_model_is_v3_with_one_fallback_to_multilingual_v2`
- `test_v3_request_sends_only_stability_and_similarity`
- `test_monthly_character_budget_stops_before_the_free_plan_limit`
- `test_brief_asks_nothing_and_plays_at_normal_speed`
- `test_dry_run_prints_the_script_and_sends_nothing_to_elevenlabs`
- `test_dry_run_with_voice_off_reaches_no_network`
- `test_voices_lists_names_and_ids_only`

Added, `tests/test_weather.py` (6):
- `test_weather_request_sends_only_rounded_coordinates_and_units`
- `test_weather_sentence_has_now_high_low_and_rain_chance`
- `test_weather_tips_follow_the_rules` (Fahrenheit and Celsius)
- `test_weather_fetch_runs_under_the_guard_with_only_open_meteo`
- `test_weather_is_cached_for_the_morning`
- `test_weather_failure_skips_the_section_without_details`

Added, `tests/test_ics.py` (7, Runna only with D1 A):
- `test_parses_only_todays_events`: timed, all-day, other days, `TZID`, UTC, folded lines.
- `test_workout_name_duration_and_distance`
- `test_rest_day_when_no_workout_today`
- `test_long_workout_titles_are_trimmed`: a 300-character `SUMMARY`.
- `test_feed_url_comes_from_the_keychain_and_never_shows`: errors, stdout, stderr, logs.
- `test_feed_fetch_runs_under_the_guard_with_only_its_host`
- `test_webcal_urls_are_fetched_over_https_only`

Added, `tests/test_morning_brief.py` (6):
- `test_greeting_uses_the_configured_name_or_none`
- `test_greeting_says_the_day_and_an_ordinal_date`
- `test_sections_come_in_order_and_read_like_speech`
- `test_missing_sources_are_skipped_quietly`
- `test_script_is_capped_by_dropping_the_least_needed_parts`
- `test_script_never_has_event_details_feed_urls_or_coordinates`

All network calls (weather, both feeds, ElevenLabs) use fakes, and the keychain is faked too.

**Found during the build (2026-11-17):**
- **The Runna feed:** a read-only check of the owner's real feed found all-day and floating timed events, with no repeating rules. Titles end with a duration (shaped like "Easy Run 30m"). The first reader took minutes from the description, where the numbers are workout steps (a "5 min" warm-up), so it said "about 5 minutes".
  - Minutes and distance now come only from the event's own times or the end of its title, and the description is never read.
  - `test_ics.py::test_workout_name_duration_and_distance` covers Runna's title shapes.
- **Weather grammar:** "a 88 percent" became "an 88 percent", checked in the sentence test.
- **Tests changed (not renamed) beyond the two above, to fit the new script:**
  - `test_off_by_default_sends_nothing`: no mood prompt.
  - `test_api_key_never_in_output_logs_errors_or_repr`: the new `main()` arguments.
  - `test_same_brief_is_generated_once`: the cache name includes the model.
  - `test_old_cache_files_are_pruned`: usage lines now carry character counts and are kept for the month.
  - `test_text_over_the_cap_is_refused_before_sending`: the cap is 420.
- **Count:** `uv run pytest --collect-only` gives 638, as planned.

`uv run pytest e2e`: 28 → 28.

Break tests, each reverted and recorded in the PR:
- Put the workout's `DESCRIPTION` in the script, and `test_script_never_has_event_details_feed_urls_or_coordinates` fails.
- Skip the coordinate rounding, and `test_weather_request_sends_only_rounded_coordinates_and_units` fails.
- Skip the monthly budget check, and `test_monthly_character_budget_stops_before_the_free_plan_limit` fails.

## PR 2 (D2 A): the to-do module
This gets its own short plan before building, with the fields above. It includes a page, a migration, the new module's contract tests, and its two pages added to the e2e checklist. The rule to test: a title is read aloud only when "ok to read aloud" is on, and that flag is off by default.

## Not in this slice
- Mood (parked).
- Deleting each ElevenLabs generation after download (parked).
- A web play button.
- macOS `say` as a free fallback.
