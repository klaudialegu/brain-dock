from brain_dock.modules.job_search.models import Stage
from brain_dock.modules.job_search.stages import (
    KINDS,
    STAGES,
    recordable_stages,
    stage_css,
    stage_label,
)


def test_every_stage_has_metadata():
    assert set(STAGES) == set(Stage)


def test_pipeline_order_is_unique_and_starts_with_applied():
    orders = [info.order for info in STAGES.values()]
    applications = [s for s in STAGES if STAGES[s].kind != "saved"]

    assert sorted(orders) == list(range(len(Stage)))
    # Interested comes first but isn't an application; the pipeline starts at applied.
    assert [s for s in STAGES if STAGES[s].kind == "saved"] == [Stage.interested]
    assert min(STAGES, key=lambda s: STAGES[s].order) == Stage.interested
    assert min(applications, key=lambda s: STAGES[s].order) == Stage.applied


def test_kinds_are_known_and_offer_is_the_win():
    assert {info.kind for info in STAGES.values()} <= KINDS
    assert [s for s, i in STAGES.items() if i.kind == "won"] == [Stage.offer]


def test_labels_and_recordable_stages():
    assert stage_label("screen") == "Screen"
    assert Stage.applied not in recordable_stages()
    assert Stage.interested not in recordable_stages()  # only from saving a job
    assert recordable_stages()[0] == Stage.screen
    assert len(recordable_stages()) == len(Stage) - 2


def test_css_has_a_color_for_every_stage_light_only():
    css = stage_css()

    for stage, info in STAGES.items():
        assert f".stage-{stage.value} {{ color: {info.color}; }}" in css
    assert "prefers-color-scheme" not in css  # one light look for now (ADR 0016)


def test_stage_css_is_served_and_linked(client):  # the fixture: pages read the layout

    response = client.get("/stages.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.text == stage_css()
    assert '<link rel="stylesheet" href="/stages.css">' in client.get("/applications/new").text


def test_stage_colors_are_warm_and_readable():
    from brain_dock.core.palette import CARD, PALETTE, contrast

    inks = {c.ink for c in PALETTE.values()}
    for stage, info in STAGES.items():
        assert contrast(info.color, "#F3EEE5") >= 4.5, stage  # chip text on its cream badge
        assert contrast(info.chart, CARD) >= 3, stage  # a chart node on the card
        if info.kind in ("saved", "active", "won") and stage != Stage.applied:
            assert info.chart in inks, stage  # the module inks, not a cool blue-grey
    greys = [STAGES[s].chart for s in STAGES if STAGES[s].kind == "closed"]
    for grey in greys:  # warm: red channel at or above blue
        assert int(grey[1:3], 16) >= int(grey[5:7], 16), grey


def test_each_open_stage_has_its_own_color():
    open_stages = [s for s, i in STAGES.items() if i.kind in ("saved", "active", "won")]
    chips = [STAGES[s].color for s in open_stages if s != Stage.applied]
    charts = [STAGES[s].chart for s in open_stages]
    assert len(set(chips)) == len(chips)  # interested and interview no longer look alike
    assert len(set(charts)) == len(charts)
