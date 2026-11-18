# Plan: spoken morning brief (ElevenLabs text-to-speech)

**Status:** approved by Klaudia on 2026-11-17 with D1–D4 all A (after one review round, 🟡, fixes applied). Built on branch `feat/voice-brief`; ADR 0013 records it.

**What:** an opt-in voice feature. One command builds a short brief from existing data and reads it aloud with ElevenLabs text-to-speech. It's off by default and sends nothing until `[voice] enabled = true` and a key are in `config.toml`.

**No daily brief exists yet**, so this slice adds the smallest one: a few counts from data the app already has, built by the modules that own that data. It can be printed and checked for free, without sending anything.

## ElevenLabs facts (from their docs, read 2026-11-17)
- `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128`. The key goes in the `xi-api-key` header. The JSON body is `text`, `model_id` and `voice_settings`, and nothing else is needed.
- `voice_settings`: `stability` (default 0.5), `similarity_boost` (0.75), `style` (0), `use_speaker_boost` (true), `speed` (1.0; 0.7–1.2).
- Model: `eleven_flash_v2_5`, half the price per character of `eleven_multilingual_v2` and `eleven_v4` (about $0.04 per 1,000 characters), 32 languages. It can be changed in config.
- Errors come back as `{"detail": {"type", "code", "message", "request_id", ...}}`: 401 `invalid_api_key`, 402 `insufficient_credits`, 429 `rate_limit_exceeded`.
- **Retention:** ElevenLabs keeps text and audio by default. Zero retention (`enable_logging=false`) is enterprise-only. The README says so plainly.

## Open decisions
- **D1: mood never leaves the Mac (recommended), or mood picks the voice settings.**
  - A: ElevenLabs always gets the same neutral settings. Mood changes only the local playback speed: low 0.9, okay 1.0, good 1.05, with pitch kept. One generation serves every mood.
  - B: as asked. Mood picks what's sent: low is stability 0.75, style 0, speed 0.9; good is stability 0.35, style 0.3, speed 1.05. ElevenLabs keeps requests, so it could read a daily mood level from the settings. CLAUDE.md says wellbeing data is "never sent to any API", so B needs that rule changed. B also needs up to 3 generations per brief.
  - Either way, mood is asked at a prompt after the command starts (1 low, 2 okay, 3 good; Enter means okay). It is never a command-line flag, because zsh saves every command line in `~/.zsh_history`. It is used for this run only, and never stored or logged.
- **D2: key in the macOS keychain (recommended), or in `config.toml` as asked.**
  - CLAUDE.md and THREAT_MODEL.md say secrets live only in `.env` or the keychain.
  - Claude Code is blocked from reading `.env`, but not `config.toml`, and sessions open `config.toml` to debug the inbox. A key there would end up in a transcript after one routine read.
  - A: the keychain, service `brain-dock-elevenlabs`. You add it once with `security add-generic-password -s brain-dock-elevenlabs -a brain-dock -w` and paste the key at its hidden prompt.
    - It's never in a file, never in shell history, and Claude can't see it. This follows the current rule.
    - The command reads it with `security find-generic-password` before the guarded request (the guard blocks starting processes).
    - `config.toml [voice]` keeps only `enabled`, `voice_id` and `model_id`, none of them secret.
  - B: `config.toml`, `[voice] api_key`, as asked.
    - CLAUDE.md and THREAT_MODEL.md get one exception.
    - `.claude/settings.json` gets `Read(./config.toml)` and `Bash(cat config.toml)` deny rules, a settings change you approve.
    - The command refuses if others can read the file.
- **D3: the brief names no companies (recommended), or names them.**
  - A: counts, stages and dates only, for example "2 follow-ups are due today. 1 application is at the interview stage. 3 roles are waiting in the inbox." No company, role, note, link or person ever goes to ElevenLabs.
  - B: names companies and roles ("Follow up with <company> about <role>"). That's more useful, but your job search would then sit in ElevenLabs' retained logs.
- **D4: one PR (recommended, bigger-slice mode), or two.**
  - A: one PR, as planned.
  - B: the text brief first (steps 1–2, 7 tests, no outside service, no rule changes), then the voice feature.

**Decided by approving this plan:** modules feed the brief through their manifests (step 1). That answers ADR 0007's open question ("Decide when the daily brief is built"). ADR 0013 records it, and 0007 gets a pointer.

"Brief" here means this local text brief. The Phase 3b Gmail brief and its audit anchor will be another contributor, not a second brief.

## Steps
1. **A brief contributor per module.** `Manifest` gains `brief: Callable[[Session, date], list[str]] | None = None`, a type only, so the core still imports no module.
   - `job_search/brief.py` gives follow-ups due or overdue, active applications per stage, and the number of saved jobs.
   - `inbox/brief.py` gives the number of roles waiting.
   - Only enabled modules contribute.
2. **`brain_dock/brief.py`** builds the text. It opens with "Good morning. Here's your brief for Tuesday, November 17." and then gives each contributor's lines. If nothing is due, it says so.
   - It is capped at `MAX_BRIEF_CHARS = 600` (about $0.024 per generation at most). Whole lines are dropped past the cap and the brief ends "More in the app."
   - `uv run python -m brain_dock.brief` prints it. Nothing is sent.
3. **`brain_dock/voice.py`, the voice feature:**
   - **Config:** `[voice]` in `config.toml`.
     - Keys: `enabled` (default false), `voice_id`, and `model_id` (default `eleven_flash_v2_5`).
     - The key comes from the keychain (D2 A).
     - Errors name the key, never the value. The config object's repr hides everything.
   - **Masking:** `mask_secrets()` replaces secret-shaped text with `[secret]`. Then the gateway's existing `redact()` removes emails, phone numbers and URL query strings. The secret shapes are:
     - `sk-`/`sk_` keys, `xi-api-key`-style hex, `Bearer` tokens, `password=`/`token=`/`secret=` pairs, `AKIA` keys, `ghp_`/`github_pat_` tokens, and any 32+ character hex or base64 run.
   - **Request:** the body is exactly `{text, model_id, voice_settings}`, where text is the masked brief. The key goes only in the header.
     - It is sent with `urllib` (standard library, no new dependency), inside the existing network guard with only `api.elevenlabs.io:443` allowed.
     - Errors show the HTTP status and ElevenLabs' `code` only. Never the message, the body or the key.
   - **Credits:**
     - Text over the cap is refused before sending.
     - The cache key is a SHA-256 of text + voice + model + settings + format. A cache hit sends nothing.
     - At most 3 send attempts a day. Failed and timed-out attempts count too.
       - The count is kept as timestamps only (no content) in `data/voice_cache/attempts.txt`.
     - Sending happens only from this command's own process, never from the web server. While the guard is active, it blocks approvals and other network calls process-wide.
     - Audio lives in `data/voice_cache/` (gitignored). Files are owner-only and the folder is 0700, and files older than 7 days are pruned.
   - **Playback:** macOS `afplay` runs after the guarded request, never inside it. Mood sets the rate (D1 A).
   - **Command:** `uv run python -m brain_dock.voice [--dry-run]` (it asks for mood at a prompt). `--dry-run` prints the exact text that would be sent and its character count, and sends nothing.
4. **ADR 0013** (a new outside service): what's sent, what's kept and where, the retention fact, and D1–D3.
5. **THREAT_MODEL.md:**
   - New rows for the voice key, the cached audio, and "brief text goes to ElevenLabs only when enabled, masked, counts only".
   - The wellbeing row moves from "Not built yet": mood is asked at a prompt, used for this run only, and never stored, logged or sent.
   - A known gap: ElevenLabs retains requests by default.
   - Each row cites its test IDs.
6. **Docs:**
   - `config.example.toml` gets a `[voice]` section with fake values.
   - README gets a "Spoken brief (optional)" section. It states: "When enabled, the brief text is sent to ElevenLabs, which keeps it by default."
   - CLAUDE.md gets the commands and map entries, and the D2 exception.
   - CHANGELOG.

## Test IDs
`uv run pytest`: **589 → 613**, all new. Nothing is renamed or removed.

`tests/test_brief.py` (7):
- `test_job_search_brief_counts_follow_ups_and_active_stages`
- `test_inbox_brief_counts_waiting_roles`
- `test_brief_never_names_companies_roles_notes_or_links` (D3 A: plants unique names in each field)
- `test_brief_with_nothing_due_says_so`
- `test_brief_is_capped_and_drops_whole_lines`
- `test_brief_uses_only_enabled_modules`
- `test_brief_command_prints_and_sends_nothing`

`tests/test_voice.py` (17):
- `test_off_by_default_sends_nothing`
- `test_request_body_is_only_the_masked_brief`: exact keys, text equals the masked brief, the key only in the header, and the right host, path and `output_format`.
- `test_secret_shaped_text_is_masked`: one planted value per shape.
- `test_masking_keeps_ordinary_brief_text`: dates and counts survive.
- `test_api_key_never_in_output_logs_errors_or_repr`
- `test_config_errors_name_the_key_never_the_value`
- `test_key_is_read_from_the_keychain_before_the_guarded_request` (D2 A)
- `test_same_brief_is_generated_once`
- `test_cache_files_are_owner_only`
- `test_old_cache_files_are_pruned`
- `test_daily_generation_limit`
- `test_text_over_the_cap_is_refused_before_sending`
- `test_api_errors_show_status_and_code_only`: a fake error body that echoes the text and key.
- `test_mood_changes_only_local_playback`: the sent request is identical for all three moods, and the `afplay` rate differs (D1 A).
- `test_mood_is_never_stored_or_logged`
- `test_mood_is_asked_at_a_prompt_never_a_flag`
- `test_request_runs_under_the_network_guard_with_only_elevenlabs_allowed`

Every test uses a fake sender, so none touch the network. The real `urllib` sender is never called in tests: `test_off_by_default_sends_nothing` and the others inject a spy that would fail if the default ran.

**Added during the build: 613 → 614.** One new parameter on an existing test: `test_importer.py::test_personal_data_files_are_gitignored[data/voice_cache/0123abcd.mp3]`. It proves the audio cache is gitignored, for THREAT_MODEL's new row.

**Added after the PR review: 614 → 615.** `test_brief.py::test_current_brief_reads_the_database_and_only_enabled_modules`. It covers the real entry point: a missing database, a migrated one, and `BRAIN_DOCK_MODULES` turning the inbox's line off.

`uv run pytest e2e`: 28 → 28 (no UI in this slice).

Break tests before the PR, each reverted and recorded in the PR:
- Add `config` to the request body, and `test_request_body_is_only_the_masked_brief` fails.
- Drop `mask_secrets` from the send path, and `test_secret_shaped_text_is_masked` fails.
- Skip the cache lookup, and `test_same_brief_is_generated_once` fails.

## Privacy
- What's sent: the masked brief text, the model ID and the voice settings. Nothing else. No config, emails, records, mood or names (D3 A).
- What's kept locally: audio in `data/voice_cache/`, owner-only, pruned after 7 days. Nothing goes into git.
- The key lives only in the keychain (D2 A). It is never printed, logged, put in an error or committed. You paste it in yourself.

## Not in this slice
- A web page with a play button (later: playback in the browser). It needs its own guard design, because the network guard is process-wide.
- Deleting each generation from ElevenLabs' history after download (their API allows it; parked).
- Storing mood, and a brief that adapts its content to mood. That is wellbeing data: its own slice and ADR.
