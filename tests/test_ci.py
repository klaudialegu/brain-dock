"""CI settings that must stay in step with the lock file."""

import re
import tomllib

from brain_dock.core.db import REPO_ROOT

IMAGE = re.compile(
    r"image:\s*mcr\.microsoft\.com/playwright/python:v(\d+\.\d+\.\d+)-[a-z]+@sha256:[0-9a-f]{64}"
)


def test_e2e_image_matches_the_locked_playwright_version():
    """The e2e job runs in Microsoft's Playwright image, whose browsers belong to one
    Playwright version. If uv.lock moves on (a Dependabot bump, say) and the image doesn't,
    the browser tests would run against the wrong browser build, so this fails first."""
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    [locked] = [p["version"] for p in lock["package"] if p["name"] == "playwright"]
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    images = IMAGE.findall(workflow)  # tag with an exact version, pinned by digest

    assert len(images) == 1, "the e2e job's Playwright image, pinned by tag and digest"
    assert images[0] == locked, (
        f"e2e image is Playwright {images[0]}, uv.lock has {locked}: update the image tag "
        "and digest in .github/workflows/ci.yml"
    )
