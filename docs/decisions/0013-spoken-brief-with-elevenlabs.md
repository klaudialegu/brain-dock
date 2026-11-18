# 0013. A text brief from module contributions, read aloud by ElevenLabs (opt-in)
**Status:** Accepted; points 1, 3, 5, 6 and 7 changed by [ADR 0014](0014-morning-brief.md) (the morning brief; mood removed)
**Date:** 2026-11-17

## Context
The daily brief is planned to pull from every module. ADR 0007 left open how modules feed it. A voice feature, reading the brief aloud, needs a text-to-speech service.

Brain Dock is local-first, and this is its first outside service that receives data derived from personal records. ElevenLabs keeps the text and audio of API requests by default. Zero retention (`enable_logging=false`) is for enterprise customers only. Text-to-speech is billed per character.

## Decision
1. **Modules feed the brief through their manifests.** This answers ADR 0007's open question with option (b).
   - Each module may set `Manifest.brief`, a function that takes `(session, today)` and returns lines.
   - `brain_dock/brief.py` collects the lines from enabled modules, so a disabled module simply adds nothing.
   - The lines are counts and dates only: never a company, role, note, link or person.
   - The brief is capped at 600 characters. Past the cap, whole lines are dropped and the brief ends "More in the app."
   - The Phase 3b Gmail brief and its audit anchor will be further contributors, not a second brief.
2. **The voice feature is opt-in.** `uv run python -m brain_dock.voice` reads the brief aloud with ElevenLabs. It does nothing until `[voice] enabled = true` and a `voice_id` are in `config.toml`.
3. **Only the masked brief text is sent.**
   - The text has secret shapes masked first, then emails, phone numbers and URL query strings removed by the gateway's `redact()`.
   - The request also carries the model ID and fixed voice settings. Nothing else goes in.
4. **The key lives in the macOS keychain** (service `brain-dock-elevenlabs`), never in a file. It is sent only in the `xi-api-key` header. It is never printed, logged or put in an error.
   - Errors show the HTTP status and ElevenLabs' short code only.
5. **Mood never leaves the Mac.**
   - It's asked at a prompt, never as a flag, so it stays out of shell history.
   - It changes only the local playback speed (`afplay`), and is used for that run only.
   - The voice settings sent are always the same, so the request reveals nothing about mood.
6. **Credits:**
   - Brief text over the cap is refused before sending.
   - Audio is cached by a hash of what was sent, in `data/voice_cache/` (owner-only, pruned after 7 days), so the same brief is never generated twice.
   - At most 3 requests a day, failures included.
   - The model is `eleven_flash_v2_5` (half the price per character), changeable in config.
7. **Sending happens only from the command's own process,** inside the network guard (ADR 0008) with only `api.elevenlabs.io:443` allowed. The keychain lookup and playback start processes, so they run outside the guard. The guard is process-wide, so a play button in the web app will need its own design.

## Options considered
- **Mood picks the voice settings** (calmer and slower on low days): why not: the settings would tell ElevenLabs, which retains requests, a daily mood level. Wellbeing data is never sent to any API.
- **The key in `config.toml` or `.env`:** why not: a file can be read by accident, including by an AI session debugging `config.toml`. The keychain keeps the key out of every file and out of shell history.
- **Name companies and roles in the brief:** why not: the job search would sit in ElevenLabs' retained logs. Counts give the shape of the day without that.
- **macOS `say` (on-device speech):** sends nothing and costs nothing, but the voice quality is lower. It stays a fallback worth adding.
- **Event bus or a brief-owned copy of the data** (ADR 0007's other options): why not: no event bus exists yet, and a copy would need keeping in sync. The manifest field is one line per module.

## Consequences
- Good: the brief can be read and checked for free (`python -m brain_dock.brief`, or `voice --dry-run`) before anything is sent.
- Good: a new module joins the brief by setting one field. Turning it off removes its lines.
- Trade-off: when enabled, the brief text is kept by ElevenLabs under its privacy policy. The text is counts and dates only, and the README says so.
- Trade-off: playback uses macOS `afplay`, so the voice feature is macOS-only for now.
