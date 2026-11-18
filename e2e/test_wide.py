"""Wide windows (ADR 0016): one centered content column up to 1600px, Home's grid filling
it, the header on the same edges as the cards, and nothing scrolling sideways. Each test
leaves a screenshot (e2e-artifacts/wide-window-fits-<width>-<page>.png)."""

import pytest

from e2e.support import open_named_page, settle, sideways_overflow

WIDTHS = [1440, 1920, 2560]
MAX_COLUMN = 1600


@pytest.mark.parametrize("name", ["home", "applications", "brief", "scratchpad"])
@pytest.mark.parametrize("width", WIDTHS)
def test_window_fits(page, width, name):
    page.set_viewport_size({"width": width, "height": 1000})
    open_named_page(page, name)
    settle(page)

    assert sideways_overflow(page) == 0
    main = page.locator("main.page").bounding_box()
    column = page.locator(".page-inner").bounding_box()
    left = column["x"] - main["x"]
    right = main["x"] + main["width"] - (column["x"] + column["width"])
    assert abs(left - right) <= 2, (left, right)  # centered in the space beside the rail
    if name == "brief":  # a narrow page: 640px, centered like the rest
        assert abs(column["width"] - 640) <= 1
    elif main["width"] >= MAX_COLUMN + 2 * 72:
        assert abs(column["width"] - MAX_COLUMN) <= 1  # grows to its full width
    else:
        assert column["width"] >= main["width"] - 2 * 72 - 1  # only the side margins left

    if name == "home":
        grid = page.locator(".grid").bounding_box()
        head = page.locator(".home-head").bounding_box()
        assert abs(grid["width"] - column["width"]) <= 1  # the grid uses the whole column
        assert abs(head["x"] - grid["x"]) <= 1  # the header shares the cards' edges…
        assert abs((head["x"] + head["width"]) - (grid["x"] + grid["width"])) <= 1
        pill = page.locator(".play-brief").bounding_box()
        assert abs((pill["x"] + pill["width"]) - (grid["x"] + grid["width"])) <= 1  # …pill too
        todo = page.locator("section.card", has=page.locator(".tape", has_text="To do"))
        assert todo.bounding_box()["width"] > column["width"] * 0.6  # cards grow with it
