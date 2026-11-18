"""The shell in a real browser (ADR 0016): modules on and off in Settings, and a saved
layout that survives a reload. The e2e server is shared, so each test puts back what it
changed."""

import re

from playwright.sync_api import expect


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
