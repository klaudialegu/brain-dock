import json
import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from brain_dock.charts import pipeline_chart_data, pipeline_summary
from brain_dock.main import app, get_session
from brain_dock.models import (
    RoleTrack,
    Stage,
    create_application,
    get_or_create_company,
    record_stage,
)
from brain_dock.queries import PipelineLink
from brain_dock.stages import STAGES

from .conftest import BASE_URL


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, base_url=BASE_URL)
    app.dependency_overrides.clear()


def add(session, company, role, applied_on, *stages):
    application = create_application(
        session, get_or_create_company(session, company), role, RoleTrack.fde, applied_on
    )
    for i, stage in enumerate(stages, start=1):
        record_stage(session, application, stage, applied_on + timedelta(days=i))
    session.commit()


def chart_json(html):
    block = re.search(
        r'<script type="application/json" id="pipeline-data">(.*?)</script>', html, re.S
    )
    return json.loads(block.group(1)) if block else None


OLD = date.today() - timedelta(days=30)


# --- Chart data --------------------------------------------------------------


def test_chart_data_uses_stage_labels_and_colors_only():
    links = [
        PipelineLink(Stage.applied, Stage.screen, 2),
        PipelineLink(Stage.screen, Stage.rejected, 1),
    ]

    data = pipeline_chart_data(links)

    assert data["nodes"] == [
        {
            "name": "Applied",
            "color": STAGES[Stage.applied].color,
            "darkColor": STAGES[Stage.applied].dark_color,
        },
        {
            "name": "Screen",
            "color": STAGES[Stage.screen].color,
            "darkColor": STAGES[Stage.screen].dark_color,
        },
        {
            "name": "Rejected",
            "color": STAGES[Stage.rejected].color,
            "darkColor": STAGES[Stage.rejected].dark_color,
        },
    ]
    assert data["links"] == [
        {"source": "Applied", "target": "Screen", "value": 2},
        {"source": "Screen", "target": "Rejected", "value": 1},
    ]
    assert pipeline_summary(links) == "Applied to Screen: 2; Screen to Rejected: 1"


def test_empty_chart_data():
    assert pipeline_chart_data([]) == {"nodes": [], "links": []}


# --- The page ----------------------------------------------------------------


def test_page_shows_stats_and_chart(client, session):
    add(session, "Acme Analytics", "Engineer", OLD, Stage.screen, Stage.interview)
    add(session, "Globex Systems", "Lead", OLD, Stage.ghosted)
    add(session, "Initech", "Support", date.today())

    html = client.get("/applications").text

    assert "Response rate" in html
    assert "1 of 2 applications older than 14 days" in html
    assert ">50%<" in html
    assert "1 of 3 reached an interview" in html and ">33%<" in html
    assert "Since last application" in html
    data = chart_json(html)
    assert {(link["source"], link["target"]) for link in data["links"]} == {
        ("Applied", "Screen"),
        ("Screen", "Interview"),
        ("Applied", "Ghosted"),
    }
    assert 'aria-label="Pipeline: Applied to Screen: 1;' in html


def test_chart_data_never_contains_company_or_role_names(client, session):
    add(session, "Acme Analytics", "Secret Role Title", OLD, Stage.screen)

    block = re.search(r'id="pipeline-data">(.*?)</script>', client.get("/applications").text, re.S)

    assert block  # the block exists, so the check below means something
    assert "Acme" not in block.group(1) and "Secret Role" not in block.group(1)


def test_chart_scripts_load_from_this_app_in_order(client, session):
    add(session, "Acme Analytics", "Engineer", OLD, Stage.screen)

    html = client.get("/applications").text
    echarts = html.index(
        '<script src="/static/vendor/echarts-6.1.0/echarts.min.js" defer></script>'
    )
    pipeline = html.index('<script src="/static/pipeline.js" defer></script>')

    assert echarts < pipeline


def test_no_chart_until_an_application_moves_past_applied(client, session):
    add(session, "Acme Analytics", "Engineer", OLD)

    html = client.get("/applications").text

    assert "The pipeline appears once an application moves past Applied." in html
    assert chart_json(html) is None
    assert "echarts.min.js" not in html
    assert "Response rate" in html  # the stats still show


def test_new_applications_only_show_a_labelled_dash_for_response_rate(client, session):
    add(session, "Acme Analytics", "Engineer", date.today(), Stage.screen)

    html = client.get("/applications").text

    assert "No application is 14 days old yet" in html


def test_empty_list_has_no_stats_or_chart(client):
    html = client.get("/applications").text

    assert "Response rate" not in html
    assert "pipeline-data" not in html
    assert "Add your first application" in html


def test_pipeline_script_is_served(client):
    response = client.get("/static/pipeline.js")

    assert response.status_code == 200
    assert "renderMode" in response.text  # canvas tooltips, no inline styles (CSP)
