# API

Role is supplied by the `X-Role` header (`viewer` default, `admin`). This is trial-grade
authentication, chosen so permission paths can be tested without an identity provider.

| Method | Path | Behavior |
|---|---|---|
| GET | `/healthz` | `{"status": "ok", "version": ...}` |
| GET | `/api/reports` | Reports visible to the role. Restricted reports are admin-only. |
| GET | `/api/reports/export` | CSV download of every report visible to the role — format, headers, permissions and error cases in [CSV export](#csv-export). |
| GET | `/api/reports/{id}` | One report, or 404 if missing or not visible to the role. |

## CSV export

`GET /api/reports/export` — exactly one URL, no path/query/body parameters and no alias
(e.g. no `/export.csv`); a request body is accepted but ignored (C1). The route is registered
before `/api/reports/{report_id}`, so a canonical GET is never swallowed by the int route (C1).
This section equals the frozen CSV export contract **rev 3**, extended only by addendum clause
**A1** (export cache directives), forming **rev 4**; the ids in parentheses are its clause
numbers (traceability table: contract C8).

### Response headers (C1, A1, C7)

| Header | Value |
|---|---|
| `Content-Type` | `text/csv; charset=utf-8`. No content negotiation: `Accept` never changes status, media type or bytes (C1). |
| `Content-Disposition` | `attachment; filename="reports-YYYY-MM-DD.csv"` — the UTC calendar date when the response is generated, in one server-side statement. The name derives only from that constant and the server clock: never from report data or client input, and the role never appears in it. The fixed shape excludes CR, LF, quotes and backslashes, which is what closes the header-injection surface (C7). Browser downloads reuse the server-stated name; client-side code never computes its own (C1). |
| `Cache-Control` | `no-store` — exact literal, on every 200. The body is role-filtered (C3) but the URL is unique with no cache-visible variant (C1), so a URL-keyed shared cache (proxy, CDN, browser) could otherwise serve one role's CSV to another; forbidding storage closes that path (A1). |
| `Vary` | `X-Role` — exact literal, on every 200. Keys any correct reuse on the one header that decides the body; `Accept` is deliberately not named because C1 forbids content negotiation. Both values are handler-side constants, never derived from request or report data, so neither adds an injection surface (A1). |

### File contents (C2, C4)

- One row per permitted report; the columns are the page-table columns. The header line is
  exactly `id,title,owner,rows` (21 bytes with its CRLF); `restricted` is a permission-filtering
  matter, never a column at any privilege (C2).
- Rows are ordered by `id` ascending, and the same role over unchanged data yields byte-identical
  files on repeated downloads (C2).
- Every record, including the last, ends with CRLF; no bare CR/LF outside quoted fields. Strict
  UTF-8 with no Unicode normalisation, so NFC and NFD text round-trips byte-exactly (C4).
- RFC 4180 minimal quoting: a field is quoted only if it contains `,` `"` CR or LF (inner `"`
  doubled); a formula lead alone never forces quoting (C4).
- Typing is per-column and value-blind: `id`/`rows` render as plain integers (`rows=-42` → `-42`,
  never quoted or prefixed); `title`/`owner` are text however numeric they look (`00123`, `1E+3`
  verbatim) and take the neutralisation below (C2).
- Formula-lead neutralisation: stored text whose **first character** is one of `=` `+` `-` `@` `'`
  serialises with a leading `'` (U+0027) inserted before any quoting, and only the first character
  decides — later trigger characters are not neutralised. A value already starting with `'` is
  prefixed too (`'=x` → `''=x`; the second apostrophe is stored content, not escaping), so
  "strip exactly one leading apostrophe, if present" recovers the stored value for every input
  (C4, OD-7=B).
- The API path emits no byte-order mark; the UTF-8 BOM appears only on the browser download path,
  where the page prepends it for Excel (C4). Byte relation:
  `browser_file_bytes == b"\xef\xbb\xbf" + api_file_bytes` (C4). The emitter never truncates
  (C2).

### Permissions (C3)

The endpoint reuses exactly the same role resolution and listing code as `GET /api/reports`
(`main._role` + `data.list_reports`, no parallel implementation), so for any header value the
exported rows equal the listed rows for that same header — parity by construction (C3).

- The report set depends on the `X-Role` request header **only**. No query, path, body or form
  parameter can widen, narrow or reorder it: `?role=admin`, `?X-Role=admin`, `?id=3`,
  `?restricted=true`, `?format=json` or any body returns bytes identical to the header-only
  baseline (C3).
- Resolution is exact-equality: only the literal `admin` grants the admin set; anything not
  byte-equal to it — absent header, unknown (`guest`), case variants (`ADMIN`),
  whitespace-padded (` admin`) — resolves to `viewer`, so no input can escalate a non-admin (C3).
- Repeated `X-Role` headers: the **first occurrence** is used (`[viewer, admin]` ⇒ viewer set;
  `[admin, viewer]` ⇒ admin set) (C1).

Role semantics are asserted per the contract's J3 matrix (surface × `X-Role` treatment) and the
J4 restricted-never-appears matrix; see the accepted-journeys table below for the test files. A
restricted report is never addressed by id on this route — it is filtered out by set, so restricted
items appear in no row and no cell for non-admin roles, and every such test runs with an admin
positive-control export so it cannot pass vacuously (C3).

### Error and edge cases (C5)

- Empty permitted set ⇒ 200 with the header line only (never 404/204/400) (C5).
- Never 401/403 for any `X-Role` value: every caller is authorized for the set its header
  resolves to (C5).
- Existing endpoints' semantics are unchanged: `GET /api/reports/3` as viewer returns a 404
  identical in shape and message (`report not found`) to a missing id — hidden and missing are
  indistinguishable; a non-integer id still returns 422 (C5).
- No size limits, caps, paging or server-side filtering/date ranges in v1 — export everything
  the role may see (C2, C5).

Normative request shapes (C5), probed on the pinned stack — CSV bytes on any non-canonical shape
below is a contract violation:

| Request shape | Status | Notes |
|---|---|---|
| `GET` canonical | 200 | CSV per C1–C4; same bytes with any query params |
| `HEAD` canonical | 405 | `Allow: GET`, empty body |
| `POST/PUT/PATCH/DELETE` canonical | 405 | `{"detail": "Method Not Allowed"}` |
| `GET` canonical, trailing slash | 307 | `Location` = canonical URL + original query, empty body |
| `GET /api/reports/export/extra` | 404 | `{"detail": "Not Found"}` |
| `GET /api/reports/export.csv` or `/api/reports/Export` | 422 | `{report_id}` int-validation detail — never CSV bytes |
| `GET` other path-case variants (`/API/…`, `/api/Reports/…`) | 404 | path matching is case-sensitive |

## Accepted user journeys

| ID | Journey | Test |
|---|---|---|
| J-01 | Viewer opens the reports page and sees permitted reports; admin sees the restricted one too | `tests/e2e/test_journey.py` |
| J-02 | Browser export, viewer (contract J1): clicking **Export CSV** downloads the permitted set minus the restricted report, with the server-stated filename reused unchanged | `tests/e2e/test_export_journey.py` |
| J-03 | Browser export, admin (contract J2): the export request carries the selector's `X-Role: admin` verbatim and the file additionally contains the restricted report | `tests/e2e/test_export_journey.py` |
| J-04 | API export × role matrix and request shapes (contract J3): every canonical/variant response matches the table above, and no parameter or header variant widens the set beyond the header-only baseline | `tests/integration/test_csv_export.py` (browser legs in `tests/e2e/test_export_journey.py`) |
| J-05 | Restricted report never appears (contract J4): no row and no cell contains it for viewer/absent/unknown/`ADMIN` treatments on either surface; permanent regression test with a non-vacuous admin positive control | `tests/integration/test_csv_export.py`, `tests/e2e/test_export_journey.py` |
