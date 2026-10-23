import html

import pytest
from fastapi.testclient import TestClient

from brain_dock import main
from brain_dock.core.security import CONTENT_SECURITY_POLICY
from brain_dock.main import app, get_session

from .conftest import BASE_URL, SECRET


@pytest.mark.parametrize(
    ("method", "path", "status", "title"),
    [
        ("get", "/does-not-exist", 404, "Page not found"),
        ("get", "/applications/999/edit", 404, "Page not found"),
        ("get", f"/applications/{SECRET}/edit", 422, "That request didn't make sense"),
        ("get", "/applications/1", 405, "That action isn't available here"),
        ("post", "/applications", 403, "That form wasn't accepted"),
    ],
)
def test_errors_are_html_pages(client, method, path, status, title):
    response = getattr(client, method)(path)

    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    assert f"<h1>{title}</h1>" in html.unescape(response.text)
    assert 'href="/applications"' in response.text  # a way back
    assert SECRET not in response.text
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_not_found_never_echoes_the_path(client):
    response = client.get(f"/{SECRET}")

    assert response.status_code == 404
    assert SECRET not in response.text


def test_unexpected_error_is_a_plain_500_page(session, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError(f"database exploded {SECRET}")

    monkeypatch.setattr(main, "list_applications", broken)
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app, base_url=BASE_URL, raise_server_exceptions=False)
    response = client.get("/applications")
    app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Something went wrong</h1>" in html.unescape(response.text)
    for leak in [SECRET, "RuntimeError", "Traceback", "database exploded"]:
        assert leak not in response.text
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
