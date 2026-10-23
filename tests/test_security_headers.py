import re
from pathlib import Path

import pytest

from brain_dock.main import TEMPLATES_DIR
from brain_dock.security import CONTENT_SECURITY_POLICY


def directives(policy):
    return dict(part.strip().split(" ", 1) for part in policy.split(";"))


def test_policy_allows_only_own_scripts_and_styles():
    policy = directives(CONTENT_SECURITY_POLICY)

    assert policy["script-src"] == "'self'"
    assert policy["style-src"] == "'self'"
    assert policy["default-src"] == "'self'"
    assert policy["object-src"] == "'none'"
    assert policy["frame-ancestors"] == "'none'"
    assert policy["form-action"] == "'self'"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/"),
        ("get", "/applications"),
        ("get", "/applications/new"),
        ("get", "/static/app.css"),
        ("get", "/does-not-exist"),
        ("post", "/applications"),  # refused by CSRF, still gets the header
    ],
)
def test_every_response_has_the_policy(client, method, path):
    response = getattr(client, method)(path)

    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


TEMPLATES = sorted(Path(TEMPLATES_DIR).rglob("*.html"))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_have_no_inline_scripts_or_styles(template):
    html = template.read_text()

    # Allowed: <script src="..."> and data blocks (<script type="application/json">).
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag or 'type="application/json"' in tag, f"inline script: {tag}"
    assert "<style" not in html
    assert not re.search(r"\sstyle=", html), "inline style attribute"
    assert not re.search(r"\son[a-z]+=", html), "inline event handler"


def test_template_scan_covers_real_templates():
    assert len(TEMPLATES) >= 4  # the scan ran on the actual templates
