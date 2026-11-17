"""The e2e server runs on a throwaway database, never on real data."""

import sqlite3

import pytest

from e2e.support import REPO_ROOT, RealDataError, fetch, guard_temp_db


def test_guard_refuses_repo_data_paths(tmp_path_factory, monkeypatch):
    def no_connect(*_args, **_kwargs):
        raise AssertionError("the guard opened a database")

    monkeypatch.setattr(sqlite3, "connect", no_connect)
    temp_root = tmp_path_factory.getbasetemp()
    never_created = REPO_ROOT / "data" / "e2e-guard-probe.db"
    refused = [
        REPO_ROOT / "data" / "demo.db",
        REPO_ROOT / "data" / "brain_dock.db",
        never_created,
        temp_root / ".." / "escaped.db",  # resolves outside the temp folder
    ]
    for path in refused:
        with pytest.raises(RealDataError):
            guard_temp_db(path, temp_root)
    # A temp folder inside the repo (a --basetemp there) is refused too.
    with pytest.raises(RealDataError, match="outside the repo"):
        guard_temp_db(REPO_ROOT / "e2e-tmp" / "demo.db", REPO_ROOT)
    assert not never_created.exists()
    # The allow-list does let a temp file through, so the refusals above mean something.
    assert guard_temp_db(temp_root / "ok.db", temp_root) == (temp_root / "ok.db").resolve()


def test_e2e_server_uses_a_temp_database(server):
    assert server.db_path.is_relative_to(server.temp_root.resolve())
    assert not server.db_path.is_relative_to(REPO_ROOT)
    assert server.db_path.exists()
    assert server.marker in fetch(f"{server.url}/companies/{server.marker_id}")
