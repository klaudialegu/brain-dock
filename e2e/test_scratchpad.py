"""The Scratchpad in a real browser (ADR 0017): paper per page, remembered; quick capture
with ⌘K lands on today's page. The e2e server is shared, so each test puts back what it
changed."""

import re

from playwright.sync_api import expect


def test_paper_switching_is_remembered(page):
    page.goto("/scratchpad")
    sheet = page.locator("section.pad-sheet")
    expect(sheet).to_have_class(re.compile(r"\bpaper-lined\b"))

    page.get_by_role("button", name="Kraft").click()
    expect(page.locator("section.pad-sheet")).to_have_class(re.compile(r"\bpaper-kraft\b"))
    expect(page.get_by_role("button", name="Kraft")).to_have_attribute("aria-pressed", "true")
    page.reload()
    expect(page.locator("section.pad-sheet")).to_have_class(re.compile(r"\bpaper-kraft\b"))
    page.goto("/")
    expect(page.locator(".pad-card")).to_have_class(re.compile(r"\bpaper-kraft\b"))  # the card too

    page.goto("/scratchpad")
    page.get_by_role("button", name="Lined").click()  # put it back
    expect(page.locator("section.pad-sheet")).to_have_class(re.compile(r"\bpaper-lined\b"))


def test_quick_capture_shortcut_lands_on_the_scratchpad(page):
    page.goto("/todo")
    page.keyboard.press("Meta+k")  # from another page: opens Home with the field focused
    expect(page).to_have_url(re.compile(r"/\?capture$"))
    field = page.get_by_role("textbox", name="Quick capture")
    expect(field).to_be_focused()

    page.keyboard.press("Escape")
    page.locator("body").click()
    page.keyboard.press("Control+k")  # on Home: just focuses the field
    expect(field).to_be_focused()
    note = "e2e note " + __import__("secrets").token_hex(4)
    field.fill(note)
    field.press("Enter")
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.locator(".pad-card")).to_contain_text(note)  # on Home's card…
    page.goto("/scratchpad")
    expect(page.locator("#pad-text")).to_have_value(
        re.compile(re.escape(note) + r"$")
    )  # …and the page


def test_words_typed_just_before_switching_paper_are_kept(page):
    page.goto("/scratchpad")
    box = page.locator("#pad-text")
    original = box.input_value()
    sent = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    box.focus()
    box.evaluate("el => el.setSelectionRange(el.value.length, el.value.length)")
    box.press_sequentially(" quick words")  # no pause: the autosave timer hasn't fired yet
    page.get_by_role("button", name="Dotted").click()
    expect(page.locator("section.pad-sheet")).to_have_class(re.compile(r"\bpaper-dotted\b"))
    expect(page.locator("#pad-text")).to_have_value(original + " quick words")  # no reload needed
    assert [url.rsplit("/", 1)[-1] for url in sent] == ["text", "style"]  # the words went first

    page.locator("#pad-text").fill(original)  # put it back
    page.get_by_role("button", name="Lined").click()
    expect(page.locator("section.pad-sheet")).to_have_class(re.compile(r"\bpaper-lined\b"))
    page.reload()
    expect(page.locator("#pad-text")).to_have_value(original)
