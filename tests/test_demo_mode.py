from fastapi.testclient import TestClient

from brain_dock import db
from brain_dock.db import DEFAULT_DB_PATH, DEMO_DB_PATH, database_path, get_engine, is_demo_database
from brain_dock.importer import load_applications, rebuild_db
from brain_dock.main import app

from .conftest import BASE_URL

BANNER = "You're looking at fake demo data"


def test_default_database_without_the_setting():
    assert database_path({}) == DEFAULT_DB_PATH
    assert database_path({"BRAIN_DOCK_DB": "  "}) == DEFAULT_DB_PATH


def test_setting_picks_the_database(tmp_path):
    assert database_path({"BRAIN_DOCK_DB": str(tmp_path / "x.db")}) == tmp_path / "x.db"


def test_relative_setting_is_taken_from_the_current_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert (
        database_path({"BRAIN_DOCK_DB": "data/demo.db"})
        == (tmp_path / "data" / "demo.db").resolve()
    )


def test_demo_database_is_recognized(tmp_path):
    assert is_demo_database(DEMO_DB_PATH)
    assert not is_demo_database(DEFAULT_DB_PATH)
    assert not is_demo_database(tmp_path / "demo.db")  # same name elsewhere isn't the demo


def serve(monkeypatch, path, demo_path):
    """Run the real startup against `path`, with `demo_path` counting as the demo database."""
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "DEMO_DB_PATH", demo_path)
    engine = get_engine(f"sqlite:///{path}")
    rebuild_db(engine, load_applications(db.REPO_ROOT / "demo" / "applications.json"), locked=False)
    engine.dispose()
    return TestClient(app, base_url=BASE_URL)


def test_demo_database_shows_the_banner(tmp_path, monkeypatch):
    demo = tmp_path / "demo.db"

    with serve(monkeypatch, demo, demo) as client:
        html = client.get("/applications").text

    assert BANNER in html
    assert "Acme Analytics" in html  # and the demo data itself


def test_real_database_has_no_banner(tmp_path, monkeypatch):
    with serve(monkeypatch, tmp_path / "brain_dock.db", tmp_path / "demo.db") as client:
        html = client.get("/applications").text

    assert BANNER not in html
    assert "Acme Analytics" in html  # the page did render data, so the absence means something
