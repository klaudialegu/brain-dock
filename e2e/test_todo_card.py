"""The To do card on Home and Focus mode in a real browser (ADR 0016), keyboard first.
The e2e server is shared, so each test puts back what it changed. The "look-*.png"
screenshots are the ones the look is approved from."""

import re

from playwright.sync_api import expect

from .support import ARTIFACTS
from .test_remove import SCREENSHOT_STYLE, named, press

CARD = "section.card.c-graphite"


def snap(page, recorder, name: str, locator=None) -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    page.evaluate("() => document.activeElement?.blur()")
    before = len(recorder.entries)
    target = locator if locator is not None else page
    kwargs = {} if locator is not None else {"full_page": True}
    target.screenshot(path=ARTIFACTS / f"look-{name}.png", caret="initial", **kwargs)
    page.wait_for_timeout(100)
    new = recorder.entries[before:]
    del recorder.entries[before:]
    recorder.entries.extend(e for e in new if not e[1].startswith(SCREENSHOT_STYLE))


def test_read_aloud_toggle(page, recorder):
    page.goto("/")
    card = page.locator(CARD)
    speaker = card.get_by_role("button", name=named("Ok to read aloud", "Order groceries"))
    expect(speaker).to_have_attribute("aria-pressed", "false")  # off by default
    snap(page, recorder, "todo-card", card)

    press(speaker)
    expect(page).to_have_url(re.compile(r"/$"))  # back on Home, not the To do page
    speaker = page.locator(CARD).get_by_role(
        "button", name=named("Ok to read aloud", "Order groceries")
    )
    expect(speaker).to_have_attribute("aria-pressed", "true")
    press(speaker)  # put it back
    expect(
        page.locator(CARD).get_by_role("button", name=named("Ok to read aloud", "Order groceries"))
    ).to_have_attribute("aria-pressed", "false")


def test_focus_ring_has_one_dot_per_minute(page, recorder):
    page.goto("/")
    press(
        page.locator(CARD).get_by_role("link", name=named("Focus", "Finish the project write-up"))
    )
    expect(page).to_have_url(re.compile(r"/todo/\d+/focus$"))
    expect(page.locator(".focus-step")).to_contain_text("Step 1 of 4: Outline the three sections")
    ring = page.locator(".focus-ring circle")
    expect(ring).to_have_count(10)  # the current step's 10 minutes
    expect(page.locator(".focus-ring circle.is-now")).to_have_count(1)
    toggle = page.get_by_role("button", name="Pause")
    expect(toggle).to_be_visible()  # the script runs the timer
    snap(page, recorder, "focus")

    press(toggle)
    expect(page.get_by_role("button", name="Resume")).to_be_visible()
    expect(page.locator("[data-state]")).to_have_text("Paused")
    press(page.get_by_role("button", name="Resume"))
    expect(page.get_by_role("button", name="Pause")).to_be_visible()

    park = page.get_by_role("textbox", name="Park a thought")
    park.fill("e2e parked thought")
    park.press("Enter")
    expect(page.locator("[data-park-state]")).to_have_text("Parked.")  # stays in Focus
    expect(page).to_have_url(re.compile(r"/focus$"))

    page.emulate_media(reduced_motion="reduce")  # the ring still updates, without animating
    page.reload()
    expect(page.locator(".focus-ring circle.is-now")).to_have_count(1)
    duration = page.locator(".focus-ring circle").first.evaluate(
        "el => getComputedStyle(el).transitionDuration"
    )
    assert duration in ("0s", "0s, 0s")


def test_break_into_steps_shows_on_hover_and_focus(page):
    page.goto("/")
    card = page.locator(CARD)
    plain = card.locator(".tcard-item", has=page.get_by_text("Order groceries", exact=True))
    summary = plain.locator("summary")
    expect(summary).to_contain_text("Break into steps")

    def opacity(locator):
        return locator.evaluate("el => getComputedStyle(el).opacity")

    page.mouse.move(0, 0)
    expect(summary).to_have_css("opacity", "0")  # quiet until wanted
    plain.hover()
    expect(summary).to_have_css("opacity", "1")
    page.mouse.move(0, 0)
    expect(summary).to_have_css("opacity", "0")
    summary.focus()  # keyboard: Tab lands on it and it shows
    expect(summary).to_have_css("opacity", "1")
    stepped = card.locator(
        ".tcard-item", has=page.get_by_text("Finish the project write-up", exact=True)
    )
    page.mouse.move(0, 0)
    stepped.locator("summary").blur()
    assert opacity(stepped.locator("summary")) == "1"  # "4 steps" is always shown
    expect(stepped.locator("summary")).to_contain_text("4 steps")
