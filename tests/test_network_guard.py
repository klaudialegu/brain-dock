"""The network guard (ADR 0008): during an agent run, nothing leaves this process except to
the run's allowed host:port, and no process or native library starts. No test here touches
the real network: a local server stands in for the allowed host."""

import ctypes
import os
import socket
import subprocess
import threading

import pytest

from brain_dock.core.agents import guard
from brain_dock.core.agents.guard import NetworkGuardError, guarded_run


@pytest.fixture
def server():
    """A local TCP server on a free port that answers b"ok" to every connection."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    accepted = []

    def serve():
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            accepted.append(conn)
            conn.sendall(b"ok")
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1], accepted
    listener.close()


def fetch(host, port):
    with socket.create_connection((host, port), timeout=2) as conn:
        return conn.recv(2)


def test_dns_for_a_host_not_on_the_allowlist_is_refused():
    refusals = []

    with guarded_run(on_refusal=refusals.append), pytest.raises(NetworkGuardError):
        socket.getaddrinfo("example.invalid", 443)  # refused before any lookup happens

    assert refusals == ["guard_dns"]


def raw_connect(host, port):
    """Connect without a DNS lookup first (create_connection would look the IP up, and
    the DNS check would refuse it before the connect check is ever reached)."""
    with socket.socket() as s:
        s.settimeout(0.5)
        s.connect((host, port))


def test_connecting_to_a_literal_ip_is_refused(server):
    port, accepted = server
    refusals = []

    # 192.0.2.1 is reserved for documentation and never routed, so even if the guard
    # failed, nothing would be reached (the connect would time out instead).
    with guarded_run(allow=[("localhost", port)], on_refusal=refusals.append):
        with pytest.raises(NetworkGuardError):
            raw_connect("192.0.2.1", 443)

    assert refusals == ["guard_connect"]


def test_an_allowed_host_and_port_works(server):
    port, accepted = server

    with guarded_run(allow=[("localhost", port)]):
        assert fetch("localhost", port) == b"ok"

    assert len(accepted) == 1


def test_another_port_on_an_allowed_host_is_refused(server):
    port, accepted = server
    refusals = []

    with guarded_run(allow=[("localhost", port + 1)], on_refusal=refusals.append):
        with pytest.raises(NetworkGuardError):
            raw_connect("127.0.0.1", port)  # the right address, the wrong port

    assert refusals == ["guard_connect"] and accepted == []


def test_an_allowed_host_whose_address_changed_still_works(server, monkeypatch):
    port, _ = server
    real = guard._resolve
    answers = iter([{("10.9.9.9", port)}])  # the first lookup: an address that's gone since

    monkeypatch.setattr(guard, "_resolve", lambda h, p: next(answers, None) or real(h, p))

    with guarded_run(allow=[("localhost", port)]):
        assert fetch("localhost", port) == b"ok"  # refreshed on the miss, then allowed


@pytest.mark.parametrize("kind", ["unix", "udp"])
def test_unix_sockets_and_udp_sends_are_refused(kind):
    with guarded_run(), pytest.raises(NetworkGuardError):
        if kind == "unix":
            with socket.socket(socket.AF_UNIX) as s:
                # Short and relative: macOS caps socket paths at 104 characters. It never
                # exists, so without the guard this raises FileNotFoundError instead.
                s.connect("daemon.sock")
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(b"data", ("127.0.0.1", 9))


@pytest.mark.parametrize("how", ["subprocess", "os_system"])
def test_starting_a_process_is_refused(how, tmp_path):
    marker = tmp_path / "ran"
    command = f"touch {marker}"

    with guarded_run(), pytest.raises(NetworkGuardError):
        if how == "subprocess":
            subprocess.run(["touch", str(marker)], check=False)
        else:
            os.system(command)

    assert not marker.exists()


@pytest.mark.parametrize("event", ["os.exec", "os.fork", "os.posix_spawn", "os.spawn"])
def test_process_events_that_would_replace_or_copy_this_process_are_refused(event):
    # Calling os.exec* or os.fork for real would replace or copy the test process if the
    # guard failed, so the hook is checked directly with the event it would receive.
    with guarded_run(), pytest.raises(NetworkGuardError):
        guard._hook(event, ())


def test_loading_native_code_with_ctypes_is_refused():
    refusals = []

    with guarded_run(on_refusal=refusals.append), pytest.raises(NetworkGuardError):
        ctypes.CDLL(None)

    assert refusals == ["guard_native_code"]


def test_threads_started_in_a_run_are_guarded_too():
    errors = []

    def reach_out():
        try:
            socket.getaddrinfo("example.invalid", 443)
        except NetworkGuardError as e:
            errors.append(e)

    with guarded_run():
        thread = threading.Thread(target=reach_out)
        thread.start()
        thread.join()

    assert len(errors) == 1


def test_guard_is_off_after_a_run_even_after_an_exception(tmp_path):
    with pytest.raises(RuntimeError), guarded_run():
        raise RuntimeError("the run failed")

    marker = tmp_path / "ran"
    subprocess.run(["touch", str(marker)], check=True)  # allowed again outside runs
    assert marker.exists()
    assert guard._runs == []
