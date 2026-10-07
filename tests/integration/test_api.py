from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_reports_viewer_default():
    r = client.get("/api/reports")
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [1, 2, 4]


def test_reports_admin_header():
    r = client.get("/api/reports", headers={"X-Role": "admin"})
    assert [x["id"] for x in r.json()] == [1, 2, 3, 4]


def test_restricted_report_404_for_viewer():
    assert client.get("/api/reports/3").status_code == 404
    assert client.get("/api/reports/3", headers={"X-Role": "admin"}).status_code == 200


def test_index_renders():
    r = client.get("/")
    assert r.status_code == 200 and "<table" in r.text


def test_index_has_export_control():
    r = client.get("/")
    assert 'id="export-csv"' in r.text and ">Export CSV<" in r.text
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "/api/reports/export" in js.text and "X-Role" in js.text
