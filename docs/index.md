# pilot-target

A deliberately small reports web app. It exists so that an agent team can be evaluated on a
realistic delivery loop: plan → small tickets → PRs → protected merge → release to a real host.

- Browser UI at `/` lists reports visible to the selected role.
- The "Export CSV" button on the reports page downloads every report the currently selected
  role may see as a CSV file. The download is fetched with the same `X-Role` header as the page
  list, so it always matches the table on screen.
- JSON API under `/api` (see `api.md`).
- Health endpoint `/healthz`.

## Run locally

```
uv sync
uv run uvicorn app.main:app --reload
```

## Tests

```
uv run ruff check .
uv run pytest tests/unit tests/integration
uv run playwright install chromium && uv run pytest tests/e2e
```

## Documentation policy

Any change under `app/` must touch `docs/` in the same PR, or the PR description must contain
the line `docs-impact: none` with a one-line reason. The `docs` CI check enforces this.
