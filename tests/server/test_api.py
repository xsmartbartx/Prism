"""End-to-end API tests through the HTTP layer (TestClient)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings

CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "parser-corpus"
H = {"X-Prism-CSRF": "1"}
PASSWORD = "correct horse battery"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from tests.server.test_licensing import PUB, key

    settings = Settings(env="test", data_dir=tmp_path / "var", secret_key="k" * 32,
                        base_url="http://testserver", license_public_key=PUB,
                        license_key=key("business"))
    with TestClient(create_app(settings)) as c:
        yield c


def setup_admin(c: TestClient) -> dict[str, Any]:
    r = c.post("/api/v1/setup", json={"email": "admin@acme.test", "name": "Ada",
                                       "password": PASSWORD, "workspace_name": "Acme"}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def import_sales(c: TestClient) -> dict[str, Any]:
    raw = (CORPUS / "title-rows.csv").read_bytes()
    r = c.post("/api/v1/imports", files={"file": ("sales.csv", raw, "text/csv")}, headers=H)
    assert r.status_code == 201, r.text
    imp = r.json()
    p = imp["proposal"]
    body = {
        "dataset_name": "Sales",
        "header_row": p["header_row"],
        "data_start_row": p["data_start_row"],
        "locale": p["locale"],
        "columns": [
            {k: col[k] for k in ("index", "source_name", "name", "type", "role", "locale")}
            for col in p["columns"]
        ],
    }
    r = c.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


CHART = {
    "query": {"dimensions": ["Region"], "measures": [{"column": "Revenue", "function": "sum"}],
              "sort": [{"column": "Revenue", "direction": "desc"}]},
    "view": {"mark": "bar", "title": "Revenue by region",
             "encodings": [{"channel": "x", "field": "Region"}, {"channel": "y", "field": "Revenue"}]},
}


def test_health_and_setup_flow(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "ready"
    assert client.get("/api/v1/setup/status").json() == {"needs_setup": True}
    assert client.get("/api/v1/auth/me").status_code == 401
    setup_admin(client)
    assert client.get("/api/v1/setup/status").json() == {"needs_setup": False}
    me = client.get("/api/v1/auth/me").json()
    assert me["user"]["email"] == "admin@acme.test" and me["role"] == "admin"
    # Setup only once
    r = client.post("/api/v1/setup", json={"email": "x@y.test", "password": PASSWORD}, headers=H)
    assert r.status_code == 409


def test_security_headers_and_csrf(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    r = client.post("/api/v1/setup", json={"email": "a@b.test", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CsrfRejected"


def test_weak_password_rejected(client: TestClient) -> None:
    r = client.post("/api/v1/setup", json={"email": "a@b.test", "password": "short"}, headers=H)
    assert r.status_code == 400 and "at least" in r.json()["error"]["message"]


def test_login_logout_and_rate_limit(client: TestClient) -> None:
    setup_admin(client)
    client.post("/api/v1/auth/logout", headers=H)
    assert client.get("/api/v1/auth/me").status_code == 401
    for _ in range(10):
        r = client.post("/api/v1/auth/login", json={"email": "admin@acme.test", "password": "nope-nope-nope"}, headers=H)
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "admin@acme.test", "password": PASSWORD}, headers=H)
    assert r.status_code == 429


def test_full_pipeline_import_chart_dashboard_share(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    assert ds["row_count"] == 6 and ds["load"]["quarantined"] == 0
    did = ds["id"]

    listing = client.get("/api/v1/datasets").json()
    assert listing[0]["id"] == did and listing[0]["row_count"] == 6

    rows = client.get(f"/api/v1/datasets/{did}/rows?limit=2").json()
    assert rows["total"] == 6 and len(rows["rows"]) == 2

    q = client.post(f"/api/v1/datasets/{did}/query", json=CHART["query"], headers=H).json()
    assert q["rows"][0]["Region"] == "APAC" and q["rows"][0]["Revenue"] == 4300.0

    bad = client.post(f"/api/v1/datasets/{did}/query", json={"dimensions": ["Nope"]}, headers=H)
    assert bad.status_code == 400 and "Nope" in bad.json()["error"]["message"]

    rec = client.post(f"/api/v1/datasets/{did}/recommend", json={"fields": ["Order Date", "Revenue"]}, headers=H).json()
    assert rec["view"]["mark"] == "line"

    prev = client.post("/api/v1/charts/preview", json={"dataset_id": did, **CHART}, headers=H).json()
    assert prev["svg"].startswith("<svg") and prev["total"] == 3

    chart = client.post("/api/v1/charts", json={"dataset_id": did, "name": "Revenue", **CHART}, headers=H).json()
    svg = client.get(f"/api/v1/charts/{chart['id']}/render?theme=dark")
    assert svg.headers["content-type"].startswith("image/svg+xml") and "#0d1117" in svg.text

    csv = client.get(f"/api/v1/charts/{chart['id']}/export?format=csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    assert "APAC" in csv.content.decode("utf-8-sig")

    dash = client.post("/api/v1/dashboards", json={"name": "Exec", "layout": [{"chart_id": chart["id"], "w": 12}]}, headers=H).json()
    full = client.get(f"/api/v1/dashboards/{dash['id']}").json()
    assert chart["id"] in full["charts"]

    share = client.post("/api/v1/shares", json={"artifact_type": "dashboard", "artifact_id": dash["id"]}, headers=H).json()
    assert share["url"].startswith("http://testserver/s/")
    token = share["token"]

    anon = TestClient(client.app)
    page = anon.get(f"/s/{token}")
    assert page.status_code == 200 and "Exec" in page.text and "<svg" in page.text
    assert "<script" not in page.text
    assert anon.get(f"/embed/{token}").status_code == 404  # embedding not enabled

    client.delete(f"/api/v1/shares/{share['id']}", headers=H)
    gone = anon.get(f"/s/{token}")
    assert gone.status_code == 404 and "unavailable" in gone.text

    audit = client.get("/api/v1/audit").json()["events"]
    actions = {e["action"] for e in audit}
    assert {"dataset.load", "chart.create", "share.create", "share.revoke", "chart.export"} <= actions
    assert client.get("/api/v1/audit/verify").json()["ok"] is True


def test_embed_share_allows_framing(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    chart = client.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "R", **CHART}, headers=H).json()
    share = client.post("/api/v1/shares", json={"artifact_type": "chart", "artifact_id": chart["id"], "allow_embed": True, "expires_in_hours": 1}, headers=H).json()
    r = TestClient(client.app).get(f"/embed/{share['token']}")
    assert r.status_code == 200
    assert "x-frame-options" not in r.headers
    assert "frame-ancestors *" in r.headers["content-security-policy"]


def test_invites_roles_and_api_keys(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    inv = client.post("/api/v1/workspace/invites", json={"email": "viewer@acme.test", "role": "viewer"}, headers=H).json()
    token = inv["link"].rsplit("/", 1)[1]

    other = TestClient(client.app)
    assert other.get(f"/api/v1/invites/{token}").json()["workspace"] == "Acme"
    r = other.post(f"/api/v1/invites/{token}/accept", json={"name": "Vic", "password": PASSWORD}, headers=H)
    assert r.status_code == 200
    assert other.get("/api/v1/auth/me").json()["role"] == "viewer"
    # Viewer can read but not author
    assert other.get(f"/api/v1/datasets/{ds['id']}").status_code == 200
    r = other.post("/api/v1/imports", files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")}, headers=H)
    assert r.status_code == 403
    assert other.get("/api/v1/audit").status_code == 403
    # Invite links are single-use
    assert other.post(f"/api/v1/invites/{token}/accept", json={"password": PASSWORD}, headers=H).status_code == 404

    members = client.get("/api/v1/workspace/members").json()
    assert {m["email"] for m in members} == {"admin@acme.test", "viewer@acme.test"}

    key = client.post("/api/v1/workspace/api-keys", json={"name": "CI"}, headers=H).json()
    assert key["secret"].startswith("prism_")
    bearer = TestClient(client.app)
    auth = {"Authorization": f"Bearer {key['secret']}"}
    assert bearer.get("/api/v1/datasets", headers=auth).status_code == 200
    # Bearer requests are exempt from the CSRF header (no ambient credentials)
    q = bearer.post(f"/api/v1/datasets/{ds['id']}/query", json=CHART["query"], headers=auth)
    assert q.status_code == 200
    client.delete(f"/api/v1/workspace/api-keys/{key['id']}", headers=H)
    assert bearer.get("/api/v1/datasets", headers=auth).status_code == 401


def test_last_admin_cannot_be_demoted(client: TestClient) -> None:
    admin = setup_admin(client)
    uid = admin["user"]["id"]
    r = client.patch(f"/api/v1/workspace/members/{uid}", json={"role": "viewer"}, headers=H)
    assert r.status_code == 400


def test_refresh_drift_returns_422(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    r = client.post(f"/api/v1/datasets/{ds['id']}/refresh",
                    files={"file": ("s.csv", b"Order ID,Region\nA-1,EU\n", "text/csv")}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "DriftDetected"


def test_dataset_export_neutralizes_formulas(client: TestClient) -> None:
    setup_admin(client)
    raw = b"name,score\n=cmd|' /C calc'!A0,1\nbob,2\n"
    imp = client.post("/api/v1/imports", files={"file": ("x.csv", raw, "text/csv")}, headers=H).json()
    p = imp["proposal"]
    client.post(f"/api/v1/imports/{imp['id']}/commit", headers=H, json={
        "dataset_name": "X", "header_row": p["header_row"], "data_start_row": p["data_start_row"],
        "columns": [{k: c[k] for k in ("index", "source_name", "name", "type", "role")} for c in p["columns"]],
    })
    did = client.get("/api/v1/datasets").json()[0]["id"]
    text = client.get(f"/api/v1/datasets/{did}/export?format=csv").content.decode("utf-8-sig")
    assert "'=cmd" in text
