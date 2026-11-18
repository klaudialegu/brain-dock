import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from brain_dock.main import STATIC_DIR, app

from .conftest import BASE_URL, all_templates

# Every vendored file and its SHA-256. A changed file fails the test until it's reviewed.
VENDORED = {
    "vendor/echarts-6.1.0/echarts.min.js": "b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0",  # noqa: E501
    "vendor/fonts/geist-mono-5.3.0/geist-mono-latin-400-normal.woff2": "3f98383b122fe015a48536cd4a1cda855a201718923ffe74931a01597107b9b5",  # noqa: E501
    "vendor/fonts/geist-mono-5.3.0/geist-mono-latin-500-normal.woff2": "72971bd4908d3984fa1b1426bb363730e4957e16a0f58bfbca76993095715488",  # noqa: E501
    "vendor/fonts/inter-5.3.0/inter-latin-400-normal.woff2": "8909904ab6c872eb994093482a88a28eca2cd95912d7b6fecd72103b0dc07edc",  # noqa: E501
    "vendor/fonts/inter-5.3.0/inter-latin-500-normal.woff2": "f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f",  # noqa: E501
    "vendor/fonts/inter-5.3.0/inter-latin-600-normal.woff2": "f9a06e79cd3a2a20951c0f0e28f66dd0e6d3fda73911d640a2125c8fcb78f21a",  # noqa: E501
    "vendor/fonts/inter-5.3.0/inter-latin-ext-400-normal.woff2": "6744a7f509ebc6ab220a6cd4ea77e898adf014f03d88dcda5d45d8a9feefb4e9",  # noqa: E501
    "vendor/fonts/inter-5.3.0/inter-latin-ext-500-normal.woff2": "2c6fbc42d315528beb06c1096df45487bf4186c4b78b8111d12c9c951f8acca2",  # noqa: E501
    "vendor/fonts/inter-5.3.0/inter-latin-ext-600-normal.woff2": "e4bdf67b0cd15ca9e184509275be95db942195d3cc2b17f6a0452f2adf75d0bf",  # noqa: E501
    "vendor/fonts/kalam-5.3.0/kalam-latin-300-normal.woff2": "19f8586a22fbcb870f9d2490381d76b9f2e868c56e44b7bbc28d9efe05522a41",  # noqa: E501
    "vendor/fonts/kalam-5.3.0/kalam-latin-ext-300-normal.woff2": "5e1f8697ade10b1b0c1992b23f7532076538ae8db69c2ba9c3dec7aa7d546a83",  # noqa: E501
    "vendor/fonts/newsreader-5.3.0/newsreader-latin-300-normal.woff2": "7370b0829a4d60c6918b775d2fa486c7850a76cf5cd35504f79ef3857987952a",  # noqa: E501
    "vendor/fonts/newsreader-5.3.0/newsreader-latin-400-normal.woff2": "e66067814f1c672d33a457e4f4d102c818b481420e2234cf685ebdbf2f443904",  # noqa: E501
    "vendor/fonts/newsreader-5.3.0/newsreader-latin-ext-300-normal.woff2": "45988371abe58073f913defd1c9dfaf922be77657d825713cb4092bbe557a3da",  # noqa: E501
    "vendor/fonts/newsreader-5.3.0/newsreader-latin-ext-400-normal.woff2": "9d9350535facb67450976945ae249ab8ade73e4909deb3deaa756caa5e7dbb59",  # noqa: E501
}


@pytest.mark.parametrize(("path", "sha256"), VENDORED.items())
def test_vendored_file_matches_its_recorded_checksum(path, sha256):
    assert hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest() == sha256


@pytest.mark.parametrize("path", VENDORED)
def test_vendored_file_has_its_license_alongside(path):
    folder = (STATIC_DIR / path).parent

    if path.endswith(".woff2"):  # fonts: the SIL Open Font License (ADR 0016)
        assert "SIL Open Font License" in (folder / "LICENSE").read_text()
    else:
        assert "Apache License" in (folder / "LICENSE").read_text()
        assert (folder / "NOTICE").read_text().strip()


@pytest.mark.parametrize("path", VENDORED)
def test_vendored_file_is_served(path):
    response = TestClient(app, base_url=BASE_URL).get(f"/static/{path}")

    assert response.status_code == 200
    kind = "font/woff2" if path.endswith(".woff2") else "javascript"
    assert kind in response.headers["content-type"]


TEMPLATES = all_templates()


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_load_nothing_from_other_sites(template):
    html = template.read_text()
    # src= and href= on scripts, styles and images must be local paths.
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not re.match(r"^(https?:)?//", url), f"external resource in {template.name}: {url}"
