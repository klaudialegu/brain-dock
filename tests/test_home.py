from fastapi.testclient import TestClient

from brain_dock.main import app

from .conftest import BASE_URL

client = TestClient(app, base_url=BASE_URL)


def test_home_redirects_to_the_pipeline():
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/applications"


def test_static_css_is_served():
    response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--accent" in response.text


def test_pages_use_the_static_css():
    html = client.get("/applications/new").text

    assert '<link rel="stylesheet" href="/static/app.css">' in html
