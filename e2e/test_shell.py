"""The shell in a real browser (ADR 0016): modules on and off in Settings, and a saved
layout that survives a reload. The e2e server is shared, so each test puts back what it
changed."""

import re

import pytest
from playwright.sync_api import expect

from e2e.support import settle


def card_order(page) -> list[str]:
    page.goto("/")
    return page.locator("section.card .tape").all_inner_texts()


def settings_row(page, label: str):
    return page.locator("li.settings-row").filter(has=page.locator(".tape", has_text=label))


def test_module_off_and_on_in_settings(page):
    page.goto("/")
    rail = page.get_by_role("navigation", name="Main")
    expect(rail.get_by_role("link", name="Inbox")).to_be_visible()
    assert "Inbox" in card_order(page)

    page.goto("/settings")
    settings_row(page, "Inbox").get_by_role("button", name=re.compile(r"^Shown")).click()
    expect(
        settings_row(page, "Inbox").get_by_role("button", name=re.compile(r"^Hidden"))
    ).to_be_visible()

    assert "Inbox" not in card_order(page)  # off Home
    expect(
        page.get_by_role("navigation", name="Main").get_by_role("link", name="Inbox")
    ).to_have_count(0)  # and out of the rail
    page.goto("/inbox")
    expect(page.get_by_role("heading", level=1)).to_be_visible()  # its page stays

    page.goto("/settings")
    settings_row(page, "Inbox").get_by_role("button", name=re.compile(r"^Hidden")).click()
    assert "Inbox" in card_order(page)
    expect(
        page.get_by_role("navigation", name="Main").get_by_role("link", name="Inbox")
    ).to_be_visible()


def test_layout_persists_after_reload(page):
    before = card_order(page)
    assert before.index("Career Radar") > before.index("Brief")

    page.goto("/settings")
    settings_row(page, "Career Radar").get_by_role("button", name=re.compile("Move .* up")).click()
    settings_row(page, "Career Radar").get_by_label(re.compile("Width of")).select_option("M")
    settings_row(page, "Career Radar").get_by_role("button", name=re.compile("Set width")).click()

    page.reload()
    after = card_order(page)
    assert after.index("Career Radar") == before.index("Career Radar") - 1
    page.goto("/")
    expect(page.locator("section.card.size-M", has_text="Career Radar")).to_be_visible()
    rail = page.get_by_role("navigation", name="Main").get_by_role("link")
    labels = [rail.nth(i).get_attribute("aria-label") for i in range(rail.count())]
    assert labels.index("Career Radar") < labels.index("Brief")  # the rail follows Home

    page.goto("/settings")  # put it back for the other tests
    settings_row(page, "Career Radar").get_by_role(
        "button", name=re.compile("Move .* down")
    ).click()
    settings_row(page, "Career Radar").get_by_label(re.compile("Width of")).select_option("L")
    settings_row(page, "Career Radar").get_by_role("button", name=re.compile("Set width")).click()
    assert card_order(page) == before


def test_every_button_is_a_pill_on_every_page(page):
    from e2e.support import PAGES, open_named_page

    seen = 0
    for name in PAGES:
        open_named_page(page, name)
        radii = page.eval_on_selector_all(
            ".button, .button-quiet, .play-brief",
            "els => els.map(e => [e.textContent.trim().slice(0, 30), "
            "getComputedStyle(e).borderTopLeftRadius])",
        )
        for label, radius in radii:
            assert radius == "999px", f"{name}: {label!r} has radius {radius}"
        seen += len(radii)
    assert seen > 20  # the check really covered buttons across the pages


def test_home_packs_cards_without_gaps(page):
    page.goto("/")
    expect(page.locator(".grid[data-pack]")).to_have_class(re.compile(r"\bpacked\b"))

    def box(label):
        return page.locator(
            "section.card", has=page.locator(".tape", has_text=label)
        ).bounding_box()

    todo, brief, radar = box("To do"), box("Brief"), box("Career Radar")
    assert brief["height"] > todo["height"]  # the case packing is for: a taller neighbour
    assert abs(radar["x"] - todo["x"]) < 2  # Career Radar sits in To do's column…
    gap = radar["y"] - (todo["y"] + todo["height"])
    assert 18 <= gap <= 26, gap  # …right under it (the 22px grid gap), not under Brief


@pytest.mark.parametrize("width", [1280, 2560])
def test_add_module_tile_lines_up_with_the_card_above(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto("/")
    settle(page)
    tile = page.locator(".add-module").bounding_box()
    boxes = [
        page.locator("section.card").nth(i).bounding_box()
        for i in range(page.locator("section.card").count())
    ]
    above = [
        b for b in boxes if b["y"] + b["height"] <= tile["y"] + 1 and abs(b["x"] - tile["x"]) < 4
    ]
    assert above, "the tile sits under a card"
    card = max(above, key=lambda b: b["y"])
    assert abs(card["x"] - tile["x"]) <= 1  # left edges line up
    assert abs(card["width"] - tile["width"]) <= 1  # and so do the right edges
