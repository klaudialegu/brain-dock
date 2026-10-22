# 0005. Form security on a localhost app
**Status:** Accepted
**Date:** 2026-10-21

## Context
The add-application form is the first feature that changes data from browser input. The app only listens on 127.0.0.1, but that doesn't stop attacks through the browser: any website open in the same browser can submit a form to `http://127.0.0.1:8000` (cross-site request forgery), and a site can point its own domain at 127.0.0.1 to talk to the app as if it were same-origin (DNS rebinding). Error messages are also a leak risk: FastAPI's default validation reply includes the submitted values.

## Decision
- **CSRF, double-submit token:** form pages put a random token (`secrets.token_urlsafe(32)`) in a hidden field and in an `HttpOnly`, `SameSite=Strict` cookie. An existing well-formed cookie is reused, so several tabs work together. Every POST must send both, and they must match (`secrets.compare_digest`).
- **Origin check:** every POST must have an `Origin` of `http://127.0.0.1:<port>` or `http://localhost:<port>`, or, if there's no `Origin`, a `Referer` with one of those origins. A POST with neither is refused. `Sec-Fetch-Site: cross-site` is refused.
- **Trusted hosts:** Starlette's `TrustedHostMiddleware` only accepts `127.0.0.1` and `localhost`, which blocks DNS rebinding.
- **One dependency for all POSTs:** `verify_csrf` is a FastAPI dependency, and a test fails if any POST route lacks it.
- **No echo:** forms are validated with the shared Pydantic rules in `schemas.py`, the same ones the importer uses. Errors show a field label and a reason, never the value. FastAPI's validation-error reply is replaced with a plain "Invalid request". Form bodies are never logged.
- **No caching:** pages with personal data send `Cache-Control: no-store`.

## Options considered
- No CSRF protection ("it's only localhost"): rejected; the browser is the attack path, not the network.
- Server-side sessions with stored tokens: works, but needs session storage for one user; double-submit gives the same protection here.
- A CSRF library: a new dependency for about 40 lines that are easy to test directly.
- Origin checks only: modern browsers send `Origin` on POST, but the token also covers older or unusual clients, and each layer is tested on its own.

## Consequences
- Good: a forged request needs to pass the token, the origin check and the host check; each is tested, and each test was confirmed to fail when its check is removed.
- Good: the form and the importer can't drift apart on what's valid.
- Trade-off: tests must use an allowed host (`BASE_URL = http://127.0.0.1:8000`), because TestClient's default host is refused.
- Trade-off: the app must be opened as 127.0.0.1 or localhost on its own port; any other host name gets 400.
