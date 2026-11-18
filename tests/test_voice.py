"""The spoken morning show (ADR 0013, 0014). Every test uses a fake sender, guard, keychain
and sources: nothing here reaches the network, the real keychain or the speaker."""

import inspect
import io
import json
import logging
import os
import stat
import urllib.error
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from brain_dock import outbound, voice
from brain_dock.core.agents.guard import guarded_run
from brain_dock.voice import VoiceConfig, VoiceError

from .conftest import SECRET

KEY = "sk_" + "0f" * 24  # a fake key, shaped like an ElevenLabs one
BRIEF = (
    "Good morning, it's Tuesday, November 17th. On the job front... 2 follow-ups are due "
    "today. In progress: 3 applied, 1 screen, 1 interview. That's your morning."
)
ON = VoiceConfig(enabled=True, voice_id="TestVoice123")  # the default model: Eleven v3
NOW = datetime(2026, 11, 17, 7, 30)
CONFIG_ON = '[voice]\nenabled = true\nvoice_id = "TestVoice123"\n'
NO_NETWORK = {
    "secret": lambda service: None,
    "fetch_fn": lambda *a, **k: pytest.fail("fetched in a test that shouldn't"),
}


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


def run_main(
    tmp_path,
    fake,
    *,
    config=CONFIG_ON,
    lines=("2 follow-ups are due today.",),
    played=None,
    argv=(),
):
    path = tmp_path / "config.toml"
    if config is not None:
        path.write_text(config)
    return voice.main(
        list(argv),
        config_path=path,
        now=NOW,
        gather_options={**NO_NETWORK, "lines": lambda day: {"job_search": list(lines)}},
        player=lambda audio: (played if played is not None else []).append(audio),
        **fake.options(tmp_path / "cache"),
    )


def test_off_by_default_sends_nothing(tmp_path, capsys):
    for config in [None, "", "[inbox]\n", "[voice]\n", "[voice]\nenabled = false\n"]:
        fake = Fake()
        code = run_main(tmp_path, fake, config=config)
        (tmp_path / "config.toml").unlink(missing_ok=True)

        assert code == 1
        assert fake.events == []  # no key, no send
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
    assert sent["model_id"] == "eleven_v3"
    assert sent["voice_settings"] == {"stability": 0.5, "similarity_boost": 0.75}
    assert SECRET not in request.data.decode()
    assert request.get_method() == "POST"
    assert request.full_url == (
        "https://api.elevenlabs.io/v1/text-to-speech/TestVoice123?output_format=mp3_44100_128"
    )
    assert request.get_header("Xi-api-key") == KEY  # the key: only in this header
    assert KEY not in request.data.decode() and KEY not in request.full_url


# Fake values, built from parts so secret scanners don't mistake the test file for a leak.
SECRET_SHAPES = [
    "sk-" + "ant-api03-abcdefghijklmnopqrstuvwxyz012345",
    "sk_0123456789abcdef0123456789abcdef0123",
    "Bearer abc.DEF-ghi_jkl.mno",
    "password=hunter2-correct",
    "api_key: q1w2e3r4t5",
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "ghp" + "_abcdefghijklmnopqrstuvwxyz0123456789",
    "github" + "_pat_11ABCDEFG0123456789_abcdefghij",
    "xox" + "b-1234567890-abcdefghij",
    ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3In0", "c2lnbmF0dXJlLXZhbHVl"]),
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
        "Good morning, Avery, it's Wednesday, December 31st. Right now it's 46 degrees, "
        "heading for 52, with a low of 41. There's a 70 percent chance of rain, so grab a "
        "hood before noon.",
        "On the training plan today: Tempo Run - 6 x 800m 5K pace w/ 90s, 8 kilometers, "
        "about 55 minutes. No run on the plan today... it's a rest day.",
        "On the job front... 2 follow-ups are overdue. That's your morning. Have a lovely day!",
    ]
    for line in lines:
        assert voice.prepare_text(line) == line


def test_api_key_never_in_output_logs_errors_or_repr(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    echo = json.dumps({"detail": {"code": "invalid_api_key", "message": f"bad key {KEY}"}})
    failing = Fake(error=lambda: http_error(401, echo.encode()))

    code = run_main(tmp_path, failing)
    assert code == 1
    with pytest.raises(VoiceError) as raised:
        voice.speak(BRIEF + " again", ON, now=NOW, **Fake(error=failing.error).options(tmp_path))
    run_main(tmp_path, Fake(), lines=["1 offer is open."])  # and a run that succeeds

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
    assert first.name == voice.cache_name(voice.prepare_text(BRIEF), ON, "eleven_v3")
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
    last_month, this_month = datetime(2026, 10, 30, 7, 0), datetime(2026, 11, 2, 7, 0)
    (tmp_path / "attempts.txt").write_text(
        f"{last_month.isoformat()} 300\n{this_month.isoformat()} 310\n"
        f"{(NOW - timedelta(days=1)).isoformat()}\n"  # a line from before counts were kept
    )

    voice.speak(BRIEF, ON, now=NOW, **Fake().options(tmp_path))

    assert not old.exists() and recent.exists()
    attempts = (tmp_path / "attempts.txt").read_text().splitlines()
    assert attempts == [  # this month stays (the monthly budget), an older month goes
        f"{this_month.isoformat()} 310",
        f"{(NOW - timedelta(days=1)).isoformat()} {voice.MAX_SCRIPT_CHARS}",  # no count: most
        f"{NOW.isoformat()} {len(BRIEF)}",
    ]


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
    too_long = "x " * 211  # 422 characters

    with pytest.raises(VoiceError, match="over 420 characters"):
        voice.speak(too_long, ON, now=NOW, **fake.options(tmp_path))
    assert fake.events == []
    voice.speak(too_long[:420], ON, now=NOW, **fake.options(tmp_path))  # at the cap: fine
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


def test_request_runs_under_the_network_guard_with_only_elevenlabs_allowed(tmp_path):
    fake = Fake()  # its send() fails unless the guard is active

    voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path))

    assert fake.allow == [("api.elevenlabs.io", 443)]
    assert fake.events.index("guard") < fake.events.index("send")
    assert inspect.signature(voice.speak).parameters["guard"].default is guarded_run


def test_default_model_is_v3_with_one_fallback_to_multilingual_v2(tmp_path):
    denied = json.dumps({"detail": {"code": "model_access_denied", "message": "no"}}).encode()
    answers = [lambda: http_error(403, denied)]

    class FirstRefused(Fake):
        def send(self, request):
            self.error = answers.pop(0) if answers else None
            return super().send(request)

    fake, notes = FirstRefused(), []
    audio = voice.speak(BRIEF, ON, now=NOW, note=notes.append, **fake.options(tmp_path))

    assert [body(r)["model_id"] for r in fake.requests] == ["eleven_v3", "eleven_multilingual_v2"]
    assert audio.name == voice.cache_name(voice.prepare_text(BRIEF), ON, "eleven_multilingual_v2")
    assert notes == [
        "eleven_v3 isn't available on this account (model_access_denied); trying "
        'eleven_multilingual_v2. Set model_id = "eleven_multilingual_v2" under [voice] to skip '
        "the first try."
    ]
    usage = (tmp_path / "attempts.txt").read_text().splitlines()
    assert [line.split()[1] for line in usage] == ["0", str(len(BRIEF))]  # refused: no credits

    assert voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path)) == audio  # cached
    assert len(fake.requests) == 2

    fixed = VoiceConfig(
        enabled=True, voice_id="TestVoice123", model_id="eleven_v3", model_fixed=True
    )  # model_id set in config: no fallback
    other_error = json.dumps({"detail": {"code": "invalid_api_key"}}).encode()
    for config, error, code in [(fixed, denied, 403), (ON, other_error, 401)]:
        one = Fake(error=lambda e=error, c=code: http_error(c, e))
        with pytest.raises(VoiceError, match=f"HTTP {code}"):
            voice.speak(BRIEF + f" {code}", config, now=NOW, **one.options(tmp_path / str(code)))
        assert len(one.requests) == 1


def test_v3_request_sends_only_stability_and_similarity(tmp_path):
    fake = Fake()
    voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path))

    assert body(fake.requests[0])["voice_settings"] == {"stability": 0.5, "similarity_boost": 0.75}
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_ON)
    default = voice.load_config(path)
    assert (default.model_id, default.model_fixed) == ("eleven_v3", False)
    path.write_text(CONFIG_ON + 'model_id = "eleven_multilingual_v2"\n')
    chosen = voice.load_config(path)
    assert (chosen.model_id, chosen.model_fixed) == ("eleven_multilingual_v2", True)


def test_monthly_character_budget_stops_before_the_free_plan_limit(tmp_path):
    tmp_path.chmod(0o700)
    (tmp_path / "attempts.txt").write_text(
        "2026-10-28T07:00:00 9000\n"  # last month: doesn't count
        "2026-11-03T07:00:00 9690\n"
        "2026-11-04T07:00:00 0\n"  # a refused request: no credits
    )
    fake = Fake()

    voice.speak("Short one.", ON, now=NOW, **fake.options(tmp_path))  # 9,700: still under
    assert len(fake.requests) == 1
    with pytest.raises(VoiceError, match="budget of 9,800 characters is used up"):
        voice.speak(BRIEF, ON, now=NOW, **fake.options(tmp_path))  # 9,700 + 158 would pass 9,800
    assert len(fake.requests) == 1
    assert voice.characters_this_month(tmp_path, NOW) == 9700
    assert voice.MONTHLY_CHAR_BUDGET < 10_000  # the free plan's monthly credits
    nextmonth = datetime(2026, 12, 1, 7, 0)
    voice.speak(BRIEF, ON, now=nextmonth, **fake.options(tmp_path))
    assert len(fake.requests) == 2


def test_show_asks_nothing_and_plays_at_normal_speed(tmp_path, monkeypatch):
    def no_prompt(*args):
        raise AssertionError("the show must not ask anything")

    monkeypatch.setattr("builtins.input", no_prompt)
    played = []

    assert run_main(tmp_path, Fake(), played=played) == 0

    commands = []
    voice.play(played[0], run=lambda cmd, **kwargs: commands.append(cmd))
    assert commands == [["afplay", str(played[0])]]  # no rate, no quality flags
    assert "mood" not in voice.parser().format_help().lower()
    with pytest.raises(SystemExit):
        voice.parser().parse_args(["--mood", "low"])


def test_dry_run_prints_the_script_and_sends_nothing_to_elevenlabs(tmp_path, capsys):
    from .show_fixtures import COORDS, FEED_URL, FakeNet

    path = tmp_path / "config.toml"
    path.write_text(
        CONFIG_ON + f'greeting_name = "Avery"\nweather_latitude = {COORDS[0]}\n'
        f"weather_longitude = {COORDS[1]}\n"
    )
    net, fake = FakeNet(), Fake()

    code = voice.main(
        ["--dry-run"],
        config_path=path,
        now=NOW,
        gather_options=net.options(),
        **fake.options(tmp_path / "cache"),
    )

    assert code == 0
    script, summary = capsys.readouterr().out.splitlines()
    assert script.startswith("Good morning, Avery, it's Tuesday, November 17th. Right now")
    assert "Easy Run" not in script  # the fixture's workout is on the 18th, so today's a rest
    assert "rest day" in script
    assert summary == (
        f"({len(script)} characters; weather and the Runna feed were read; "
        "nothing was sent to ElevenLabs)"
    )
    assert fake.events == []  # no key, no guard, no send
    assert len(net.fetched) == 2
    assert net.secrets == ["brain-dock-runna-ics"]  # the feed URL was read from the keychain
    for leak in [FEED_URL, "feeds.example.test", "feed-secret-qwfp", KEY]:  # and never shown
        assert leak not in script and leak not in summary


def test_dry_run_with_voice_off_reaches_no_network(tmp_path, capsys, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("voice is off: nothing may reach the network")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    path = tmp_path / "config.toml"
    path.write_text(
        '[voice]\nenabled = false\ngreeting_name = "Avery"\n'
        "weather_latitude = 12.3\nweather_longitude = -45.6\n"
    )
    fake = Fake()
    options = {
        "secret": no_network,
        "fetch_fn": no_network,
        "lines": lambda d: {"job_search": ["1 offer is open."]},
    }

    assert (
        voice.main(
            ["--dry-run"],
            config_path=path,
            now=NOW,
            gather_options=options,
            **fake.options(tmp_path / "cache"),
        )
        == 0
    )

    script, summary = capsys.readouterr().out.splitlines()
    assert script == (
        "Good morning, Avery, it's Tuesday, November 17th. On the job front... "
        "1 offer is open. That's your morning. Have a lovely day!"
    )
    assert summary.endswith("voice is off, so nothing was fetched or sent)")
    assert fake.events == []


def test_voices_lists_names_and_ids_only(tmp_path, capsys):
    answer = {
        "voices": [
            {
                "voice_id": "EXAVITQu4vr4xnSDxMaL",
                "name": "Sarah",
                "category": "premade",
                "description": "long text",
                "labels": {"accent": "american"},
                "preview_url": "https://cdn.example.test/p.mp3",
                "samples": [{"file": "x"}],
            },
            {"voice_id": "abc123", "name": "My voice", "category": "cloned"},
        ]
    }
    calls = []

    def fetch_fn(url, source, headers):
        calls.append((url, source, headers))
        return json.dumps(answer).encode()

    code = voice.main(
        ["--voices"],
        config_path=tmp_path / "none.toml",
        voices_options={"get_key": lambda: KEY, "fetch_fn": fetch_fn},
    )

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "Sarah  EXAVITQu4vr4xnSDxMaL  (premade)",
        "My voice  abc123  (cloned)",
    ]
    assert calls == [
        (
            "https://api.elevenlabs.io/v2/voices?page_size=100",
            "ElevenLabs voice list",
            {"xi-api-key": KEY},
        )
    ]

    def refused(url, source, headers):
        raise outbound.RefusedError(
            "x", 401, json.dumps({"detail": {"code": "invalid_api_key", "message": KEY}}).encode()
        )

    code = voice.main(
        ["--voices"],
        config_path=tmp_path / "none.toml",
        voices_options={"get_key": lambda: KEY, "fetch_fn": refused},
    )
    err = capsys.readouterr().err
    assert code == 1
    assert err.strip() == "Voice: ElevenLabs refused the request: HTTP 401 (invalid_api_key)"
    assert KEY not in err
