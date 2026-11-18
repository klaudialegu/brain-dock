"""The play-brief orb in a real browser (ADR 0016): it breathes, stays still under reduced
motion, and stops drawing in a hidden tab. Display-only until playback arrives."""

from playwright.sync_api import expect

ORB = "[data-orb]"


def frames(page, count: int = 3, gap_ms: int = 400) -> list[str]:
    """The canvas now, and a few more times a little later."""
    shots = []
    for i in range(count):
        if i:
            page.wait_for_timeout(gap_ms)
        shots.append(page.eval_on_selector(f"{ORB} canvas", "c => c.toDataURL()"))
    return shots


def test_reduced_motion_keeps_the_orb_still(page):
    page.goto("/")
    expect(page.locator(ORB)).to_have_attribute("data-animating", "true")
    before = int(page.get_attribute(ORB, "data-frames"))
    # The loop really runs: frames keep coming. A generous wait, since a busy CI browser
    # ticks animation frames slowly; a loop that never runs still times out.
    page.wait_for_function(
        "n => Number(document.querySelector('[data-orb]').dataset.frames) >= n",
        arg=before + 5,
        timeout=5000,
    )

    page.emulate_media(reduced_motion="reduce")
    page.reload()
    expect(page.locator(ORB)).to_have_attribute("data-animating", "false")
    still = frames(page)
    assert len(set(still)) == 1
    assert int(page.get_attribute(ORB, "data-frames")) <= 2  # drawn once (plus a resize)
    assert still[0] != page.evaluate("() => document.createElement('canvas').toDataURL()")
    button = page.get_by_role("button", name="Play brief")
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("title", "Available after the next update")
    expect(button).to_have_css("opacity", "1")  # disabled, but not dimmed
    # Hover lands on the wrapper (the disabled button ignores the pointer): the tooltip
    # must be on whatever is under the pointer, or one of its parents.
    under = page.evaluate(
        """() => {
            const b = document.querySelector(".play-brief").getBoundingClientRect();
            const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
            return el && el.closest("[title]") ? el.closest("[title]").title : null;
        }"""
    )
    assert under == "Available after the next update"
    expect(page.locator(f"{ORB} canvas")).to_have_attribute("aria-hidden", "true")


def test_drawing_stops_when_the_tab_is_hidden(page):
    page.goto("/")
    expect(page.locator(ORB)).to_have_attribute("data-animating", "true")

    page.evaluate(
        """() => {
            Object.defineProperty(document, "hidden", { value: true, configurable: true });
            document.dispatchEvent(new Event("visibilitychange"));
        }"""
    )
    expect(page.locator(ORB)).to_have_attribute("data-animating", "false")
    hidden = frames(page)
    assert len(set(hidden)) == 1
    stopped = int(page.get_attribute(ORB, "data-frames"))
    page.wait_for_timeout(400)
    assert int(page.get_attribute(ORB, "data-frames")) == stopped  # no drawing while hidden

    page.evaluate(
        """() => {
            Object.defineProperty(document, "hidden", { value: false, configurable: true });
            document.dispatchEvent(new Event("visibilitychange"));
        }"""
    )
    expect(page.locator(ORB)).to_have_attribute("data-animating", "true")
