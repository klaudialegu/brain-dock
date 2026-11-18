"""The one-time message bar (ADR 0018): shown once, holds no text, ignores junk."""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from brain_dock.core.flash import COOKIE, clear_message, read_message, set_message


def tiny_app() -> FastAPI:
    app = FastAPI()

    @app.get("/set")
    def set_it():
        response = PlainTextResponse("set")
        set_message(response, "task_removed", 7)
        return response

    @app.get("/page")
    def page(request: Request):
        waiting = read_message(request)
        response = PlainTextResponse(repr(waiting))
        clear_message(request, response)
        return response

    return app


def test_message_shows_once_then_clears(client):
    with TestClient(tiny_app(), base_url="http://127.0.0.1") as c:
        c.get("/set")
        assert c.get("/page").text == "('task_removed', 7)"
        assert c.get("/page").text == "None"  # a reload doesn't repeat it
    # and the app's own pages clear it too: any rendered page is its one showing
    client.cookies.set(COOKIE, "task_removed:7")
    response = client.get("/settings")
    assert (
        COOKIE in response.headers.get("set-cookie", "")
        and "Max-Age=0" in response.headers["set-cookie"]
    )


def test_message_cookie_holds_no_text_and_rejects_junk():
    with TestClient(tiny_app(), base_url="http://127.0.0.1") as c:
        cookie = c.get("/set").headers["set-cookie"]
        assert cookie.startswith(f"{COOKIE}=task_removed:7;")  # a kind and an id, no title
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        for junk in ["Removed: Water the plants", "task_removed:x", "a" * 40, "<script>", ""]:
            c.cookies.clear()
            c.cookies.set(COOKIE, junk)
            assert c.get("/page").text == "None"
    with pytest.raises(ValueError):
        set_message(PlainTextResponse(""), "Removed: a title")
