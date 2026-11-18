# 0014. The spoken brief becomes a morning show
**Status:** Accepted
**Date:** 2026-11-17
**Changes:** ADR 0013 points 1, 3, 5, 6 and 7 (listed below); the rest of 0013 stands. Point 2 is extended by [ADR 0015](0015-todo-module.md) (marked to-do titles).

## Context
The spoken brief (ADR 0013) read out a few counts. The goal now is a short, warm script, like a morning radio host, with these sections in order:
1. a greeting
2. the weather
3. today's workout
4. the schedule
5. to-dos
6. job counts
7. a sign-off

Brain Dock has no calendar and no task list yet. Most meetings are repeating events, which a small reader can't count correctly. ElevenLabs' default voices expire on December 31, 2026, and free-plan keys can't use Voice Library voices through the API. The free plan has 10,000 credits a month with no rollover. The API credit rate for Eleven v3 isn't published (only "discounted" from 1 credit per character).

## Decision
1. **The script** (`brain_dock/show.py`): one short spoken sentence per section, with natural connectors and punctuation for rhythm.
   - Each section is optional: a source that is off or failed is left out, with a one-line note on stderr that never holds a URL or a body.
   - This PR has the greeting, weather, workout, job counts (at most 2 lines, from the modules' `brief` lines) and the sign-off.
   - To-dos come with the to-do module, then its UI. Meetings come last, in a schedule slice with a real calendar library.
2. **What the script may hold** (changes ADR 0013 points 1 and 3):
   - the greeting name from `config.toml [voice] greeting_name`, if set
   - weather numbers and a tip
   - the workout's cleaned name (letters, digits and basic punctuation, at most 40 characters), its minutes and its distance
   - job counts

   Never event descriptions, locations, feed URLs or coordinates.
3. **Weather:** Open-Meteo, free with no key.
   - Coordinates come from `config.toml` (a home city is a personal value) and are rounded to 1 decimal (about 10 km). The script never names the city.
   - The forecast is always fetched in Fahrenheit, so the tip rules have one scale; only the spoken numbers are converted for Celsius.
   - It is cached for the morning, then per hour.
4. **Workout:** Runna's iCalendar feed.
   - Its URL is a secret, so it lives in the macOS keychain (`brain-dock-runna-ics`), never in a file, and is never logged.
   - The feed is fetched over HTTPS only, under the network guard with only its own host allowed.
   - Today's events are read in memory and the feed is never stored.
5. **Mood is removed** (changes ADR 0013 point 5): no prompt, normal playback speed. It's parked as a future idea.
6. **Model and cost** (changes ADR 0013 point 6):
   - **Model:** `eleven_v3` by default. If the account can't use it (403 `model_access_denied`, `feature_not_available` or `subscription_required`, or 400 `unsupported_model`), there's one fallback to `eleven_multilingual_v2`. A `model_id` set in config is used as-is.
   - **Voice settings:** only `stability: 0.5` and `similarity_boost: 0.75`, because v3's docs don't confirm the others.
   - **Budget:** the script is capped at 420 characters: 23 weekdays × 420 = 9,660 credits, under 10,000 at the worst-case rate. A local monthly counter stops at 9,800 characters, and the daily limit of 3 attempts stays. A refused request (HTTP 4xx) counts 0 characters, because nothing is generated.
7. **More outside hosts** (changes ADR 0013 point 7):
   - `api.open-meteo.com` and the Runna feed's host join `api.elevenlabs.io`. Each fetch runs under the network guard with only its own host allowed, from the command's process.
   - The keychain lookups start processes, so they happen before any guarded fetch.
   - A `--dry-run` with voice off reaches no network.
8. **Voices:** Sarah (`EXAVITQu4vr4xnSDxMaL`) is the suggested default. `--voices` lists what the key can use. The voice for 2027 is decided by December 15, 2026: a paid plan, an own voice, or macOS `say`.

## Options considered
- **A hand-written reader for meetings too:** why not: repeating events, skipped dates, moved instances and Outlook's Windows time-zone names need a real library. Meetings get their own slice with `icalendar` and `recurring-ical-events`.
- **Building the to-do list in this PR:** why not: it brings a page and a migration. It is its own module next, with all its fields in the first migration (title, due date, done, `ok_to_read_aloud` off by default, `estimate_minutes`, `bucket`, ordered steps with their own minutes).
- **Keeping `eleven_flash_v2_5`:** half the price, but less expressive. v3 fits the "radio host" goal, and the cap keeps it within the free plan.
- **Audio tags like `[warm]`:** they count as billed characters; punctuation and ellipses carry the rhythm instead.
- **api.weather.gov:** US-only, and it asks automated clients for contact details in the User-Agent. Open-Meteo needs nothing.

## Consequences
- Good: one dry run shows the exact script, and a voice-off dry run touches nothing outside the Mac.
- Good: the cost is bounded twice: by length per show, and by a monthly counter.
- Trade-off: the greeting name and the workout's name now go to ElevenLabs, which keeps them by default. The README says so.
- Trade-off: the default voices end on December 31, 2026, so a voice decision is due before then.
