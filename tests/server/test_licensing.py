"""License verification, plan evaluation and enforcement."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from core.clock import utcnow
from server.app import create_app
from server.config import Settings
from server.services.licensing import GRACE_DAYS, LicenseError, evaluate, verify_key
from tests.server.test_api import CHART, PASSWORD, H, import_sales, setup_admin
from tools.issue_license import make_payload, public_key_of, sign

VENDOR = Ed25519PrivateKey.generate()
PUB = public_key_of(VENDOR)


def key(plan: str = "pro", months: int | None = 12, **kw: object) -> str:
    return sign(VENDOR, make_payload(customer="Acme", email="it@acme.test", plan=plan,
                                     months=months, **kw))  # type: ignore[arg-type]


def test_verify_roundtrip_and_tamper() -> None:
    k = key()
    assert verify_key(k, PUB)["plan"] == "pro"
    head, body, sig = k.split(".")
    forged = f"{head}.{body[:-2]}xx.{sig}"
    with pytest.raises(LicenseError):
        verify_key(forged, PUB)
    with pytest.raises(LicenseError):
        verify_key(key(), public_key_of(Ed25519PrivateKey.generate()))
    with pytest.raises(LicenseError):
        verify_key("garbage", PUB)


def test_evaluate_states() -> None:
    assert evaluate(None).status == "community"
    assert evaluate("PRISM1.x.y", public_key=PUB).status == "invalid"
    active = evaluate(key(seats=40), public_key=PUB)
    assert active.status == "active" and active.plan.max_users == 40
    assert "embed" in active.plan.features
    perpetual = evaluate(key(months=None), public_key=PUB)
    assert perpetual.status == "active" and perpetual.expires_at is None
    exp = active.expires_at
    assert exp is not None
    grace = evaluate(key(), public_key=PUB, now=exp + timedelta(days=1))
    assert grace.status == "grace" and grace.plan.code == "pro"
    expired = evaluate(key(), public_key=PUB, now=exp + timedelta(days=GRACE_DAYS + 1))
    assert expired.status == "expired" and expired.plan.code == "community"
    soon = evaluate(key(), public_key=PUB, now=exp - timedelta(days=5))
    assert soon.warnings


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(env="test", data_dir=tmp_path / "var", secret_key="k" * 32,
                        base_url="http://testserver", license_public_key=PUB)
    with TestClient(create_app(settings)) as c:
        yield c


def test_community_blocks_pro_features(client: TestClient) -> None:
    setup_admin(client)
    r = client.post("/api/v1/workspace/api-keys", json={"name": "x"}, headers=H)
    assert r.status_code == 402 and "API keys" in r.json()["error"]["message"]
    ds = import_sales(client)
    chart = client.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "c", **CHART}, headers=H).json()
    r = client.post("/api/v1/shares", json={"artifact_type": "chart", "artifact_id": chart["id"], "allow_embed": True}, headers=H)
    assert r.status_code == 402
    lic = client.get("/api/v1/admin/license").json()
    assert lic["status"] == "community" and lic["usage"]["datasets"] == 1
    assert lic["plan"]["limits"]["datasets"] == 10


def test_community_dataset_limit(client: TestClient) -> None:
    setup_admin(client)
    for _ in range(10):
        import_sales(client)
    raw = b"a,b\n1,2\n"
    imp = client.post("/api/v1/imports", files={"file": ("x.csv", raw, "text/csv")}, headers=H).json()
    p = imp["proposal"]
    r = client.post(f"/api/v1/imports/{imp['id']}/commit", headers=H, json={
        "dataset_name": "11th", "header_row": p["header_row"], "data_start_row": p["data_start_row"],
        "columns": [{k: c[k] for k in ("index", "source_name", "name", "type", "role")} for c in p["columns"]],
    })
    assert r.status_code == 402 and "10 datasets" in r.json()["error"]["message"]


def test_install_license_unlocks_and_removes_branding(client: TestClient) -> None:
    setup_admin(client)
    bad = client.put("/api/v1/admin/license", json={"key": "PRISM1.bad.key"}, headers=H)
    assert bad.status_code == 400
    r = client.put("/api/v1/admin/license", json={"key": key("pro")}, headers=H)
    assert r.status_code == 200 and r.json()["plan"]["code"] == "pro"
    assert client.post("/api/v1/workspace/api-keys", json={"name": "ci"}, headers=H).status_code == 201
    ds = import_sales(client)
    chart = client.post("/api/v1/charts", json={"dataset_id": ds["id"], "name": "c", **CHART}, headers=H).json()
    share = client.post("/api/v1/shares", json={"artifact_type": "chart", "artifact_id": chart["id"], "allow_embed": True}, headers=H).json()
    page = TestClient(client.app).get(f"/s/{share['token']}").text
    assert "Made with" not in page
    assert TestClient(client.app).get(f"/embed/{share['token']}").status_code == 200
    # Removing the license downgrades: API keys stop working, embeds stop rendering
    client.delete("/api/v1/admin/license", headers=H)
    assert TestClient(client.app).get(f"/embed/{share['token']}").status_code == 404
    assert "Made with" in TestClient(client.app).get(f"/s/{share['token']}").text


def test_non_owner_cannot_manage_license(client: TestClient) -> None:
    setup_admin(client)
    client.put("/api/v1/admin/license", json={"key": key("pro")}, headers=H)
    inv = client.post("/api/v1/workspace/invites", json={"email": "a2@acme.test", "role": "admin"}, headers=H).json()
    other = TestClient(client.app)
    other.post(f"/api/v1/invites/{inv['link'].rsplit('/', 1)[1]}/accept", json={"password": PASSWORD}, headers=H)
    assert other.put("/api/v1/admin/license", json={"key": key("business")}, headers=H).status_code == 403


def test_seat_limit_counts_pending_invites(client: TestClient) -> None:
    setup_admin(client)
    for i in range(4):
        r = client.post("/api/v1/workspace/invites", json={"email": f"u{i}@acme.test"}, headers=H)
        assert r.status_code == 201
    r = client.post("/api/v1/workspace/invites", json={"email": "u9@acme.test"}, headers=H)
    assert r.status_code == 402 and "5 users" in r.json()["error"]["message"]


def test_cli_tool_issue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.issue_license import main

    monkeypatch.chdir(tmp_path)
    assert main(["keygen", "--out", "k.pem"]) == 0
    assert main(["keygen", "--out", "k.pem"]) == 1  # never overwrite
    assert main(["issue", "--key", "k.pem", "--customer", "X", "--email", "x@y.z",
                 "--plan", "business", "--months", "0"]) == 0
    (tmp_path / "link.pem").symlink_to(tmp_path / "k.pem")
    for bad in ("../k.pem", "/etc/k.pem", "k.txt", "missing.pem", "link.pem"):
        with pytest.raises(SystemExit):
            main(["issue", "--key", bad, "--customer", "X", "--email", "x@y.z", "--plan", "pro"])


def test_utc_now_sanity() -> None:
    assert utcnow().tzinfo is not None
