"""Lifecycle management through the API: update, certify, delete, cascade."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.server.test_api import CHART, CORPUS, PASSWORD, H, client, import_sales, setup_admin

__all__ = ["client"]


def _invite(c: TestClient, email: str, role: str) -> TestClient:
    inv = c.post("/api/v1/workspace/invites", json={"email": email, "role": role}, headers=H).json()
    other = TestClient(c.app)
    token = inv["link"].rsplit("/", 1)[1]
    assert other.post(f"/api/v1/invites/{token}/accept", json={"password": PASSWORD}, headers=H).status_code == 200
    return other


def test_dataset_update_certify_and_versions(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    did = ds["id"]
    r = client.patch(f"/api/v1/datasets/{did}", json={"status": "certified"}, headers=H)
    assert r.status_code == 400 and "description" in r.json()["error"]["message"]
    r = client.patch(f"/api/v1/datasets/{did}", json={"description": "Orders", "status": "certified", "name": "Orders"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "certified" and r.json()["name"] == "Orders"

    author = _invite(client, "author@acme.test", "author")
    r = author.patch(f"/api/v1/datasets/{did}", json={"status": "deprecated"}, headers=H)
    assert r.status_code == 403  # only stewards certify/deprecate

    full = client.get(f"/api/v1/datasets/{did}").json()
    vid = full["versions"][0]["id"]
    v = client.get(f"/api/v1/datasets/{did}/versions/{vid}").json()
    assert v["version"] == 1 and v["profile"]["row_count"] == 6
    assert client.get(f"/api/v1/datasets/{did}/quarantine").json() == []
    xlsx = client.get(f"/api/v1/datasets/{did}/export?format=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_quarantine_rows_listed(client: TestClient) -> None:
    setup_admin(client)
    raw = (CORPUS / "title-rows.csv").read_bytes() + b"".join(b"A-9%03d,EU,2026-04-01,%d\n" % (i, i) for i in range(30)) + b"A-999,EU,someday,1\n"
    imp = client.post("/api/v1/imports", files={"file": ("q.csv", raw, "text/csv")}, headers=H).json()
    p = imp["proposal"]
    body = {"dataset_name": "Q", "header_row": p["header_row"], "data_start_row": p["data_start_row"],
            "columns": [{k: c[k] for k in ("index", "source_name", "name", "type", "role")} for c in p["columns"]]}
    ds = client.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H).json()
    assert ds["load"]["quarantined"] == 1
    q = client.get(f"/api/v1/datasets/{ds['id']}/quarantine").json()
    assert len(q) == 1 and "someday" in q[0]["_reason"]
    again = client.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H)
    assert again.status_code == 400  # an import publishes once


def test_chart_and_dashboard_lifecycle_with_cascade(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    chart = client.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "A", **CHART}, headers=H).json()
    upd = {**CHART, "view": {**CHART["view"], "mark": "pie"}}
    r = client.put(f"/api/v1/charts/{chart['id']}", json={"dataset_id": ds["id"], "name": "A2", **upd}, headers=H)
    assert r.status_code == 200 and r.json()["view"]["mark"] == "pie" and r.json()["name"] == "A2"

    bad = {**CHART, "view": {**CHART["view"], "encodings": [{"channel": "x", "field": "Nope"}, {"channel": "y", "field": "Revenue"}]}}
    r = client.put(f"/api/v1/charts/{chart['id']}", json={"dataset_id": ds["id"], "name": "A2", **bad}, headers=H)
    assert r.status_code == 400 and "Nope" in r.json()["error"]["message"]

    data = client.get(f"/api/v1/charts/{chart['id']}/data").json()
    assert data["total"] == 3 and data["dataset_version"] == 1
    big = client.get(f"/api/v1/charts/{chart['id']}/render?width=1200&height=600&theme=light")
    assert 'width="1200"' in big.text
    assert client.get(f"/api/v1/charts?dataset_id={ds['id']}").json()[0]["id"] == chart["id"]

    dash = client.post("/api/v1/dashboards", json={"name": "D", "layout": [{"chart_id": chart["id"], "w": 99, "x": -4}]}, headers=H).json()
    assert dash["layout"][0]["w"] == 12 and dash["layout"][0]["x"] == 0  # clamped
    r = client.put(f"/api/v1/dashboards/{dash['id']}", json={"name": "D2", "layout": []}, headers=H)
    assert r.json()["name"] == "D2" and r.json()["layout"] == []
    client.put(f"/api/v1/dashboards/{dash['id']}", json={"name": "D2", "layout": [{"chart_id": chart["id"]}]}, headers=H)
    r = client.put(f"/api/v1/dashboards/{dash['id']}", json={"name": "D2", "layout": [{"chart_id": "missing"}]}, headers=H)
    assert r.status_code == 404

    share = client.post("/api/v1/shares", json={"artifact_type": "chart", "artifact_id": chart["id"]}, headers=H).json()
    assert len(client.get(f"/api/v1/shares?artifact_id={chart['id']}").json()) == 1

    # Deleting the dataset removes its charts, strips dashboards and revokes links.
    assert client.delete(f"/api/v1/datasets/{ds['id']}", headers=H).status_code == 204
    assert client.get(f"/api/v1/charts/{chart['id']}").status_code == 404
    assert client.get(f"/api/v1/dashboards/{dash['id']}").json()["layout"] == []
    assert TestClient(client.app).get(f"/s/{share['token']}").status_code == 404
    assert client.delete(f"/api/v1/dashboards/{dash['id']}", headers=H).status_code == 204
    assert client.get("/api/v1/dashboards").json() == []


def test_explorer_owns_personal_charts_only(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    admin_chart = client.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "Admin", **CHART}, headers=H).json()
    explorer = _invite(client, "ex@acme.test", "explorer")
    mine = explorer.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "Mine", **CHART}, headers=H)
    assert mine.status_code == 201
    r = explorer.put(f"/api/v1/charts/{admin_chart['id']}", json={"dataset_id": ds["id"], "name": "Hijack", **CHART}, headers=H)
    assert r.status_code == 403
    assert explorer.delete(f"/api/v1/charts/{admin_chart['id']}", headers=H).status_code == 403
    assert explorer.delete(f"/api/v1/charts/{mine.json()['id']}", headers=H).status_code == 204


def test_workspaces_are_isolated(client: TestClient) -> None:
    setup_admin(client)
    ds = import_sales(client)
    ws = client.post("/api/v1/workspace/new", json={"name": "Other"}, headers=H).json()
    other = {"X-Prism-Workspace": ws["id"], **H}
    assert client.get("/api/v1/datasets", headers=other).json() == []
    assert client.get(f"/api/v1/datasets/{ds['id']}", headers=other).status_code == 404
    assert client.get("/api/v1/datasets", headers={"X-Prism-Workspace": "nope"}).status_code == 403
    me = client.get("/api/v1/auth/me", headers=other).json()
    assert me["workspace"]["name"] == "Other" and len(me["workspaces"]) == 2


def test_profile_password_and_reset_link(client: TestClient) -> None:
    setup_admin(client)
    assert client.patch("/api/v1/auth/me", json={"name": "Ada L."}, headers=H).json()["name"] == "Ada L."
    r = client.post("/api/v1/auth/password", json={"current_password": "wrong-wrong-wrong", "new_password": "a brand new secret"}, headers=H)
    assert r.status_code == 400
    r = client.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "a brand new secret"}, headers=H)
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200  # current session kept

    viewer = _invite(client, "v@acme.test", "viewer")
    uid = next(m["id"] for m in client.get("/api/v1/workspace/members").json() if m["email"] == "v@acme.test")
    link = client.post(f"/api/v1/workspace/members/{uid}/reset-link", headers=H).json()["link"]
    token = link.rsplit("/", 1)[1]
    assert TestClient(client.app).get(f"/api/v1/invites/{token}").json()["kind"] == "reset"
    r = TestClient(client.app).post(f"/api/v1/invites/{token}/accept", json={"password": "reset password ok"}, headers=H)
    assert r.status_code == 200
    assert viewer.get("/api/v1/auth/me").status_code == 401  # old sessions revoked
    assert client.delete(f"/api/v1/workspace/members/{uid}", headers=H).status_code == 204
    pending = client.post("/api/v1/workspace/invites", json={"email": "p@acme.test"}, headers=H).json()
    assert client.delete(f"/api/v1/workspace/invites/{pending['id']}", headers=H).status_code == 204
    assert client.get("/api/v1/workspace/invites").json() == []
