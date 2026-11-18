"""The spoken brief (ADR 0013). Every test uses a fake sender, guard and keychain: nothing
here reaches the network, the real keychain or the speaker."""

import inspect
import io
import json
import logging
import os
import re
import stat
import urllib.error
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from brain_dock import voice
from brain_dock.core.agents.guard import guarded_run
from brain_dock.voice import VoiceConfig, VoiceError

from .conftest import SECRET

KEY = "sk_" + "0f" * 24  # a fake key, shaped like an ElevenLabs one
BRIEF = (
    "Good morning. Here's your brief for Tuesday, November 17. 2 follow-ups are due today. "
    "In progress: 3 applied, 1 screen, 1 interview."
)
ON = VoiceConfig(enabled=True, voice_id="TestVoice123", model_id="eleven_flash_v2_5")
NOW = datetime(2026, 11, 17, 7, 30)
CONFIG_ON = '[voice]\nenabled = true\nvoice_id = "TestVoice123"\n'


def http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.elevenlabs.io/x", status, "x", {}, io.BytesIO(body))


class Fake:
    """Stands in for the keychain, the network guard and ElevenLabs, and records the order."""

    def __init__(self, audio=b"ID3-fake-audio", error=None):
        self.audio, self.error = audio, error
        self.requests, self.events, self.allow, self.inside = [], [], None, False

    def get_key(self):
        assert not self.inside, "the keychain lookup starts a process: never inside the guard"
        self.events.append("key")
        return KEY

    def send(self, request):
        assert self.inside, "sent outside the network guard"
        self.events.append("send")
        self.requests.append(request)
        if self.error:
            raise self.error()
        return self.audio

    @contextmanager
    def guard(self, allow):
        self.allow, self.inside = list(allow), True
        self.events.append("guard")
        try:
            yield
        finally:
            self.inside = False

    def options(self, cache_dir):
        return {
            "cache_dir": cache_dir,
            "get_key": self.get_key,
            "send": self.send,
            "guard": self.guard,
        }


def body(request) -> dict:
    return json.loads(request.data)


def run_main(tmp_path, fake, *, config=CONFIG_ON, answer="2", brief=BRIEF, played=None):
    path = tmp_path / "config.toml"
    if config is not None:
        path.write_text(config)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return answer

    code = voice.main(
        [],
        config_path=path,
        brief=lambda: brief,
        ask=ask,
        player=lambda audio, mood: (played if played is not None else []).append((audio, mood)),
        **fake.options(tmp_path / "cache"),
    )
    return code, asked


def test_off_by_default_sends_nothing(tmp_path, capsys):
    for config in [None, "", "[inbox]\n", "[voice]\n", "[voice]\nenabled = false\n"]:
        fake = Fake()
        code, asked = run_main(tmp_path, fake, config=config)
        (tmp_path / "config.toml").unlink(missing_ok=True)

        assert code == 1
        assert fake.events == [] and asked == []  # no key, no send, not even the mood prompt
        assert "Voice is off" in capsys.readouterr().err
    with pytest.raises(VoiceError, match="Voice is off"):
        voice.speak(BRIEF, VoiceConfig(enabled=False), now=NOW, **Fake().options(tmp_path))
    assert voice.load_config(tmp_path / "missing.toml").enabled is False


def test_request_body_is_only_the_masked_brief(tmp_path):
    fake = Fake()
    planted = f"{BRIEF} token={SECRET}"

    voice.speak(planted, ON, now=NOW, **fake.options(tmp_path))

    [request] = fake.requests
    sent = body(request)
    assert set(sent) == {"text", "model_id", "voice_settings"}
    assert sent["text"] == voice.prepare_text(planted) == f"{BRIEF} [secret]"
    assert sent["model_id"] == "eleven_flash_v2_5"
    assert sent["voice_settings"] == voice.VOICE_SETTINGS
    assert SECRET not in request.data.decode()
    assert request.get_method() == "POST"
    assert request.full_url == (
        "https://api.elevenlabs.io/v1/text-to-speech/TestVoice123?output_format=mp3_44100_128"
    )
    assert request.get_header("Xi-api-key") == KEY  # the key: only in this header
    assert KEY not in request.data.decode() and KEY not in request.full_url


SECRET_SHAPES = [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345",
    "sk_0123456789abcdef0123456789abcdef0123",
    "Bearer abc.DEF-ghi_jkl.mno",
    "password=hunter2-correct",
    "api_key: q1w2e3r4t5",
    "AKIAABCDEFGHIJKLMNOP",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_11ABCDEFG0123456789_abcdefghij",
    "xoxb-1234567890-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3In0.c2lnbmF0dXJlLXZhbHVl",
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "QmFzZTY0LWVuY29kZWQtc2VjcmV0LXZhbHVlLWhlcmU=",
]


def test_secret_shaped_text_is_masked():
    for secret in SECRET_SHAPES:
        masked = voice.prepare_text(f"Before {secret} after.")

        assert masked == "Before [secret] after.", secret


def test_masking_keeps_ordinary_brief_text():
    lines = [
        BRIEF,
        "1 follow-up is overdue. 1 offer is open. 2 saved jobs are waiting to be applied to.",
        "3 inbox roles are waiting for your decision. More in the app.",
        "Good morning. Here's your brief for Wednesday, December 31. "
        "Nothing needs your attention today.",
    ]
    for line in lines:
        assert voice.prepare_text(line) == line


def test_api_key_never_in_output_logs_errors_or_repr(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    echo = json.dumps({"detail": {"code": "invalid_api_key", "message": f"bad key {KEY}"}})
    failing = Fake(error=lambda: http_error(401, echo.encode()))

    code, _ = run_main(tmp_path, failing)
    assert code == 1
    with pytest.raises(VoiceError) as raised:
        voice.speak(BRIEF + " again", ON, now=NOW, **Fake(error=failing.error).options(tmp_path))
    run_main(tmp_path, Fake(), brief=BRIEF + " works")  # and a run that succeeds

    out = capsys.readouterr()
    seen = [
        out.out,
        out.err,
        caplog.text,
        str(raised.value),
        repr(raised.value),
        repr(ON),
        repr(voice.load_config(tmp_path / "config.toml")),
    ]
    assert all(KEY not in text for text in seen)
    assert repr(ON) == "VoiceConfig(<hidden>)"
    assert len(failing.requests) == 1  # the failing run did send (so the key was in play)


def test_config_errors_name_the_key_never_the_value(tmp_path):
    cases = {
        f'[voice]\nenabled = true\nvoice_id = "has spaces {SECRET}"\n': "voice.voice_id",
        f'[voice]\nenabled = true\nvoice_id = "ok"\nmodel_id = "{SECRET}!"\n': "voice.model_id",
        f'[voice]\nenabled = "{SECRET}"\n': "voice.enabled",
        f'[voice]\nenabled = false\napi_key = "{SECRET}"\n': "voice.api_key",
        f"[voice\n{SECRET}": "isn't valid TOML",
        f'voice = "{SECRET}"\n': "[voice] section",
    }
    path = tmp_path / "config.toml"
    for text, named in cases.items():
        path.write_text(text)
        with pytest.raises(VoiceError) as raised:
            voice.load_config(path)
        assert named in str(raised.value)
        assert SECRET not in str(raised.value)
        assert raised.value.__cause__ is None


def test_key_is_read_from_the_keychain_before_the_guarded_request(tmp_path):
    calls = []

    class Result:
        def __init__(self, code, out, err=""):
            self.returncode, self.stdout, self.stderr = code, out, err

    def run(cmd, **kwargs):
        calls.append(cmd)
        return Result(0, KEY + "\n")

    assert voice.keychain_key(run) == KEY
    assert calls == [
        [
            "security",
            "find-generic-password",
            "-s",
            "brain-dock-elevenlabs",
            "-a",
            "brain-dock",
            "-w",
        ]
    ]
    for result in [Result(44, "", f"not found {SECRET}"), Result(0, "  \n")]:
        with pytest.raises(VoiceError) as raised:
            voice.keychain_key(lambda cmd, **kwargs: result)  # noqa: B023
        assert "security add-generic-password -s brain-dock-elevenlabs" in str(raised.value)
        assert SECRET not in str(raised.value)

    fake = Fake()
    voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path))
    assert fake.events == ["key", "guard", "send"]
    assert inspect.signature(voice.speak).parameters["get_key"].default is voice.keychain_key


def test_same_brief_is_generated_once(tmp_path):
    fake = Fake()

    first = voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path))
    again = voice.speak(BRIEF, ON, now=NOW + timedelta(hours=2), **fake.options(tmp_path))
    other = voice.speak(BRIEF + " One more.", ON, now=NOW, **fake.options(tmp_path))

    assert first == again != other
    assert first.read_bytes() == b"ID3-fake-audio"
    assert len(fake.requests) == 2  # the repeat came from the cache
    assert first.name == voice.cache_name(voice.prepare_text(BRIEF), ON)
    assert BRIEF not in first.name  # the file name is a hash, not the text


def test_cache_files_are_owner_only(tmp_path):
    cache = tmp_path / "cache"
    old_umask = os.umask(0o022)  # the usual default: new files readable by others
    try:
        audio = voice.speak(BRIEF, ON, now=NOW, **Fake().options(cache))
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(cache.stat().st_mode) == 0o700
    assert stat.S_IMODE(audio.stat().st_mode) == 0o600
    assert stat.S_IMODE((cache / "attempts.txt").stat().st_mode) == 0o600


def test_old_cache_files_are_pruned(tmp_path):
    tmp_path.chmod(0o700)
    old, recent = tmp_path / "old.mp3", tmp_path / "recent.mp3"
    for path, age in [(old, 8), (recent, 1)]:
        path.write_bytes(b"audio")
        when = (NOW - timedelta(days=age)).timestamp()
        os.utime(path, (when, when))
    (tmp_path / "attempts.txt").write_text(
        f"{(NOW - timedelta(days=9)).isoformat()}\n{(NOW - timedelta(days=1)).isoformat()}\n"
    )

    voice.speak(BRIEF, ON, now=NOW, **Fake().options(tmp_path))

    assert not old.exists() and recent.exists()
    attempts = (tmp_path / "attempts.txt").read_text().split()
    assert attempts == [(NOW - timedelta(days=1)).isoformat(), NOW.isoformat()]


def test_daily_generation_limit(tmp_path):
    failing = Fake(error=lambda: http_error(500, b"{}"))
    for i in range(voice.MAX_ATTEMPTS_PER_DAY):  # failed attempts count too
        with pytest.raises(VoiceError, match="HTTP 500"):
            voice.speak(f"{BRIEF} {i}", ON, now=NOW, **failing.options(tmp_path))

    with pytest.raises(VoiceError, match="Already 3 requests today"):
        voice.speak(BRIEF, ON, now=NOW, **failing.options(tmp_path))
    assert len(failing.requests) == voice.MAX_ATTEMPTS_PER_DAY

    tomorrow = Fake()
    voice.speak(BRIEF, ON, now=NOW + timedelta(days=1), **tomorrow.options(tmp_path))
    assert len(tomorrow.requests) == 1


def test_text_over_the_cap_is_refused_before_sending(tmp_path):
    fake = Fake()
    too_long = "x " * 301  # 602 characters

    with pytest.raises(VoiceError, match="over 600 characters"):
        voice.speak(too_long, ON, now=NOW, **fake.options(tmp_path))
    assert fake.events == []
    voice.speak(too_long[:600], ON, now=NOW, **fake.options(tmp_path))  # at the cap: fine
    assert len(fake.requests) == 1


def test_api_errors_show_status_and_code_only(tmp_path):
    echo = {
        "detail": {
            "code": "insufficient_credits",
            "message": f"{BRIEF} {KEY}",
            "request_id": SECRET,
        }
    }
    cases = [
        (
            lambda: http_error(402, json.dumps(echo).encode()),
            "ElevenLabs refused the request: HTTP 402 (insufficient_credits)",
        ),
        (
            lambda: http_error(401, f"<html>{BRIEF}</html>".encode()),
            "ElevenLabs refused the request: HTTP 401 (no code)",
        ),
        (
            lambda: http_error(400, json.dumps({"detail": {"code": BRIEF}}).encode()),
            "ElevenLabs refused the request: HTTP 400 (no code)",
        ),
        (lambda: urllib.error.URLError(f"dns failed {SECRET}"), "Couldn't reach ElevenLabs"),
        (lambda: TimeoutError(), "Couldn't reach ElevenLabs"),
    ]
    for i, (error, message) in enumerate(cases):
        with pytest.raises(VoiceError) as raised:
            voice.speak(
                f"Brief {i}.",
                ON,
                now=NOW + timedelta(days=i),
                **Fake(error=error).options(tmp_path),
            )
        assert str(raised.value) == message
        assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_mood_changes_only_local_playback(tmp_path):
    fake, played = Fake(), []
    for answer in ["1", "2", "3"]:
        assert run_main(tmp_path, fake, answer=answer, played=played)[0] == 0

    assert len(fake.requests) == 1  # one generation serves every mood
    assert [mood for _, mood in played] == ["low", "okay", "good"]
    assert len({audio for audio, _ in played}) == 1

    commands = []
    for mood in ["low", "okay", "good"]:
        voice.play(played[0][0], mood, run=lambda cmd, **kwargs: commands.append(cmd))
    assert [cmd[cmd.index("-r") + 1] for cmd in commands] == ["0.9", "1.0", "1.05"]
    assert all(cmd[0] == "afplay" and cmd[-1] == str(played[0][0]) for cmd in commands)

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = Fake()  # a fresh cache: the low-mood request equals the plain one
    run_main(other_dir, other, answer="1")
    assert body(other.requests[0]) == body(fake.requests[0])
    assert other.requests[0].full_url == fake.requests[0].full_url


def test_mood_is_never_stored_or_logged(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    fake, played = Fake(), []

    assert run_main(tmp_path, fake, answer="1", played=played)[0] == 0

    assert played[0][1] == "low"  # it reached the player, the only place it goes
    out = capsys.readouterr()
    stored = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != "config.toml"]
    assert len(stored) == 2  # the audio and the attempts file exist and are checked
    texts = [out.out, out.err, caplog.text, fake.requests[0].data.decode()]
    texts += [p.read_bytes().decode(errors="replace") + p.name for p in stored]
    for text in texts:
        assert not re.search(r"\b(low|mood)\b", text, re.I)  # ("follow-ups" is fine)


def test_mood_is_asked_at_a_prompt_never_a_flag(tmp_path, capsys):
    with pytest.raises(SystemExit):
        voice.parser().parse_args(["--mood", "low"])
    assert "--mood" not in voice.parser().format_help()

    _, asked = run_main(tmp_path, Fake())
    assert asked == [voice.MOOD_PROMPT]

    assert [voice.ask_mood(lambda p, a=a: a) for a in ["1", "2", "3", "", " 3 ", "x"]] == [
        "low",
        "okay",
        "good",
        "okay",
        "good",
        "okay",
    ]

    def eof(prompt):
        raise EOFError

    assert voice.ask_mood(eof) == "okay"


def test_request_runs_under_the_network_guard_with_only_elevenlabs_allowed(tmp_path):
    fake = Fake()  # its send() fails unless the guard is active

    voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path))

    assert fake.allow == [("api.elevenlabs.io", 443)]
    assert fake.events.index("guard") < fake.events.index("send")
    assert inspect.signature(voice.speak).parameters["guard"].default is guarded_run
