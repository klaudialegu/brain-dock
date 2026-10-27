"""The network guard (ADR 0008, design section 6): while an agent run is active, this
process can't reach anywhere except the run's allowed `host:port` pairs, and can't start
processes or load native libraries.

It uses Python audit hooks (PEP 578): the interpreter calls the hook before every DNS
lookup, socket connect, process start and ctypes library load, and a hook can't be removed
once added. It's installed once and does nothing while no run is active.

Honest limits: audit hooks see Python-level calls, so a compiled extension making raw
system calls could slip past. An IP allowlist can't tell two sites on one shared CDN
address apart; the DNS check is the main line. A thread a tool leaves running is unguarded
once the run ends. This is the strongest guard inside Python, not an operating-system
sandbox.
"""

import socket
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

# Events refused outright during a run, with the reason code that's audited.
REFUSED_EVENTS = {
    "subprocess.Popen": "guard_process",
    "os.system": "guard_process",
    "os.exec": "guard_process",
    "os.posix_spawn": "guard_process",
    "os.spawn": "guard_process",
    "os.fork": "guard_process",
    "os.forkpty": "guard_process",
    "pty.spawn": "guard_process",
    "ctypes.dlopen": "guard_native_code",
    "socket.sendto": "guard_connect",  # UDP sends name their address without connect()
    "socket.sendmsg": "guard_connect",
}


class NetworkGuardError(PermissionError):
    """An agent run tried to reach outside its allowlist, start a process or load native
    code. Nothing happened."""


_lock = threading.Lock()
_runs: list[dict] = []  # one entry per active run: its allowlist and refusal callback
_addresses: set[tuple[str, int]] = set()  # (ip, port) the allowed hosts resolve to
_local = threading.local()
_installed = False


def _resolve(host: str, port: int) -> set[tuple[str, int]]:
    """The addresses a host resolves to. Called with the guard bypassed."""
    return {(info[4][0], port) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}


def _allowed_hosts() -> set[tuple[str, int]]:
    return {pair for run in _runs for pair in run["allow"]}


def _refresh_addresses() -> None:
    """Resolve every allowed host again (addresses can change during a run)."""
    _local.bypass = True
    try:
        fresh = set()
        for host, port in _allowed_hosts():
            try:
                fresh |= _resolve(host, port)
            except OSError:
                pass
    finally:
        _local.bypass = False
    with _lock:
        _addresses.clear()
        _addresses.update(fresh)


def _refuse(reason: str) -> None:
    callbacks = [run["on_refusal"] for run in _runs if run["on_refusal"] is not None]
    _local.bypass = True  # the audit write itself mustn't trip the guard
    try:
        for callback in callbacks:
            try:
                callback(reason)
            except Exception:
                pass  # the refusal stands even if it can't be recorded
    finally:
        _local.bypass = False
    raise NetworkGuardError(f"refused during an agent run ({reason})")


def _port(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hook(event: str, args: tuple) -> None:
    if not _runs or getattr(_local, "bypass", False):
        return
    if event in REFUSED_EVENTS:
        _refuse(REFUSED_EVENTS[event])
    elif event == "socket.getaddrinfo":
        host, port = args[0], _port(args[1])
        host = host.decode() if isinstance(host, bytes) else str(host)
        if (host.lower(), port) not in _allowed_hosts():
            _refuse("guard_dns")
    elif event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple):  # a Unix socket path
            _refuse("guard_connect")
        target = (str(address[0]), _port(address[1]))
        if target not in _addresses:
            _refresh_addresses()
            if target not in _addresses:
                _refuse("guard_connect")


def install() -> None:
    """Add the audit hook once per process. It can't be removed, by design."""
    global _installed
    with _lock:
        if not _installed:
            sys.addaudithook(_hook)
            _installed = True


@contextmanager
def guarded_run(
    allow: Iterable[tuple[str, int]] = (),
    on_refusal: Callable[[str], None] | None = None,
) -> Iterator[None]:
    """Everything inside runs under the guard, in every thread of the process."""
    install()
    run = {"allow": {(h.lower(), int(p)) for h, p in allow}, "on_refusal": on_refusal}
    with _lock:
        _runs.append(run)
    try:
        _refresh_addresses()
        yield
    finally:
        with _lock:
            _runs.remove(run)
            if not _runs:
                _addresses.clear()
