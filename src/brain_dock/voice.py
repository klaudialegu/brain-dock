"""The spoken brief (ADR 0013): reads the daily brief aloud with ElevenLabs text-to-speech.

Off by default. When `[voice] enabled = true` is in config.toml:
- Only the brief text is sent. It's masked first (anything secret-shaped, then the
  gateway's redact()), along with the model ID and fixed, neutral voice settings.
- The API key comes from the macOS keychain, never a file. It's sent only in the request
  header, and never printed, logged or put in an error.
- Mood is asked at a prompt (never a flag, so it stays out of shell history). It changes
  only the local playback speed, is used for this run only, and is never stored or sent.
- Credits: the brief is capped, the audio is cached by content (the same brief is never
  generated twice), and at most MAX_ATTEMPTS_PER_DAY requests go out a day.
- The request runs inside the network guard with only api.elevenlabs.io allowed, from
  this command's own process, never the web server (the guard is process-wide).

Run: `uv run python -m brain_dock.voice` (add `--dry-run` to see the exact text that would
be sent, with nothing sent).
"""

import argparse
import hashlib
import json
import os
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

from brain_dock.brief import MAX_BRIEF_CHARS, current_brief
from brain_dock.core.agents.gateway import redact
from brain_dock.core.agents.guard import guarded_run
from brain_dock.core.db import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "config.toml"
CACHE_DIR = REPO_ROOT / "data" / "voice_cache"  # gitignored (data/)
API_HOST = "api.elevenlabs.io"
OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_MODEL = "eleven_flash_v2_5"  # half the price per character of the v2/v4 models
KEYCHAIN_SERVICE = "brain-dock-elevenlabs"
KEYCHAIN_ACCOUNT = "brain-dock"
MAX_ATTEMPTS_PER_DAY = 3  # failed and timed-out attempts count too
KEEP_DAYS = 7
TIMEOUT_SECONDS = 30

# Always the same: mood never changes what's sent (ADR 0013, D1).
VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True,
    "speed": 1.0,
}
# Mood changes only how fast the cached audio plays here (afplay -r, high-quality mode).
PLAYBACK_RATE = {"low": 0.9, "okay": 1.0, "good": 1.05}
MOOD_CHOICES = {"1": "low", "2": "okay", "3": "good", "": "okay"}
MOOD_PROMPT = "How are you feeling? 1 low, 2 okay, 3 good [2]: "

ID = re.compile(r"[A-Za-z0-9_]{1,64}")
ERROR_CODE = re.compile(r"[a-z_]{1,40}")

# Anything secret-shaped becomes [secret] before the text leaves this machine.
SECRET_SHAPES = [
    re.compile(r"\b(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*\S+", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"),  # sk-ant-…, sk_… (ElevenLabs)
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),  # JWT
    re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}"),  # any long hex or base64 run
]


class VoiceError(RuntimeError):
    """The brief can't be spoken. Messages name keys and codes, never values or text."""


@dataclass(frozen=True, repr=False)  # no repr: keep config out of any log line
class VoiceConfig:
    enabled: bool
    voice_id: str = ""
    model_id: str = DEFAULT_MODEL

    def __repr__(self) -> str:
        return "VoiceConfig(<hidden>)"


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
    if not enabled:
        return VoiceConfig(enabled=False)
    voice_id = section.get("voice_id")
    if not isinstance(voice_id, str) or not ID.fullmatch(voice_id):
        raise VoiceError("voice.voice_id must be an ElevenLabs voice ID (letters and digits)")
    model_id = section.get("model_id", DEFAULT_MODEL)
    if not isinstance(model_id, str) or not ID.fullmatch(model_id):
        raise VoiceError("voice.model_id must be an ElevenLabs model ID, like eleven_flash_v2_5")
    return VoiceConfig(enabled=True, voice_id=voice_id, model_id=model_id)


def mask_secrets(text: str) -> str:
    for shape in SECRET_SHAPES:
        text = shape.sub("[secret]", text)
    return text


def prepare_text(brief: str) -> str:
    """What may leave this machine: secret shapes masked, then emails, phone numbers and
    URL query strings removed by the gateway's redact()."""
    return redact(mask_secrets(brief)).text


def keychain_key(run: Callable = subprocess.run) -> str:
    """The key from the macOS keychain. Starts a process, so it runs before the guard."""
    try:
        result = run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    key = result.stdout.strip() if result is not None and result.returncode == 0 else ""
    if not key:  # never show stderr: it isn't ours to print
        raise VoiceError(
            f"No ElevenLabs key in the keychain (service {KEYCHAIN_SERVICE}). Add it with: "
            f"security add-generic-password -s {KEYCHAIN_SERVICE} -a {KEYCHAIN_ACCOUNT} -w"
        )
    return key


def request_body(text: str, config: VoiceConfig) -> dict:
    """Everything that's sent besides the key header: nothing else ever goes in."""
    return {"text": text, "model_id": config.model_id, "voice_settings": VOICE_SETTINGS}


def build_request(text: str, config: VoiceConfig, api_key: str) -> urllib.request.Request:
    url = (
        f"https://{API_HOST}/v1/text-to-speech/{quote(config.voice_id, safe='')}"
        f"?output_format={OUTPUT_FORMAT}"
    )
    return urllib.request.Request(
        url,
        data=json.dumps(request_body(text, config)).encode(),
        method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
    )


def default_send(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def error_code(error: urllib.error.HTTPError) -> str:
    """ElevenLabs' short error code (like invalid_api_key), never its message or body."""
    try:
        detail = json.loads(error.read() or b"{}").get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
    except (ValueError, AttributeError, OSError):
        code = None
    return code if isinstance(code, str) and ERROR_CODE.fullmatch(code) else "no code"


def send_guarded(send: Callable, request, guard: Callable[..., AbstractContextManager]) -> bytes:
    failure = None
    try:
        with guard(allow=[(API_HOST, 443)]):
            return send(request)
    except urllib.error.HTTPError as e:
        failure = f"ElevenLabs refused the request: HTTP {e.code} ({error_code(e)})"
    except (urllib.error.URLError, TimeoutError, OSError):
        failure = "Couldn't reach ElevenLabs"
    raise VoiceError(failure)  # raised outside the except: no chained error with the request


def cache_name(text: str, config: VoiceConfig) -> str:
    """Same text, voice, model, settings and format: same file, so it's generated once."""
    fields = {
        "text": text,
        "voice_id": config.voice_id,
        "model_id": config.model_id,
        "settings": VOICE_SETTINGS,
        "format": OUTPUT_FORMAT,
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest() + ".mp3"


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)


def prepare_cache(cache_dir: Path, now: datetime) -> None:
    """Owner-only folder; audio older than KEEP_DAYS is deleted."""
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(cache_dir, 0o700)
    cutoff = (now - timedelta(days=KEEP_DAYS)).timestamp()
    for audio in cache_dir.glob("*.mp3"):
        if audio.stat().st_mtime < cutoff:
            audio.unlink()


def attempts_today(cache_dir: Path, now: datetime) -> int:
    path = cache_dir / "attempts.txt"  # timestamps only, no content
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().split() if line.startswith(now.date().isoformat()))


def record_attempt(cache_dir: Path, now: datetime) -> None:
    path = cache_dir / "attempts.txt"
    cutoff = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
    kept = [t for t in (path.read_text().split() if path.exists() else []) if t[:10] >= cutoff]
    write_private(path, ("\n".join([*kept, now.isoformat(timespec="seconds")]) + "\n").encode())


def speak(
    brief: str,
    config: VoiceConfig,
    *,
    now: datetime,
    cache_dir: Path = CACHE_DIR,
    get_key: Callable[[], str] = keychain_key,
    send: Callable = default_send,
    guard: Callable[..., AbstractContextManager] = guarded_run,
) -> Path:
    """The audio file for this brief: from the cache, or generated once."""
    if not config.enabled:
        raise VoiceError("Voice is off: set enabled = true under [voice] in config.toml")
    text = prepare_text(brief)
    if len(text) > MAX_BRIEF_CHARS:
        raise VoiceError(f"The brief is over {MAX_BRIEF_CHARS} characters; nothing was sent")
    prepare_cache(cache_dir, now)
    audio_path = cache_dir / cache_name(text, config)
    if audio_path.exists():
        return audio_path
    if attempts_today(cache_dir, now) >= MAX_ATTEMPTS_PER_DAY:
        raise VoiceError(f"Already {MAX_ATTEMPTS_PER_DAY} requests today; nothing was sent")
    request = build_request(text, config, get_key())  # the keychain lookup, before the guard
    record_attempt(cache_dir, now)  # before sending: a failure still counts
    audio = send_guarded(send, request, guard)
    if not audio:
        raise VoiceError("ElevenLabs sent back no audio")
    write_private(audio_path, audio)
    return audio_path


def ask_mood(ask: Callable[[str], str] = input) -> str:
    """For this run only: never stored, logged or sent."""
    try:
        answer = ask(MOOD_PROMPT).strip()
    except EOFError:
        answer = ""
    return MOOD_CHOICES.get(answer, "okay")


def play(path: Path, mood: str, run: Callable = subprocess.run) -> None:
    """macOS afplay, after the guarded request (the guard blocks starting processes)."""
    run(["afplay", "-q", "1", "-r", str(PLAYBACK_RATE[mood]), str(path)], check=False)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m brain_dock.voice", description="Read today's brief aloud (ElevenLabs)."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact text that would be sent; send nothing",
    )
    return p


def main(
    argv: list[str] | None = None,
    *,
    config_path: Path = CONFIG_PATH,
    brief: Callable[[], str] = current_brief,
    ask: Callable[[str], str] = input,
    player: Callable[[Path, str], None] = play,
    **speak_options,
) -> int:
    args = parser().parse_args(argv)
    try:
        if args.dry_run:
            text = prepare_text(brief())
            print(text)
            print(f"({len(text)} characters; nothing was sent)")
            return 0
        config = load_config(config_path)
        if not config.enabled:
            raise VoiceError("Voice is off: set enabled = true under [voice] in config.toml")
        text = brief()
        mood = ask_mood(ask)
        audio = speak(text, config, now=datetime.now(), **speak_options)
    except (VoiceError, RuntimeError) as e:
        print(f"Voice: {e}", file=sys.stderr)
        return 1
    print("Playing today's brief.")
    player(audio, mood)
    return 0


if __name__ == "__main__":
    sys.exit(main())
