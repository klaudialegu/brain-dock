"""Shared by the e2e fixtures and tests: the real-data guard and small helpers."""

import re
import socket
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "e2e-artifacts"
MODULES = "job_search,inbox"
VIEWPORT = {"width": 1280, "height": 900}


class RealDataError(RuntimeError):
    """The e2e database would not be a throwaway file in pytest's temp folder."""


def guard_temp_db(path: Path, temp_root: Path) -> Path:
    """An allow-list, not a deny-list: the resolved path must be inside pytest's temp
    folder and outside the repo, or this raises. It only resolves paths; it never opens
    the file, so a refused path is never touched."""
    resolved = Path(path).resolve()
    root = Path(temp_root).resolve()
    if not resolved.is_relative_to(root):
        raise RealDataError(f"e2e database must be inside pytest's temp folder: {resolved}")
    if resolved.is_relative_to(REPO_ROOT):
        raise RealDataError(f"e2e database must be outside the repo: {resolved}")
    return resolved


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode()


def sideways_overflow(page) -> int:
    """How many pixels the page scrolls sideways (0 when nothing is clipped). Wide tables
    scroll inside .table-wrap, which doesn't widen the page, so they don't count."""
    return page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def wait_for_entry(page, recorder, kind: str, timeout_ms: int = 5000) -> None:
    """Reports reach Python asynchronously; wait until one of this kind arrived."""
    waited = 0
    while not any(entry[0] == kind for entry in recorder.entries) and waited < timeout_ms:
        page.wait_for_timeout(50)
        waited += 50


# The pages items 9 and 10 visit. Edit and company need an id from the demo data, so
# they're found through the applications table.
PAGES = ["applications", "add", "save-a-job", "edit", "company", "inbox", "inbox-review"]
FIXED_PATHS = {
    "applications": "/applications",
    "add": "/applications/new",
    "save-a-job": "/applications/saved/new",
    "inbox": "/inbox",
    "inbox-review": "/inbox/review",
}


def open_named_page(page, name: str) -> None:
    if name in FIXED_PATHS:
        page.goto(FIXED_PATHS[name])
        return
    page.goto("/applications")
    table = applications_table(page)
    selector = 'a[href$="/edit"]' if name == "edit" else 'a[href^="/companies/"]'
    page.goto(table.locator(selector).first.get_attribute("href"))


def applications_table(page):
    """The applications table on /applications (the only table with a Stage column)."""
    return page.locator("table").filter(
        has=page.get_by_role("columnheader", name="Stage", exact=True)
    )


def saved_section(page):
    return page.locator("section[aria-labelledby=saved-heading]")


def settle(page) -> None:
    """Let late events (CSP reports, deferred scripts) reach the recorder."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(250)


# WebKit logs this for any response with an error status, the page's own document included.
STATUS_LINE = re.compile(
    r"^Failed to load resource: the server responded with a status of (\d{3})\b"
)


@dataclass
class Recorder:
    """CSP violations, console errors and uncaught errors seen by one test's page."""

    entries: list[tuple[str, str, str]] = field(default_factory=list)  # kind, detail, url
    expected_status: int | None = None
    error_pages: dict[str, int] = field(default_factory=dict)  # document url -> status

    def expect_error_page(self, status: int) -> None:
        """For tests that post a bad form: the app answers with this status on purpose.
        Only WebKit's status line for that exact document is excused, and only when the
        navigation really returned it; anything else on the page still fails."""
        self.expected_status = status

    def add(self, kind: str, detail: str, url: str = "") -> None:
        self.entries.append((kind, detail, url))

    def problems(self) -> list[tuple[str, str]]:
        found = []
        for kind, detail, url in self.entries:
            status = STATUS_LINE.match(detail) if kind == "console" else None
            if status and self.error_pages.get(url) == int(status.group(1)):
                continue
            found.append((kind, detail))
        return found

    def clear(self) -> None:
        self.entries.clear()
