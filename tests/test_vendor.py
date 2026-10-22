import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from brain_dock.main import STATIC_DIR, TEMPLATES_DIR, app

from .conftest import BASE_URL

# Every vendored file and its SHA-256. A changed file fails the test until it's reviewed.
VENDORED = {
    "vendor/echarts-6.1.0/echarts.min.js": "b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0",  # noqa: E501
}


@pytest.mark.parametrize(("path", "sha256"), VENDORED.items())
def test_vendored_file_matches_its_recorded_checksum(path, sha256):
    assert hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest() == sha256


@pytest.mark.parametrize("path", VENDORED)
def test_vendored_file_has_its_license_alongside(path):
    folder = (STATIC_DIR / path).parent

    assert "Apache License" in (folder / "LICENSE").read_text()
    assert (folder / "NOTICE").read_text().strip()


@pytest.mark.parametrize("path", VENDORED)
def test_vendored_file_is_served(path):
    response = TestClient(app, base_url=BASE_URL).get(f"/static/{path}")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


TEMPLATES = sorted(Path(TEMPLATES_DIR).rglob("*.html"))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_load_nothing_from_other_sites(template):
    html = template.read_text()
    # src= and href= on scripts, styles and images must be local paths.
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not re.match(r"^(https?:)?//", url), f"external resource in {template.name}: {url}"
