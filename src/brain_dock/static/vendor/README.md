# Vendored files

Served from `/static/vendor/` so pages never load anything from another site (local-first; ADR 0005's CSP only allows `'self'`).

| Library | Version | License | Source | SHA-256 of the served file |
|---|---|---|---|---|
| Apache ECharts | 6.1.0 | Apache-2.0 (`LICENSE`, `NOTICE` alongside) | npm `echarts@6.1.0` tarball, `package/dist/echarts.min.js`; tarball checked against the registry's integrity `sha512-q0yaFPggC9FUdsWH4blavRWFmxdrIodbkoKNAjJudAI6CA9gNPxHtV2RcZNEepZVlk4yvBYkOkbk6HIVpIyHZA==` | `b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0` |

Checked before vendoring: no `eval`, `fetch`, `XMLHttpRequest`, WebSocket or beacon calls; its only `new Function` is a fallback for browsers without `JSON.parse`.

To update: download the new npm tarball, verify its integrity against the registry, copy the same three files into a new `echarts-<version>/` folder, update this table and `VENDORED` in `tests/test_vendor.py`, then point the template at the new folder.
