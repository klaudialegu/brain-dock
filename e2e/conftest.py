"""Browser tests for the Safari checklist (docs/design/playwright-checklist-plan.md).

Demo data only: every run builds a throwaway database in pytest's temp folder, starts the
real app on it as a subprocess, and drives it with WebKit (Safari's engine). The guard
below runs before anything opens a database file.
"""

import html
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from e2e.support import (
    ARTIFACTS,
    MODULES,
    REPO_ROOT,
    VIEWPORT,
    Recorder,
    fetch,
    free_port,
    guard_temp_db,
    settle,
)

# --- The throwaway database and the server -------------------------------------------


@dataclass
class Server:
    url: str
    db_path: Path
    temp_root: Path
    marker: str
    marker_id: int


@pytest.fixture(scope="session")
def e2e_db(tmp_path_factory) -> tuple[Path, Path, str, int]:
    """Migrate a temp database, load the job search, inbox and to-do demo sets, add a
    marker."""
    temp_root = tmp_path_factory.getbasetemp()
    path = guard_temp_db(tmp_path_factory.mktemp("e2e") / "demo.db", temp_root)  # first line

    # Imported after the guard ran, so nothing below could have picked a path yet.
    from sqlmodel import Session

    from brain_dock.core.db import get_engine, migrate
    from brain_dock.modules.inbox.demo import load_demo
    from brain_dock.modules.job_search.importer import DEMO_JSON, load_applications, rebuild_db
    from brain_dock.modules.job_search.models import Company
    from brain_dock.modules.todo.demo import load_demo as load_todo_demo

    engine = get_engine(f"sqlite:///{path}")
    try:
        migrate(engine)
        rebuild_db(engine, load_applications(DEMO_JSON), locked=False)
        marker = f"E2E marker {secrets.token_hex(6)}"
        with Session(engine) as session:
            company = Company(name=marker)
            session.add(company)
            session.commit()
            marker_id = company.id
    finally:
        engine.dispose()
    message = load_demo(path)
    assert message.startswith("Loaded"), message
    message = load_todo_demo(path)
    assert message.startswith("Loaded"), message
    return path, temp_root, marker, marker_id


@pytest.fixture(scope="session")
def server(e2e_db) -> Server:
    """The real app as a subprocess: db.DB_PATH is fixed at import (core/db.py), so a
    thread inside pytest would be too late to point it at the temp database."""
    path, temp_root, marker, marker_id = e2e_db
    guard_temp_db(path, temp_root)  # again, right before the server can write
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "BRAIN_DOCK_DB": str(path), "BRAIN_DOCK_MODULES": MODULES}
    log = (path.parent / "server.log").open("w")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "brain_dock.main:app"]
        + ["--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                fetch(f"{url}/")
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    log.flush()
                    raise RuntimeError(
                        "e2e server didn't start:\n" + (path.parent / "server.log").read_text()
                    ) from None
                time.sleep(0.2)
        # Without the marker, no test gets the server: it must be serving this file.
        assert marker in fetch(f"{url}/companies/{marker_id}"), "marker company not served"
        yield Server(url, path, temp_root, marker, marker_id)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log.close()


# --- The browser, pages and their recorders ------------------------------------------


@pytest.fixture(scope="session")
def browser() -> Browser:
    playwright = sync_playwright().start()
    browser = playwright.webkit.launch()
    try:
        yield browser
    finally:
        browser.close()
        playwright.stop()


# Runs in every document before its own scripts. The report goes to Python through a
# binding, so entries survive navigation.
LISTENERS = """
document.addEventListener("securitypolicyviolation", (e) => {
  window.__e2eReport("securitypolicyviolation", e.violatedDirective + " " + e.blockedURI);
});
"""


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def page(browser, server, recorder, request) -> Page:
    """A fresh page per test at 1280x900, with the CSP left on and every error recorded.
    Teardown saves a full-page screenshot (also on failure), then fails the test if
    anything was recorded."""
    context = browser.new_context(base_url=server.url, viewport=VIEWPORT, bypass_csp=False)
    context.expose_binding(
        "__e2eReport", lambda source, kind, detail: recorder.add(kind, detail, source["page"].url)
    )
    context.add_init_script(LISTENERS)
    page = context.new_page()

    def on_console(msg) -> None:
        if msg.type == "error":
            recorder.add("console", msg.text, msg.location.get("url", ""))

    def on_response(response) -> None:
        navigation = response.request.is_navigation_request()
        if navigation and response.status == recorder.expected_status:
            recorder.error_pages[response.url] = response.status

    page.on("console", on_console)
    page.on("response", on_response)
    page.on("pageerror", lambda error: recorder.add("pageerror", str(error), page.url))
    try:
        yield page
        settle(page)
        seen, url = recorder.problems(), page.url  # before the screenshot touches the page
        shot = screenshot_path(request.node)
        # caret="initial": the default "hide" injects a <style>, which the CSP blocks.
        page.screenshot(path=shot, full_page=True, caret="initial")
        RESULTS.setdefault(request.node.nodeid, {})["screenshot"] = shot.name
    finally:
        context.close()
    assert seen == [], f"recorded on {url}: {seen}"


# --- Screenshots and the index page ----------------------------------------------------

RESULTS: dict[str, dict] = {}  # node id -> {"outcome", "screenshot", "name"}


def screenshot_path(node) -> Path:
    """e2e-artifacts/NN-name[-param].png, so parametrized pages never overwrite."""
    name = node.name.removeprefix("test_")
    base, _, param = name.partition("[")
    slug = re.sub(r"[^a-z0-9]+", "-", f"{base}-{param.rstrip(']')}".lower()).strip("-")
    module = Path(node.fspath).stem.removeprefix("test_")
    prefix = "" if module == "safari_checklist" else f"{module}-"
    ARTIFACTS.mkdir(exist_ok=True)
    return ARTIFACTS / f"{prefix}{slug}.png"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    entry = RESULTS.setdefault(item.nodeid, {"outcome": "passed"})
    entry["name"] = item.name
    entry["file"] = Path(item.fspath).name
    if report.failed:
        entry["outcome"] = "failed"
    elif report.skipped and report.when == "setup":
        entry["outcome"] = "skipped"


def pytest_sessionfinish(session):
    if RESULTS:
        write_index(RESULTS)


def write_index(results: dict[str, dict]) -> None:
    """One page to glance at: the 10 checklist items in order with their screenshots,
    then the detector and guard tests."""
    checklist: dict[str, list[dict]] = {}
    others: list[dict] = []
    for entry in results.values():
        match = re.match(r"test_(\d\d)_", entry.get("name", ""))
        if entry.get("file") == "test_safari_checklist.py" and match:
            checklist.setdefault(match.group(1), []).append(entry)
        else:
            others.append(entry)

    def row(entry: dict) -> str:
        mark = {"passed": "✅", "failed": "❌"}.get(entry["outcome"], "⏭️")
        shot = entry.get("screenshot")
        img = f'<a href="{shot}"><img src="{shot}" alt="" loading="lazy"></a>' if shot else ""
        return f"<li>{mark} <code>{html.escape(entry['name'])}</code>{img}</li>"

    parts = ["<h2>Safari checklist</h2>"]
    for number in sorted(checklist):
        entries = sorted(checklist[number], key=lambda e: e["name"])
        failed = any(e["outcome"] == "failed" for e in entries)
        parts.append(f"<h3>{'❌' if failed else '✅'} Item {int(number)}</h3><ul>")
        parts += [row(e) for e in entries]
        parts.append("</ul>")
    parts.append("<h2>Detectors and guard</h2><ul>")
    parts += [row(e) for e in sorted(others, key=lambda e: e.get("name", ""))]
    parts.append("</ul>")
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Safari checklist (WebKit)</title>"
        "<style>body{font-family:system-ui;margin:2rem}li{margin:.5rem 0}"
        "img{display:block;max-width:420px;border:1px solid #ccc;margin:.25rem 0}</style>"
        "<h1>Safari checklist (WebKit)</h1>" + "".join(parts)
    )
