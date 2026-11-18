"""The Scratchpad (ADR 0017): pages by day, layers, pens and paper, quick capture."""

import hashlib
import logging
import re
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from brain_dock.core import db
from brain_dock.core.db import get_engine, migrate
from brain_dock.core.palette import contrast
from brain_dock.modules.scratchpad import demo
from brain_dock.modules.scratchpad.models import (
    PAPER_COLORS,
    PENS,
    ScratchpadError,
    ScratchpadLayer,
    ScratchpadPage,
    append_line,
    new_page,
    pages_by_day,
    revision,
    set_style,
    set_text,
    text_layer,
    with_new_lines,
)

from .conftest import BASE_URL, SECRET

TODAY = date.today()


def post(client, path, data, follow=False):
    page = client.get("/scratchpad").text if not follow else ""
    token = re.search(r'name="csrf_token" value="([^"]+)"', page or client.get("/").text)
    return client.post(
        path,
        data={**data, "csrf_token": token.group(1)},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )


def save(client, page_id, text, script=False, base=None):
    """Save a page's text the way its form does: with the CSRF token and the text's
    fingerprint (base) from the page as loaded."""
    html = client.get(f"/scratchpad/{page_id}").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    loaded = re.search(r'name="base" value="([0-9a-f]*)"', html).group(1)
    return client.post(
        f"/scratchpad/{page_id}/text",
        data={"text": text, "csrf_token": token, "base": loaded if base is None else base},
        headers={"Origin": BASE_URL, **({"x-scratchpad-save": "1"} if script else {})},
        follow_redirects=False,
    )


def pages(session):
    session.expire_all()
    return session.exec(select(ScratchpadPage).order_by(ScratchpadPage.id)).all()


def test_pages_by_day_and_new_page(client, session):
    old = new_page(session, TODAY - timedelta(days=3))
    first = new_page(session, TODAY)
    session.commit()
    set_style(first, pen="gel", paper="kraft")
    session.commit()

    response = post(client, "/scratchpad/pages", {})
    assert response.status_code == 303
    second = pages(session)[-1]
    assert (second.day, second.position) == (TODAY, 2)
    assert (second.pen, second.paper) == ("gel", "kraft")  # carries over from the day's page
    assert [(d, [p.position for p in ps]) for d, ps in pages_by_day(session)] == [
        (TODAY, [1, 2]),
        (old.day, [1]),
    ]
    assert (
        client.get("/scratchpad", follow_redirects=False).headers["location"]
        == f"/scratchpad/{second.id}"
    )
    html = client.get(f"/scratchpad/{second.id}").text
    assert html.count('class="pad-tab"') == 3 and 'aria-current="page"' in html
    session.add(ScratchpadPage(day=TODAY, position=1))
    with pytest.raises(IntegrityError):  # positions are unique within a day
        session.commit()


def test_pen_paper_and_size_are_saved_per_page(client, session):
    a, b = new_page(session, TODAY), new_page(session, TODAY)
    session.commit()

    for data in [{"pen": "rose"}, {"paper": "dotted"}, {"size": "full"}]:
        assert post(client, f"/scratchpad/{a.id}/style", data).status_code == 303
    a, b = pages(session)
    assert (a.pen, a.paper, a.size) == ("rose", "dotted", "full")
    assert (b.pen, b.paper, b.size) == (
        "fineliner",
        "lined",
        "wide",
    )  # the other page keeps its own
    html = client.get(f"/scratchpad/{a.id}").text
    assert 'class="pad-sheet paper-dotted size-full"' in html and "pen-rose" in html
    for bad in [{"pen": "eraser"}, {"pen": "crayon"}, {"paper": "napkin"}, {"size": "huge"}]:
        assert post(client, f"/scratchpad/{a.id}/style", bad).status_code == 400
    assert post(client, "/scratchpad/999/style", {"pen": "gel"}).status_code == 404


def test_text_is_a_layer_and_layers_keep_their_order(client, session):
    page = new_page(session, TODAY)
    session.commit()
    assert [(layer.kind, layer.position) for layer in page.layers] == [("text", 0)]

    assert save(client, page.id, "first line\r\nsecond").status_code == 303
    by_script = save(client, page.id, "autosaved", script=True)
    assert by_script.status_code == 204  # the autosave script gets no page back
    assert by_script.headers["x-scratchpad-base"] == revision(pages(session)[0])  # its next base
    page = pages(session)[0]
    assert text_layer(page).content == "autosaved"
    session.add(ScratchpadLayer(page_id=page.id, kind="ink", position=1))  # a future layer
    session.commit()
    session.refresh(page)
    assert [layer.kind for layer in page.layers] == ["text", "ink"]  # bottom first
    with pytest.raises(ScratchpadError):
        set_text(page, "x" * 20_001)


def test_capture_appends_to_todays_page(client, session):
    home = client.get("/").text
    assert 'action="/scratchpad/capture"' in home and 'id="quick-capture"' in home

    response = post(client, "/scratchpad/capture", {"text": "  buy   stamps "})
    assert response.status_code == 303 and response.headers["location"] == "/"
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").text).group(1)
    by_script = client.post(
        "/scratchpad/capture",
        data={"text": "call back", "csrf_token": token},
        headers={"Origin": BASE_URL, "x-scratchpad-capture": "1"},
    )
    assert by_script.status_code == 204  # a page's own script stays where it is
    [page] = pages(session)
    assert (page.day, text_layer(page).content) == (TODAY, "buy stamps\ncall back")
    for unsafe in ["https://example.com/", "//example.com/x", "/\texample.com", "/\t/example.com"]:
        r = post(client, "/scratchpad/capture", {"text": "x", "next": unsafe})
        assert r.status_code == 303 and r.headers["location"] == "/"  # a request never picks it
    assert post(client, "/scratchpad/capture", {"text": "   "}).status_code == 303
    assert text_layer(pages(session)[0]).content.count("\n") == 5  # the empty one added nothing
    with pytest.raises(ScratchpadError):
        append_line(session, TODAY, "")


def test_typed_text_never_appears_in_logs(client, session, caplog):
    caplog.set_level(logging.DEBUG)
    page = new_page(session, TODAY)
    session.commit()

    assert save(client, page.id, f"{SECRET} note").status_code == 303
    post(client, "/scratchpad/capture", {"text": f"{SECRET} capture"})
    assert save(client, page.id, SECRET * 2_000).status_code == 400  # too long: an error
    assert "at most 20,000 characters" in save(client, page.id, SECRET * 2_000).text  # shown
    assert save(client, page.id, SECRET, base="0" * 16).status_code == 409  # stale: an error
    post(client, f"/scratchpad/{page.id}/style", {"pen": SECRET})

    assert caplog.records  # the capture works: something was logged
    assert SECRET not in caplog.text
    for refused in [save(client, page.id, SECRET * 2_000), save(client, page.id, SECRET, base="0")]:
        errors = re.findall(r'<div class="form-errors"[^>]*>(.*?)</div>', refused.text, re.S)
        assert errors and all(SECRET not in e for e in errors)


def test_pen_inks_read_at_4_5_to_1_on_every_paper():
    for pen in PENS.values():
        for paper, color in PAPER_COLORS.items():
            assert contrast(pen.ink, color) >= 4.5, (pen.key, paper)
    assert contrast("#1D1B18", "#C9E3CF") >= 4.5  # the highlighter: ink on its sage swipe
    css = (db.REPO_ROOT / "src/brain_dock/modules/scratchpad/static/scratchpad.css").read_text()
    for pen in PENS.values():
        if pen.available:
            assert f".pen-{pen.key} {{ color: {pen.ink};" in css  # the page uses those inks


def test_scratchpad_never_reaches_the_brief(client, session):
    from brain_dock import registry
    from brain_dock.core.brief import lines_by_module

    page = new_page(session, TODAY)
    set_text(page, f"{SECRET} private line")
    session.commit()

    assert registry.INSTALLED["scratchpad"].brief is None  # no brief contributor at all
    lines = lines_by_module(session, TODAY, registry.installed())
    assert all(SECRET not in line for ls in lines.values() for line in ls)
    assert SECRET not in client.get("/brief").text


def test_scratchpad_demo_writes_only_the_demo_database(tmp_path, monkeypatch):
    real = db.DB_PATH  # the test's stand-in for data/brain_dock.db (conftest)
    engine = get_engine()
    migrate(engine)
    engine.dispose()
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    demo_db = tmp_path / "demo" / "demo.db"

    assert "isn't ready" in demo.load_demo(demo_db)  # no file: nothing created
    assert not demo_db.exists()
    demo_db.parent.mkdir()
    engine = get_engine(f"sqlite:///{demo_db}")
    migrate(engine)
    engine.dispose()

    monkeypatch.setenv("BRAIN_DOCK_DB", str(real))
    monkeypatch.setattr(db, "DEMO_DB_PATH", demo_db)
    assert demo.main() == 0
    assert "already has" in demo.load_demo(demo_db)
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before


def test_a_stale_page_never_replaces_newer_text(client, session):
    page = new_page(session, TODAY)
    set_text(page, "first")
    session.commit()
    html = client.get(f"/scratchpad/{page.id}").text  # a tab opens the page…
    stale = re.search(r'name="base" value="([0-9a-f]+)"', html).group(1)
    post(client, "/scratchpad/capture", {"text": "captured since"})  # …a note lands…

    by_script = save(client, page.id, "first, edited", script=True, base=stale)
    assert by_script.status_code == 409  # …and the old tab's autosave is refused
    refused = save(client, page.id, "first, edited", base=stale)
    assert refused.status_code == 409
    assert "changed since you opened it" in refused.text
    # the typed text, with the line that landed since added at the end…
    # (the old "first" comes back too: a line kept twice beats a line lost)
    assert ">first, edited\nfirst\ncaptured since</textarea>" in refused.text
    assert "<summary>The page as saved</summary>" in refused.text  # …and the saved page shown
    assert "data-unsaved" in refused.text  # the script knows this text isn't saved yet
    assert text_layer(pages(session)[0]).content == "first\ncaptured since"
    fresh = re.search(r'name="base" value="([0-9a-f]+)"', refused.text).group(1)
    assert save(client, page.id, "first, edited\ncaptured since", base=fresh).status_code == 303
    assert text_layer(pages(session)[0]).content == "first, edited\ncaptured since"
    assert "data-unsaved" not in client.get(f"/scratchpad/{page.id}").text


def test_merging_keeps_typed_text_and_adds_only_new_lines():
    assert with_new_lines("a\nb", "a\nb\nnote") == "a\nb\nnote"
    assert with_new_lines("a, edited\r\nb\n", "a\nb\nnote") == "a, edited\nb\na\nnote"
    assert with_new_lines("", "note") == "note"
    assert with_new_lines("same", "same\n\n") == "same"  # blank lines aren't news


def test_capture_starts_a_new_page_when_the_page_is_full(client, session):
    page = new_page(session, TODAY)
    set_text(page, "x" * 19_990)
    session.commit()

    assert (
        post(client, "/scratchpad/capture", {"text": "a note that would not fit"}).status_code
        == 303
    )
    full, fresh = pages(session)
    assert text_layer(full).content == "x" * 19_990  # untouched
    assert (fresh.position, text_layer(fresh).content) == (2, "a note that would not fit")
    assert post(client, "/scratchpad/capture", {"text": "y" * 2_001}).status_code == 400  # said
    assert 'maxlength="2000"' in client.get("/").text  # the field stops it first
