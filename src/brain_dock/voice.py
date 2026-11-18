"""The morning brief (ADR 0014, building on ADR 0013): a short spoken script, read aloud with
ElevenLabs text-to-speech.

Off by default. When `[voice] enabled = true` is in config.toml:
- Only the final script is sent: it's masked first (anything secret-shaped, then the
  gateway's redact()), along with the model ID and two fixed voice settings.
- The API key comes from the macOS keychain, never a file. It's sent only in the request
  header, and never printed, logged or put in an error.
- Credits: the script is capped (morning_brief.MAX_SCRIPT_CHARS), audio is cached by content, at
  most MAX_ATTEMPTS_PER_DAY requests go out a day, and a local monthly counter stops at
  MONTHLY_CHAR_BUDGET characters (the free plan has 10,000 credits a month).
- The model is Eleven v3; if the account can't use it, one fallback to Multilingual v2.
- Each request runs inside the network guard with only its own host allowed, from this
  command's process, never the web server (the guard is process-wide).

Run: `uv run python -m brain_dock.voice`. `--dry-run` prints the exact script and sends
nothing to ElevenLabs; `--voices` lists the voices your key can use.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from brain_dock.core.agents.guard import guarded_run
from brain_dock.core.db import REPO_ROOT
from brain_dock.core.masking import scrub
from brain_dock.morning_brief import MAX_SCRIPT_CHARS, build_script, gather
from brain_dock.outbound import (
    FetchError,
    RefusedError,
    fetch,
    keychain_secret,
    private_dir,
    write_private,
)

CONFIG_PATH = REPO_ROOT / "config.toml"
CACHE_DIR = REPO_ROOT / "data" / "voice_cache"  # gitignored (data/)
API_HOST = "api.elevenlabs.io"
VOICES_URL = f"https://{API_HOST}/v2/voices?page_size=100"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MODEL = "eleven_v3"
FALLBACK_MODEL = "eleven_multilingual_v2"
# ElevenLabs' answers when an account can't use a model (their errors page, 2026-11-17).
MODEL_UNAVAILABLE = {
    (403, "model_access_denied"),
    (403, "feature_not_available"),
    (403, "subscription_required"),
    (400, "unsupported_model"),
}
KEYCHAIN_SERVICE = "brain-dock-elevenlabs"
KEYCHAIN_ACCOUNT = "brain-dock"
MAX_ATTEMPTS_PER_DAY = 3  # failed and timed-out attempts count too
MONTHLY_CHAR_BUDGET = 9_800  # under the free plan's 10,000 credits, at 1 credit a character
KEEP_DAYS = 7
TIMEOUT_SECONDS = 30

# The two settings every model accepts; v3's docs don't confirm style, speed or speaker
# boost, so they aren't sent.
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75}

ID = re.compile(r"[A-Za-z0-9_]{1,64}")
NAME = re.compile(r"[^\W\d_](?:[^\W\d_]|[ '.-]){0,39}")
ERROR_CODE = re.compile(r"[a-z_]{1,40}")
UNITS = ("fahrenheit", "celsius")


class VoiceError(RuntimeError):
    """The morning brief can't be spoken. Messages name keys and codes, never values or text."""


class VoiceRefused(VoiceError):
    """ElevenLabs answered with an HTTP error (nothing was generated)."""

    def __init__(self, status: int, code: str):
        super().__init__(f"ElevenLabs refused the request: HTTP {status} ({code})")
        self.status, self.code = status, code


@dataclass(frozen=True, repr=False)  # no repr: keep config out of any log line
class VoiceConfig:
    enabled: bool
    voice_id: str = ""
    model_id: str = DEFAULT_MODEL
    model_fixed: bool = False  # model_id set in config: no fallback
    greeting_name: str = ""
    coordinates: tuple[float, float] | None = None
    temperature_unit: str = "fahrenheit"

    def __repr__(self) -> str:
        return "VoiceConfig(<hidden>)"


def _number(section: dict, key: str, low: float, high: float) -> float:
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise VoiceError(f"voice.{key} must be a number from {low:g} to {high:g}")
    return float(value)


def load_config(path: Path = CONFIG_PATH) -> VoiceConfig:
    """[voice] from config.toml. No file, no section or no `enabled = true` means off."""
    if not path.is_file():
        return VoiceConfig(enabled=False)
    try:
        raw = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        raise VoiceError(f"{path.name} isn't valid TOML") from None  # no excerpt of it
    section = raw.get("voice", {})
    if not isinstance(section, dict):
        raise VoiceError("voice must be a [voice] section")
    if "api_key" in section:
        raise VoiceError(
            "voice.api_key isn't read from config.toml: remove it, the key "
            "belongs in the keychain (see README)"
        )
    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise VoiceError("voice.enabled must be true or false")

    name = section.get("greeting_name", "")
    if not isinstance(name, str) or (name.strip() and not NAME.fullmatch(name.strip())):
        raise VoiceError("voice.greeting_name must be a short name (letters, up to 40)")
    has = [k in section for k in ("weather_latitude", "weather_longitude")]
    if any(has) and not all(has):
        raise VoiceError("voice.weather_latitude and voice.weather_longitude go together")
    coordinates = None
    if all(has):
        coordinates = (
            _number(section, "weather_latitude", -90, 90),
            _number(section, "weather_longitude", -180, 180),
        )
    unit = section.get("temperature_unit", "fahrenheit")
    if unit not in UNITS:
        raise VoiceError("voice.temperature_unit must be fahrenheit or celsius")
    shared = {"greeting_name": name.strip(), "coordinates": coordinates, "temperature_unit": unit}
    if not enabled:
        return VoiceConfig(enabled=False, **shared)

    voice_id = section.get("voice_id")
    if not isinstance(voice_id, str) or not ID.fullmatch(voice_id):
        raise VoiceError("voice.voice_id must be an ElevenLabs voice ID (letters and digits)")
    model_id = section.get("model_id", DEFAULT_MODEL)
    if not isinstance(model_id, str) or not ID.fullmatch(model_id):
        raise VoiceError("voice.model_id must be an ElevenLabs model ID, like eleven_v3")
    return VoiceConfig(
        enabled=True,
        voice_id=voice_id,
        model_id=model_id,
        model_fixed="model_id" in section,
        **shared,
    )


def prepare_text(script: str) -> str:
    """What may leave this machine: secret shapes masked, then emails, phone numbers and
    URL query strings removed (core.masking.scrub). The free-text parts were already
    scrubbed before they were cleaned and trimmed; this pass covers the whole script."""
    return scrub(script)


def keychain_key(run: Callable = subprocess.run) -> str:
    """The ElevenLabs key from the macOS keychain. Starts a process: call it before the
    guard."""
    key = keychain_secret(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, run=run)
    if not key:  # never show the tool's own output
        raise VoiceError(
            f"No ElevenLabs key in the keychain (service {KEYCHAIN_SERVICE}). Add it with: "
            f"security add-generic-password -s {KEYCHAIN_SERVICE} -a {KEYCHAIN_ACCOUNT} -w"
        )
    return key


def request_body(text: str, model_id: str) -> dict:
    """Everything that's sent besides the key header: nothing else ever goes in."""
    return {"text": text, "model_id": model_id, "voice_settings": VOICE_SETTINGS}


def build_request(
    text: str, config: VoiceConfig, api_key: str, model_id: str
) -> urllib.request.Request:
    url = (
        f"https://{API_HOST}/v1/text-to-speech/{quote(config.voice_id, safe='')}"
        f"?output_format={OUTPUT_FORMAT}"
    )
    return urllib.request.Request(
        url,
        data=json.dumps(request_body(text, model_id)).encode(),
        method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )


def default_send(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def error_code(body: bytes) -> str:
    """ElevenLabs' short error code (like invalid_api_key), never its message or body."""
    try:
        detail = json.loads(body or b"{}").get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
    except (ValueError, AttributeError):
        code = None
    return code if isinstance(code, str) and ERROR_CODE.fullmatch(code) else "no code"


def send_guarded(send: Callable, request, guard: Callable[..., AbstractContextManager]) -> bytes:
    failure: VoiceError
    try:
        with guard(allow=[(API_HOST, 443)]):
            return send(request)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except OSError:
            body = b""
        failure = VoiceRefused(e.code, error_code(body))
    except (urllib.error.URLError, TimeoutError, OSError):
        failure = VoiceError("Couldn't reach ElevenLabs")
    raise failure  # raised outside the except: no chained error with the request


def cache_name(text: str, config: VoiceConfig, model_id: str) -> str:
    """Same text, voice, model, settings and format: same file, so it's generated once."""
    fields = {
        "text": text,
        "voice_id": config.voice_id,
        "model_id": model_id,
        "settings": VOICE_SETTINGS,
        "format": OUTPUT_FORMAT,
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest() + ".mp3"


def prepare_cache(cache_dir: Path, now: datetime) -> None:
    """Owner-only folder; audio older than KEEP_DAYS is deleted."""
    private_dir(cache_dir)
    cutoff = (now - timedelta(days=KEEP_DAYS)).timestamp()
    for audio in cache_dir.glob("*.mp3"):
        if audio.stat().st_mtime < cutoff:
            audio.unlink()


# --- Usage: one line per request, "<timestamp> <characters>", no content -------------------


def _usage(cache_dir: Path) -> list[tuple[str, int]]:
    path = cache_dir / "attempts.txt"
    rows = []
    for line in path.read_text().splitlines() if path.exists() else []:
        stamp, _, chars = line.partition(" ")
        if stamp:  # a line from before characters were counted: assume the most
            rows.append((stamp, int(chars) if chars.isdigit() else MAX_SCRIPT_CHARS))
    return rows


def _write_usage(cache_dir: Path, rows: list[tuple[str, int]]) -> None:
    text = "".join(f"{stamp} {chars}\n" for stamp, chars in rows)
    write_private(cache_dir / "attempts.txt", text.encode())


def attempts_today(cache_dir: Path, now: datetime) -> int:
    return sum(1 for stamp, _ in _usage(cache_dir) if stamp.startswith(now.date().isoformat()))


def characters_this_month(cache_dir: Path, now: datetime) -> int:
    return sum(chars for stamp, chars in _usage(cache_dir) if stamp.startswith(f"{now:%Y-%m}"))


def record_attempt(cache_dir: Path, now: datetime, chars: int) -> None:
    """Kept for this month and the last KEEP_DAYS days; counted before sending, so a
    timeout still counts."""
    cutoff = min(now.replace(day=1), now - timedelta(days=KEEP_DAYS)).date().isoformat()
    rows = [r for r in _usage(cache_dir) if r[0][:10] >= cutoff]
    _write_usage(cache_dir, [*rows, (now.isoformat(timespec="seconds"), chars)])


def nothing_generated(cache_dir: Path) -> None:
    """ElevenLabs refused the last request (HTTP 4xx): no audio, no credits used."""
    rows = _usage(cache_dir)
    if rows:
        _write_usage(cache_dir, [*rows[:-1], (rows[-1][0], 0)])


def speak(
    script: str,
    config: VoiceConfig,
    *,
    now: datetime,
    cache_dir: Path = CACHE_DIR,
    get_key: Callable[[], str] = keychain_key,
    send: Callable = default_send,
    guard: Callable[..., AbstractContextManager] = guarded_run,
    note: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> Path:
    """The audio file for this script: from the cache, or generated once."""
    if not config.enabled:
        raise VoiceError("Voice is off: set enabled = true under [voice] in config.toml")
    text = prepare_text(script)
    if len(text) > MAX_SCRIPT_CHARS:
        raise VoiceError(f"The script is over {MAX_SCRIPT_CHARS} characters; nothing was sent")
    prepare_cache(cache_dir, now)
    models = [config.model_id]
    if not config.model_fixed and config.model_id != FALLBACK_MODEL:
        models.append(FALLBACK_MODEL)
    for model in models:
        if (cached := cache_dir / cache_name(text, config, model)).exists():
            return cached

    api_key = None
    for i, model in enumerate(models):
        if attempts_today(cache_dir, now) >= MAX_ATTEMPTS_PER_DAY:
            raise VoiceError(f"Already {MAX_ATTEMPTS_PER_DAY} requests today; nothing was sent")
        if characters_this_month(cache_dir, now) + len(text) > MONTHLY_CHAR_BUDGET:
            raise VoiceError(
                f"This month's budget of {MONTHLY_CHAR_BUDGET:,} characters is used up; "
                "nothing was sent"
            )
        api_key = api_key or get_key()  # the keychain lookup, before the guard
        request = build_request(text, config, api_key, model)
        record_attempt(cache_dir, now, len(text))  # before sending: a failure still counts
        try:
            audio = send_guarded(send, request, guard)
        except VoiceRefused as refused:
            nothing_generated(cache_dir)
            if (refused.status, refused.code) in MODEL_UNAVAILABLE and i + 1 < len(models):
                note(
                    f"{model} isn't available on this account ({refused.code}); trying "
                    f'{models[i + 1]}. Set model_id = "{models[i + 1]}" under [voice] to skip '
                    "the first try."
                )
                continue
            raise
        if not audio:
            raise VoiceError("ElevenLabs sent back no audio")
        path = cache_dir / cache_name(text, config, model)
        write_private(path, audio)
        return path
    raise VoiceError("No model could be used")  # not reached: the loop returns or raises


def list_voices(
    get_key: Callable[[], str] = keychain_key, fetch_fn: Callable[..., bytes] = fetch
) -> list[str]:
    """Name, ID and category of each voice this key can use. Nothing of yours is sent."""
    key = get_key()
    try:
        answer = fetch_fn(VOICES_URL, "ElevenLabs voice list", headers={"xi-api-key": key})
    except RefusedError as refused:
        raise VoiceRefused(refused.status, error_code(refused.body)) from None
    except FetchError as failed:
        raise VoiceError(str(failed)) from None
    try:
        voices = json.loads(answer)["voices"]
        rows = [
            (str(v["name"])[:60], str(v["voice_id"]), str(v.get("category", ""))[:20])
            for v in voices
        ]
    except (ValueError, KeyError, TypeError):
        raise VoiceError("ElevenLabs sent a voice list this can't read") from None
    return [f"{name}  {voice_id}  ({category})" for name, voice_id, category in rows]


def play(path: Path, run: Callable = subprocess.run) -> None:
    """macOS afplay at normal speed, after the guarded request (the guard blocks
    processes)."""
    run(["afplay", str(path)], check=False)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m brain_dock.voice", description="Read this morning's brief aloud."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact script; send nothing to ElevenLabs",
    )
    p.add_argument(
        "--voices", action="store_true", help="list the voices your ElevenLabs key can use"
    )
    return p


def main(
    argv: list[str] | None = None,
    *,
    config_path: Path = CONFIG_PATH,
    now: datetime | None = None,
    player: Callable[[Path], None] = play,
    gather_options: dict | None = None,
    voices_options: dict | None = None,
    **speak_options,
) -> int:
    args = parser().parse_args(argv)
    now = now or datetime.now()
    cache_dir = speak_options.get("cache_dir", CACHE_DIR)
    try:
        config = load_config(config_path)
        if args.voices:
            for line in list_voices(**(voices_options or {})):
                print(line)
            return 0
        if not config.enabled and not args.dry_run:
            raise VoiceError("Voice is off: set enabled = true under [voice] in config.toml")
        sources = gather(
            now,
            greeting_name=config.greeting_name,
            coordinates=config.coordinates,
            unit=config.temperature_unit,
            network=config.enabled,  # voice off: local data only, nothing fetched
            cache_dir=cache_dir,
            **(gather_options or {}),
        )
        script = build_script(now.date(), sources)
        if args.dry_run:
            text = prepare_text(script)
            print(text)
            reach = (
                "weather and the Runna feed were read; nothing was sent to ElevenLabs"
                if config.enabled
                else "voice is off, so nothing was fetched or sent"
            )
            print(f"({len(text)} characters; {reach})")
            return 0
        audio = speak(script, config, now=now, **speak_options)
    except VoiceError as e:
        print(f"Voice: {e}", file=sys.stderr)
        return 1
    print("Playing this morning's brief.")
    player(audio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
