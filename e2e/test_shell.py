"""The shell in a real browser (ADR 0016): modules on and off in Settings, and a saved
layout that survives a reload. The e2e server is shared, so each test puts back what it
changed."""

import re
from itertools import pairwise, product

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

    page.goto("/settings")  # put it back for the other tests, and check it really is back:
    # the e2e server is shared, so a half-restored layout breaks every later Home test
    settings_row(page, "Career Radar").get_by_role(
        "button", name=re.compile("Move .* down")
    ).click()
    page.wait_for_load_state()
    assert card_order(page) == before  # (this opens Home)
    page.goto("/settings")
    settings_row(page, "Career Radar").get_by_label(re.compile("Width of")).select_option("L")
    settings_row(page, "Career Radar").get_by_role("button", name=re.compile("Set width")).click()
    page.wait_for_load_state()
    page.goto("/")
    expect(page.locator("section.card.size-L", has_text="Career Radar")).to_be_visible()


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


def card_positions(page) -> list[tuple[str, dict]]:
    """Home's cards in page order (the Settings order), each with its box."""
    page.goto("/")
    expect(page.locator(".grid[data-pack]")).to_have_class(re.compile(r"\bpacked\b"))
    page.wait_for_timeout(150)  # let packing settle after fonts
    return [
        (card.locator(".tape").inner_text(), card.bounding_box())
        for card in page.locator("section.card").all()
    ]


def set_widths(page, widths: dict[str, str]) -> None:
    """Set card widths through the Settings form's own POST (CSRF token and all)."""
    page.goto("/settings")
    token = page.locator('input[name="csrf_token"]').first.get_attribute("value")
    origin = re.match(r"https?://[^/]+", page.url).group(0)
    for card_id, size in widths.items():
        response = page.request.post(
            f"/settings/cards/{card_id}/size",
            form={"size": size, "csrf_token": token},
            headers={"Origin": origin},
            max_redirects=0,
        )
        assert response.status == 303, (card_id, size, response.status)


DEFAULT_WIDTHS = {"todo": "W", "brief": "M", "job_search": "L", "inbox": "S"}
WIDTH_CHOICES = {"todo": "LW", "brief": "ML", "job_search": "MLW", "inbox": "SM"}


def test_cards_keep_the_settings_order_at_every_width(page):
    """Packing may tuck a card under a shorter neighbour, but it never reorders: reading
    top to bottom, then left to right, gives the Settings order. Checked for every width
    combination Settings offers (the Scratchpad has one width)."""
    combos = list(product(*(WIDTH_CHOICES[c] for c in WIDTH_CHOICES)))
    assert len(combos) == 24
    try:
        for combo in combos:
            widths = dict(zip(WIDTH_CHOICES, combo, strict=True))
            set_widths(page, widths)
            cards = card_positions(page)
            assert len(cards) == 5, widths
            for (name_a, a), (name_b, b) in pairwise(cards):
                same_row = abs(b["y"] - a["y"]) <= 4  # tilted cards: a few px
                assert b["y"] > a["y"] - 4, (widths, name_a, name_b)  # never above
                if same_row:
                    assert b["x"] > a["x"], (widths, name_a, name_b)  # then left to right
    finally:
        set_widths(page, DEFAULT_WIDTHS)  # the e2e server is shared: put them back
    assert [n for n, _ in card_positions(page)] == [
        "To do",
        "Brief",
        "Career Radar",
        "Inbox",
        "Scratchpad",
    ]


def test_home_keeps_card_order_and_no_row_leaves_a_hole(page):
    """With the default widths: cards read in the Settings order, and no row leaves a
    hole: each row starts at the grid's left edge, the cards in it sit one grid gap apart,
    and the row ends at the right edge. (Other width choices can leave a hole; see the
    plan's "PR 3 as built".)"""
    page.goto("/")
    expect(page.locator(".grid[data-pack]")).to_have_class(re.compile(r"\bpacked\b"))
    grid = page.locator(".grid[data-pack]").bounding_box()
    cards = []
    for card in page.locator("section.card").all():  # in page order: the Settings order
        box = card.bounding_box()
        cards.append((card.locator(".tape").inner_text(), box))
    assert len(cards) >= 4  # the check really covers several cards

    rows: list[list[tuple[str, dict]]] = []  # cards whose tops line up (tilted ones: ±8px)
    for name, box in cards:
        for row in rows:
            if abs(row[0][1]["y"] - box["y"]) <= 8:
                row.append((name, box))
                break
        else:
            rows.append([(name, box)])
    reading = [
        name
        for row in sorted(rows, key=lambda r: r[0][1]["y"])
        for name, _ in sorted(row, key=lambda c: c[1]["x"])
    ]
    assert reading == [name for name, _ in cards]  # order kept

    for row in rows:
        row.sort(key=lambda c: c[1]["x"])
        assert abs(row[0][1]["x"] - grid["x"]) < 3, row[0][0]  # starts at the left edge
        for (left, a), (right, b) in pairwise(row):
            gap = b["x"] - (a["x"] + a["width"])
            assert 18 <= gap <= 26, (left, right, gap)  # one grid gap, no hole
        last, box = row[-1]
        assert abs(box["x"] + box["width"] - (grid["x"] + grid["width"])) < 3, last  # right edge


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
