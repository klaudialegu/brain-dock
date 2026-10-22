import pytest
from fastapi.testclient import TestClient

from brain_dock import main
from brain_dock.main import app

from .conftest import BASE_URL

client = TestClient(app, base_url=BASE_URL)


@pytest.fixture(autouse=True)
def no_local_config(tmp_path, monkeypatch):
    # Tests must not depend on the developer's own gitignored config.toml.
    monkeypatch.setattr(main, "CONFIG_PATH", tmp_path / "config.toml")
    return tmp_path / "config.toml"


def test_home_page_loads():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Brain Dock</title>" in response.text
    assert "Everything lands here. One step at a time." in response.text


def test_home_page_shows_default_world_clocks():
    response = client.get("/")

    for city in ["Seattle", "Chicago", "New York", "Warsaw"]:
        assert city in response.text
    assert 'data-reference-tz="America/Los_Angeles"' in response.text


def test_home_page_uses_cities_from_config(no_local_config):
    no_local_config.write_text('[[clocks]]\ncity = "Tokyo"\ntz = "Asia/Tokyo"\n')

    response = client.get("/")

    assert "Tokyo" in response.text
    assert "Seattle" not in response.text
    assert 'data-reference-tz="Asia/Tokyo"' in response.text


@pytest.mark.parametrize(
    ("path", "content_type", "snippet"),
    [
        ("/static/app.css", "text/css", "--accent"),
        ("/static/clocks.js", "javascript", "Intl.DateTimeFormat"),
    ],
)
def test_static_files_are_served(path, content_type, snippet):
    response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    assert snippet in response.text


def test_pages_use_the_static_files():
    html = client.get("/").text

    assert '<link rel="stylesheet" href="/static/app.css">' in html
    assert '<script src="/static/clocks.js" defer></script>' in html
