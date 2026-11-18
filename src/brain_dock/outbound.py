"""Read-only calls to outside services for the morning brief (ADR 0014), and the private
files they leave behind.

- fetch(): HTTPS GET only, inside the network guard with only that URL's host allowed.
  Errors name the source ("weather", "Runna feed"), never the URL, query or body, because
  a feed URL is a secret.
- keychain_secret(): a value from the macOS keychain. It starts a process, so call it
  before the guard, never inside it.
- write_private() / private_dir(): owner-only files and folders under data/.
"""

import http.client
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from brain_dock.core.agents.guard import guarded_run

TIMEOUT_SECONDS = 15
MAX_BYTES = 2_000_000  # a day's feed or forecast is far smaller

Guard = Callable[..., AbstractContextManager]
Get = Callable[[str, dict], bytes]


class FetchError(RuntimeError):
    """An outside source couldn't be read. The message names the source only."""


class RefusedError(FetchError):
    """The service answered with an HTTP error: its status and body, kept off the message."""

    def __init__(self, message: str, status: int, body: bytes):
        super().__init__(message)
        self.status, self.body = status, body


def https_url(url: str, source: str) -> str:
    """webcal:// becomes https://; anything else that isn't https:// with a host is refused."""
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme.lower() == "webcal" else parts.scheme.lower()
    if scheme != "https" or not parts.hostname:
        raise FetchError(f"{source}: the address must be an https:// or webcal:// link")
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))


def default_get(url: str, headers: dict) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(MAX_BYTES)


def fetch(
    url: str,
    source: str,
    *,
    headers: dict | None = None,
    get: Get = default_get,
    guard: Guard = guarded_run,
) -> bytes:
    url = https_url(url, source)
    host = urlsplit(url).hostname
    failure: FetchError
    try:
        with guard(allow=[(host, 443)]):
            return get(url, headers or {})
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BYTES)
        except OSError:
            body = b""
        failure = RefusedError(f"{source}: the service answered HTTP {e.code}", e.code, body)
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError):
        failure = FetchError(f"Couldn't reach the {source}")
    raise failure  # raised outside the except: no chained error carrying the URL


def keychain_secret(service: str, account: str = "brain-dock", run: Callable = subprocess.run):
    """The secret stored under this service, or None. Never prints the tool's own output."""
    try:
        result = run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)
