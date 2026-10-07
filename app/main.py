"""FastAPI app: JSON API under /api plus a small browser UI at /."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import data
from app.csv_export import render_csv

BASE = Path(__file__).parent
app = FastAPI(title="pilot-target", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def _role(x_role: str | None) -> str:
    """Trial-grade auth: the role comes from a header. Good enough to test permission paths."""
    return data.ROLE_ADMIN if x_role == data.ROLE_ADMIN else data.ROLE_VIEWER


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/reports")
def api_reports(x_role: str | None = Header(default=None)) -> list[dict]:
    return [r.to_dict() for r in data.list_reports(_role(x_role))]


@app.get("/api/reports/export")
def api_reports_export(x_role: str | None = Header(default=None)) -> Response:
    """CSV download of every report the caller's role may see (contract C1-C5, C7).

    Registered before ``/api/reports/{report_id}`` so the static path is matched
    first and ``export`` is never consumed by the int route (C1). The role and
    the permitted set come from the one existing path, reused verbatim (C3).
    """
    body = render_csv(data.list_reports(_role(x_role)))
    date = datetime.now(UTC).date().strftime("%Y-%m-%d")
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="reports-{date}.csv"'},
    )


@app.get("/api/reports/{report_id}")
def api_report(report_id: int, x_role: str | None = Header(default=None)) -> dict:
    r = data.get_report(report_id, _role(x_role))
    if r is None:
        raise HTTPException(status_code=404, detail="report not found")
    return r.to_dict()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"title": "Reports"})
