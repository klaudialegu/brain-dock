"""Home and the static stylesheet. Every page reads the saved layout, so these use the
`client` fixture (an in-memory database), never a shared app state."""


def test_home_is_a_page_of_cards_not_a_redirect(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert '<div class="grid">' in response.text


def test_static_css_is_served(client):
    response = client.get("/static/app.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--accent" in response.text


def test_pages_use_the_static_css(client):
    html = client.get("/applications/new").text

    assert '<link rel="stylesheet" href="/static/app.css">' in html


# --- Home's cards and the rail (ADR 0016) ------------------------------------------------

import re  # noqa: E402

from .conftest import BASE_URL  # noqa: E402


def form_post(client, path, data):
    page = client.get("/settings").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    return client.post(
        path,
        data={**data, "csrf_token": token},
        headers={"Origin": BASE_URL},
        follow_redirects=False,
    )


def card_ids(html):
    return re.findall(r'aria-labelledby="card-([a-z_]+)"', html)


def test_home_renders_a_card_per_shown_module_in_order(client):
    html = client.get("/").text

    assert card_ids(html) == ["todo", "brief", "job_search", "inbox"]
    assert 'class="card size-W c-graphite state-' in html  # size and color from the manifest
    assert re.search(r'class="tape tilt-\d"[^>]*>To do<', html)
    assert 'href="/settings">' in html and "Add module" in html


def test_card_states_calm_empty_attention(client, session):
    from datetime import date, timedelta

    from brain_dock.modules.job_search.models import create_application, get_or_create_company
    from brain_dock.modules.todo.models import add_task

    empty = client.get("/").text
    assert "c-graphite state-empty" in empty and 'class="dot-grid"' in empty

    add_task(session, "A calm task")
    session.commit()
    assert "c-graphite state-calm" in client.get("/").text

    add_task(session, "Late", due_on=date.today() - timedelta(days=2))
    create_application(
        session,
        get_or_create_company(session, "Example Co"),
        "Role",
        "support",
        date.today() - timedelta(days=9),
        follow_up_on=date.today(),
    )
    session.commit()
    html = client.get("/").text
    assert "c-graphite state-attention" in html and "c-sage state-attention" in html
    assert html.count("Needs you") == 2


def test_attention_is_a_ring_not_red(client):
    css = client.get("/static/app.css").text

    ring = re.search(r"\.card\.state-attention \{([^}]*)\}", css).group(1)
    assert "var(--ink)" in ring  # the module's own ink
    assert not re.search(r"#(?:f00|ff0000|e5|d9|c0392b)|red\b", ring, re.I)
    assert "animation" not in ring and "blink" not in css


def test_rail_lists_modules_in_order_with_settings_last(client):
    html = client.get("/todo").text
    rail = re.search(r'<nav class="rail" aria-label="Main">(.*?)</nav>', html, re.S).group(1)

    labels = re.findall(r'aria-label="([^"]+)"', rail)
    assert labels == ["Home", "To do", "Brief", "Career Radar", "Inbox", "Settings"]
    assert re.search(r'aria-label="To do"[^>]*aria-current="page"', rail)  # this page
    assert rail.count('class="rail-dot"') == 4  # an ink dot per module, not Home or Settings


def test_no_capture_field_when_no_module_captures(client):
    html = client.get("/").text

    assert "Quick capture" not in html and 'name="text"' not in html
