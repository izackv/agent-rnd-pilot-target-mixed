# API

Role is supplied by the `X-Role` header (`viewer` default, `admin`). This is trial-grade
authentication, chosen so permission paths can be tested without an identity provider.

| Method | Path | Behavior |
|---|---|---|
| GET | `/healthz` | `{"status": "ok", "version": ...}` |
| GET | `/api/reports` | Reports visible to the role. Restricted reports are admin-only. |
| GET | `/api/reports/export` | CSV download (`text/csv; charset=utf-8`, `Content-Disposition: attachment`) of every report visible to the role — one row per report, columns `id,title,owner,rows`, CRLF lines, RFC 4180 quoting, formula-lead neutralisation (`=`,`+`,`-`,`@`,`'` leads get a leading `'`). Role comes only from the `X-Role` header; no parameter can widen it. Empty permitted set still returns 200 with the header line. |
| GET | `/api/reports/{id}` | One report, or 404 if missing or not visible to the role. |

## Accepted user journeys

| ID | Journey | Test |
|---|---|---|
| J-01 | Viewer opens the reports page and sees permitted reports; admin sees the restricted one too | `tests/e2e/test_journey.py` |
| J-03 | Any caller downloads the report set as CSV; restricted reports never appear unless `X-Role: admin` is sent verbatim | `tests/integration/test_csv_export.py` (browser control in `tests/e2e`) |
