"""Remove with Undo, and closing things, in a real browser, keyboard only (ADR 0018).

Every control is reached with focus and used with Enter or Esc, never a click. The e2e
server is shared, so each test removes only what it made itself (or puts things back).
The "look-*.png" screenshots are the ones the look is approved from.
"""

import re
import secrets

from playwright.sync_api import expect

from .support import ARTIFACTS

BAR = "[data-message]"


SCREENSHOT_STYLE = ("style-src-elem inline", "Refused to apply a stylesheet")


def snap(page, recorder, name: str) -> None:
    """A screenshot mid-test. Taking it makes WebKit report one inline stylesheet that the
    CSP blocks (the conftest takes its own only after reading the reports); exactly those
    entries are set aside, and anything else the page does still fails the test."""
    ARTIFACTS.mkdir(exist_ok=True)
    page.evaluate("() => { document.activeElement?.blur(); window.scrollTo(0, 0); }")
    before = len(recorder.entries)
    # caret="initial": the default "hide" injects a <style>, which the CSP blocks.
    page.screenshot(path=ARTIFACTS / f"look-{name}.png", full_page=True, caret="initial")
    page.wait_for_timeout(100)
    new = recorder.entries[before:]
    del recorder.entries[before:]
    recorder.entries.extend(e for e in new if not e[1].startswith(SCREENSHOT_STYLE))


def named(action: str, title: str) -> re.Pattern:
    """A control's accessible name, "Edit: <title>" (the title is visually hidden text)."""
    return re.compile(rf"^{re.escape(action)}\s*:\s*{re.escape(title)}$")


def press(locator, key: str = "Enter") -> None:
    """Keyboard only: focus the control, then press the key."""
    locator.focus()
    locator.press(key)


def new_task(page, prefix: str = "e2e task") -> str:
    title = f"{prefix} {secrets.token_hex(3)}"
    page.goto("/todo")
    page.get_by_role("textbox", name="Title").fill(title)
    page.get_by_role("textbox", name="Title").press("Enter")
    expect(page.locator(".todo-list .todo-title").get_by_text(title, exact=True)).to_be_visible()
    return title


def open_edit(page, title: str) -> None:
    press(page.get_by_role("link", name=named("Edit", title)))
    expect(page).to_have_url(re.compile(r"/todo/\d+/edit$"))


def test_remove_a_task_and_undo(page, recorder):
    title = new_task(page)
    open_edit(page, title)
    remove = page.get_by_role("button", name="Remove task")
    snap(page, recorder, "remove-task")
    press(remove)

    expect(page).to_have_url(re.compile(r"/todo$"))
    expect(page.locator(BAR)).to_contain_text(f"Removed: {title}")
    expect(page.locator(".todo-list .todo-title").get_by_text(title, exact=True)).to_have_count(0)
    snap(page, recorder, "message-bar")

    press(page.locator(BAR).get_by_role("button", name="Undo"))
    expect(page.locator(".todo-list .todo-title").get_by_text(title, exact=True)).to_be_visible()
    expect(page.locator(BAR)).to_have_count(0)
    open_edit(page, title)  # tidy up: removed again, so it stays out of other tests
    press(page.get_by_role("button", name="Remove task"))


def test_remove_a_step_and_undo(page):
    title = new_task(page, "e2e steps")
    open_edit(page, title)
    for step in ["First step", "Second step", "Third step"]:
        page.get_by_label("Step", exact=True).fill(step)
        page.get_by_label("Step", exact=True).press("Enter")
        expect(page.locator(".todo-steps-edit")).to_contain_text(step)

    press(page.get_by_role("button", name="Remove step 2"))
    expect(page.locator(BAR)).to_contain_text("Removed step: Second step")
    titles = page.locator(".todo-steps-edit .todo-title")
    expect(titles).to_have_text(["First step", "Third step"])

    press(page.locator(BAR).get_by_role("button", name="Undo"))
    expect(titles).to_have_text(["First step", "Second step", "Third step"])  # its old place
    press(page.get_by_role("button", name="Remove task"))  # tidy up


def test_remove_a_page_and_undo(page, recorder):
    page.goto("/scratchpad")
    press(page.get_by_role("button", name="New page"))
    expect(page.locator("#pad-text")).to_have_value("")
    fresh = page.url
    page.locator("#pad-text").fill("a page to remove")
    press(page.get_by_role("button", name="Save"))
    expect(page.locator("#pad-text")).to_have_value("a page to remove")
    snap(page, recorder, "remove-page")

    press(page.get_by_role("button", name="Remove page"))
    expect(page.locator(BAR)).to_contain_text("Removed page:")
    expect(page).not_to_have_url(fresh)  # on the latest page left
    expect(page.locator("#pad-text")).not_to_have_value("a page to remove")

    press(page.locator(BAR).get_by_role("button", name="Undo"))
    expect(page).to_have_url(fresh)
    expect(page.locator("#pad-text")).to_have_value("a page to remove")
    press(page.get_by_role("button", name="Remove page"))  # tidy up: it stays removed


def test_esc_and_close_dismiss_the_message(page):
    first = new_task(page, "e2e esc")
    open_edit(page, first)
    press(page.get_by_role("button", name="Remove task"))
    bar = page.locator(BAR)
    expect(bar).to_be_visible()

    title = page.get_by_role("textbox", name="Title")
    title.fill("typing in a field")
    title.press("Escape")  # Esc in a field only leaves the field…
    expect(title).not_to_be_focused()
    expect(title).to_have_value("typing in a field")
    expect(bar).to_be_visible()  # …and the Undo is still there
    page.keyboard.press("Escape")  # a second Esc closes the bar
    expect(bar).to_have_count(0)

    second = new_task(page, "e2e close")
    open_edit(page, second)
    press(page.get_by_role("button", name="Remove task"))
    expect(bar).to_be_visible()
    press(page.get_by_role("link", name="Close message"))  # the visible ×, with Enter
    expect(bar).to_have_count(0)
    expect(page.locator("main")).to_be_focused()  # focus lands somewhere sensible


def test_reload_does_not_repeat_the_message(page):
    title = new_task(page, "e2e reload")
    open_edit(page, title)
    press(page.get_by_role("button", name="Remove task"))
    expect(page.locator(BAR)).to_contain_text(f"Removed: {title}")
    page.reload()
    expect(page.locator(BAR)).to_have_count(0)


def no_leave_prompt(page) -> list[str]:
    """Collect browser dialogs. Save must never trigger "Leave this page?": choosing Stay
    there would leave a page that no longer saves."""
    seen: list[str] = []

    def answer(dialog):
        seen.append(dialog.type)
        dialog.accept()

    page.on("dialog", answer)
    return seen


def test_removed_page_in_another_tab_keeps_its_text(page, recorder):
    recorder.expect_error_page(410)  # the refused save answers 410 on purpose
    dialogs = no_leave_prompt(page)
    page.goto("/scratchpad")
    press(page.get_by_role("button", name="New page"))
    expect(page.locator("#pad-text")).to_have_value("")
    here = page.url

    other = page.context.new_page()  # the same page, removed from another tab
    other.goto(here)
    other.get_by_role("button", name="Remove page").focus()
    other.keyboard.press("Enter")
    expect(other.locator(BAR)).to_contain_text("Removed page:")
    other.close()

    box = page.locator("#pad-text")
    box.focus()
    box.press_sequentially("words typed in the old tab")
    expect(page.locator("[data-save-state]")).to_contain_text("This page was removed")
    press(page.get_by_role("button", name="Save"))
    expect(page.get_by_role("heading", name="This page was removed")).to_be_visible()
    assert dialogs == []  # Save posted the text without a "Leave this page?" prompt
    expect(page.locator(".pad-typed")).to_have_text("words typed in the old tab")
    expect(page.get_by_role("button", name="Undo")).to_be_visible()
    expect(page.locator("#pad-text")).to_have_count(0)  # no editor
    snap(page, recorder, "page-removed")

    press(page.get_by_role("button", name="Undo"))  # the page is back, with the typed words
    expect(page).to_have_url(here)
    expect(page.locator("#pad-text")).to_have_value("words typed in the old tab")
    press(page.get_by_role("button", name="Remove page"))  # tidy up: it stays removed


def test_quick_capture_esc_leaves_the_field(page):
    page.goto("/")
    page.keyboard.press("Control+k")
    field = page.get_by_role("textbox", name="Quick capture")
    expect(field).to_be_focused()
    field.press_sequentially("half a thought")
    field.press("Escape")
    expect(field).not_to_be_focused()
    expect(field).to_have_value("half a thought")  # kept, not sent


def test_done_recently_not_done(page, recorder):
    page.goto("/todo")
    summary = page.locator("details.todo-done summary")
    press(summary)  # Enter opens it
    expect(page.locator("details.todo-done")).to_have_attribute("open", "")
    recent = page.locator("details.todo-done")
    expect(recent).to_contain_text("Return the library books")
    expect(recent).to_contain_text("done")
    snap(page, recorder, "done-recently")

    press(recent.get_by_role("button", name=named("Not done", "Book the bike service")))
    today = page.locator(".todo-list").first
    expect(today).to_contain_text("Book the bike service")  # back in Today, open
    open_edit(page, "Book the bike service")  # tidy up: removed, so other tests see the demo
    press(page.get_by_role("button", name="Remove task"))


def test_remove_from_a_task_row_and_undo(page, recorder):
    title = new_task(page, "e2e row")
    row = page.locator(".todo-item", has=page.get_by_text(title, exact=True))
    remove = row.get_by_role("button", name=named("Remove", title))
    row.evaluate("el => el.scrollIntoView({block: 'center'})")
    ARTIFACTS.mkdir(exist_ok=True)
    before = len(recorder.entries)
    row.screenshot(path=ARTIFACTS / "look-row-remove.png", caret="initial")
    page.wait_for_timeout(100)
    new = recorder.entries[before:]
    del recorder.entries[before:]
    recorder.entries.extend(e for e in new if not e[1].startswith(SCREENSHOT_STYLE))

    press(remove)
    expect(page).to_have_url(re.compile(r"/todo$"))
    expect(page.locator(BAR)).to_contain_text(f"Removed: {title}")
    expect(page.locator(".todo-list .todo-title").get_by_text(title, exact=True)).to_have_count(0)
    press(page.locator(BAR).get_by_role("button", name="Undo"))
    expect(page.locator(".todo-list .todo-title").get_by_text(title, exact=True)).to_be_visible()
    press(
        page.locator(".todo-item", has=page.get_by_text(title, exact=True)).get_by_role(
            "button", name=named("Remove", title)
        )
    )  # tidy up
