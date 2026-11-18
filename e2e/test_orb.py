"""The play-brief orb in a real browser (ADR 0016): it breathes, stays still under reduced
motion, and stops drawing in a hidden tab. Display-only until playback arrives."""

from playwright.sync_api import expect

ORB = "[data-orb]"


def frames(page, gap_ms: int = 600) -> tuple[str, str]:
    """The canvas now, and again a little later."""
    first = page.eval_on_selector(f"{ORB} canvas", "c => c.toDataURL()")
    page.wait_for_timeout(gap_ms)
    return first, page.eval_on_selector(f"{ORB} canvas", "c => c.toDataURL()")


def test_reduced_motion_keeps_the_orb_still(page):
    page.goto("/")
    expect(page.locator(ORB)).to_have_attribute("data-animating", "true")
    moving = frames(page)
    assert moving[0] != moving[1]  # it really breathes, so "still" below means something

    page.emulate_media(reduced_motion="reduce")
    page.reload()
    expect(page.locator(ORB)).to_have_attribute("data-animating", "false")
    still = frames(page)
    assert still[0] == still[1]
    assert still[0] != page.evaluate("() => document.createElement('canvas').toDataURL()")
    button = page.get_by_role("button", name="Play brief")
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("title", "Available after the next update")
    expect(button).to_have_css("opacity", "1")  # disabled, but not dimmed
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
    assert hidden[0] == hidden[1]

    page.evaluate(
        """() => {
            Object.defineProperty(document, "hidden", { value: false, configurable: true });
            document.dispatchEvent(new Event("visibilitychange"));
        }"""
    )
    expect(page.locator(ORB)).to_have_attribute("data-animating", "true")
