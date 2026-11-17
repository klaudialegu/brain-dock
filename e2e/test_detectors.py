"""The detectors behind items 9 and 10 must be able to fail."""

from e2e.support import Recorder, settle, sideways_overflow, wait_for_entry


def test_overflow_detector_catches_a_wide_element(page):
    page.goto("/applications")
    assert sideways_overflow(page) == 0
    # Inside <main>, like real content (a flex item on <body> would just shrink), and
    # through the CSSOM, which the CSP allows (a style attribute would be blocked).
    page.evaluate(
        """() => {
          const wide = document.createElement("div");
          wide.style.width = "2000px";
          wide.style.height = "10px";
          document.querySelector("main").appendChild(wide);
        }"""
    )
    assert sideways_overflow(page) > 0


def test_csp_listener_catches_an_inline_script(page, recorder):
    page.goto("/applications")
    settle(page)
    assert recorder.problems() == []
    page.evaluate(
        """() => {
          const s = document.createElement("script");
          s.textContent = "window.__e2eInlineRan = true";
          document.body.appendChild(s);
        }"""
    )
    wait_for_entry(page, recorder, "securitypolicyviolation")
    # The CSP is enforced (bypass_csp is off): the inline script never ran.
    assert page.evaluate("() => window.__e2eInlineRan") is None
    page.goto("/inbox")  # recorded before the navigation, read after it
    kinds = [kind for kind, _ in recorder.problems()]
    assert "securitypolicyviolation" in kinds, recorder.entries

    page.evaluate("() => { setTimeout(() => { throw new Error('e2e probe'); }); }")
    wait_for_entry(page, recorder, "pageerror")
    assert any(k == "pageerror" and "e2e probe" in d for k, d in recorder.problems())
    recorder.clear()  # both were planted on purpose; the teardown check stays strict


def test_error_page_opt_in_excuses_only_that_document():
    form = "http://127.0.0.1/applications/saved"
    line = "Failed to load resource: the server responded with a status of 400 (Bad Request)"
    recorder = Recorder()
    recorder.expect_error_page(400)
    recorder.error_pages[form] = 400  # what the response listener records for the post
    recorder.add("console", line, form)  # the form's own 400: excused
    recorder.add("console", line, "http://127.0.0.1/static/app.css")  # a subresource: not
    recorder.add("console", line.replace("400 (Bad Request)", "500 (Server Error)"), form)
    recorder.add("securitypolicyviolation", "style-src-elem inline", form)
    recorder.add("pageerror", "boom", form)
    assert [kind for kind, _ in recorder.problems()] == [
        "console",
        "console",
        "securitypolicyviolation",
        "pageerror",
    ]
