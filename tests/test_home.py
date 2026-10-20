from fastapi.testclient import TestClient

from brain_dock.main import app

client = TestClient(app)


def test_home_page_loads():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Brain Dock</title>" in response.text
    assert "Everything lands here. One step at a time." in response.text
