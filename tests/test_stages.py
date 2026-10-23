from fastapi.testclient import TestClient

from brain_dock.main import app
from brain_dock.modules.job_search.models import Stage
from brain_dock.modules.job_search.stages import (
    KINDS,
    STAGES,
    recordable_stages,
    stage_css,
    stage_label,
)

from .conftest import BASE_URL


def test_every_stage_has_metadata():
    assert set(STAGES) == set(Stage)


def test_pipeline_order_is_unique_and_starts_with_applied():
    orders = [info.order for info in STAGES.values()]

    assert sorted(orders) == list(range(len(Stage)))
    assert min(STAGES, key=lambda s: STAGES[s].order) == Stage.applied


def test_kinds_are_known_and_offer_is_the_win():
    assert {info.kind for info in STAGES.values()} <= KINDS
    assert [s for s, i in STAGES.items() if i.kind == "won"] == [Stage.offer]


def test_labels_and_recordable_stages():
    assert stage_label("screen") == "Screen"
    assert Stage.applied not in recordable_stages()
    assert recordable_stages()[0] == Stage.screen
    assert len(recordable_stages()) == len(Stage) - 1


def test_css_has_light_and_dark_colors_for_every_stage():
    css = stage_css()

    for stage, info in STAGES.items():
        assert f".stage-{stage.value} {{ color: {info.color}; }}" in css
        assert f".stage-{stage.value} {{ color: {info.dark_color}; }}" in css
    assert "@media (prefers-color-scheme: dark)" in css


def test_stage_css_is_served_and_linked():
    client = TestClient(app, base_url=BASE_URL)

    response = client.get("/stages.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.text == stage_css()
    assert '<link rel="stylesheet" href="/stages.css">' in client.get("/applications/new").text
