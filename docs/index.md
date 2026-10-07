# pilot-target

A deliberately small reports web app. It exists so that an agent team can be evaluated on a
realistic delivery loop: plan → small tickets → PRs → protected merge → release to a real host.

- Browser UI at `/` lists reports visible to the selected role.
- JSON API under `/api` (see `api.md`).
- Health endpoint `/healthz`.

## Run locally

```
uv sync
uv run uvicorn app.main:app --reload
```

## Export CSV

The reports page has an **Export CSV** button next to the role selector. Clicking it sends the
role you selected to the server and downloads a `reports-YYYY-MM-DD.csv` file (today's UTC date,
named by the server) with one row per report the selected role may see — a viewer's file never
contains the admin-only report. The file opens in a spreadsheet app; a cell that starts with an
apostrophe is a neutralised would-be formula, not a typo. The same from the command line:

```
curl -H 'X-Role: admin' -OJ http://localhost:8000/api/reports/export
```

`-OJ` saves under the server-stated filename; send `X-Role: viewer` (or anything that is not
byte-exact `admin`, or no header at all) to get the viewer set as identical bytes minus the
restricted rows. See [api.md](api.md#csv-export) for the full contract.

## Tests

```
uv run ruff check .
uv run pytest tests/unit tests/integration
uv run playwright install chromium && uv run pytest tests/e2e
```

## Documentation policy

Any change under `app/` must touch `docs/` in the same PR, or the PR description must contain
the line `docs-impact: none` with a one-line reason. The `docs` CI check enforces this.
