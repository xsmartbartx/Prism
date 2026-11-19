"""Database sources through the API: list tables, import, refresh, schedule, credentials."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from core.clock import utcnow
from data.connectors.link import Fetched, LinkPolicy
from data.connectors.postgres import DatabaseError, PgSource, TableInfo, _parquet, rows_fingerprint
from server.db.models import AuditEvent, DatasetLink, Import
from server.services import links
from tests.server.test_api import H, client, setup_admin

__all__ = ["client"]

CONN = {"host": "db.example.com", "port": 5432, "database": "shop", "user": "reader",
        "password": "hunter2-db", "sslmode": "require"}
NAMES = ["Region", "Units"]
V1 = [["EU", 3], ["US", 5], ["APAC", 8]]


class FakeDb:
    def __init__(self) -> None:
        self.rows = [list(r) for r in V1]
        self.error: Exception | None = None
        self.calls: list[dict[str, Any]] = []

    def tables(self, src: PgSource, password: str, policy: LinkPolicy) -> list[TableInfo]:
        self.calls.append({"op": "tables", "password": password, "host": src.host})
        if self.error:
            raise self.error
        return [TableInfo("orders", "table", 3), TableInfo("sales.big", "view", None)]

    def read(self, src: PgSource, password: str, policy: LinkPolicy, *, max_rows: int,
             known: str | None = None) -> Fetched:
        self.calls.append({"op": "read", "password": password, "table": src.table,
                           "known": known, "max_rows": max_rows})
        if self.error:
            raise self.error
        etag = "rows:" + rows_fingerprint(NAMES, self.rows)
        if known == etag:
            return Fetched(url=src.to_url(), not_modified=True, etag=etag)
        return Fetched(url=src.to_url(), data=_parquet(NAMES, self.rows), kind="parquet",
                       filename=f"{src.table.rpartition('.')[2]}.parquet", etag=etag)


def _fake(c: TestClient) -> FakeDb:
    fake = FakeDb()
    svc = c.app.state.services  # type: ignore[attr-defined]
    svc.db_tables, svc.db_read = fake.tables, fake.read
    return fake


def _svc(c: TestClient) -> Any:
    return c.app.state.services  # type: ignore[attr-defined]


def _import(c: TestClient, table: str = "orders") -> dict[str, Any]:
    r = c.post("/api/v1/imports/database", json={**CONN, "table": table}, headers=H)
    assert r.status_code == 201, r.text
    imp = r.json()
    p = imp["proposal"]
    body = {
        "dataset_name": "Orders",
        "header_row": p["header_row"],
        "data_start_row": p["data_start_row"],
        "columns": [{k: col[k] for k in ("index", "source_name", "name", "type", "role")}
                    for col in p["columns"]],
    }
    r = c.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H)
    assert r.status_code == 201, r.text
    return {"import": imp, "dataset": r.json()}


def _refresh(c: TestClient, dataset_id: str) -> dict[str, Any]:
    r = c.post(f"/api/v1/datasets/{dataset_id}/link/refresh", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_import_and_refresh(client: TestClient) -> None:
    setup_admin(client)
    fake = _fake(client)
    r = client.post("/api/v1/imports/database/tables", json=CONN, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["tables"] == [
        {"name": "orders", "kind": "table", "rows": 3},
        {"name": "sales.big", "kind": "view", "rows": None},
    ]
    assert fake.calls[-1]["password"] == "hunter2-db"

    made = _import(client)
    imp, ds = made["import"], made["dataset"]
    assert (imp["filename"], imp["file_kind"], imp["source_kind"], imp["source_host"]) == (
        "orders.parquet", "parquet", "database", "db.example.com",
    )
    assert ds["row_count"] == 3
    link = client.get(f"/api/v1/datasets/{ds['id']}/link").json()["link"]
    assert link["kind"] == "database"
    assert link["label"] == "db.example.com/shop · orders"
    assert link["url"] == "postgresql://reader@db.example.com:5432/shop?sslmode=require&table=orders"

    # The password is stored only encrypted, only on the link, and is never sent back.
    with _svc(client).db.transaction() as s:
        row = s.scalars(select(DatasetLink)).one()
        assert row.secret and "hunter2" not in row.secret
        assert all(i.source_secret is None for i in s.scalars(select(Import)))
        audit = " ".join(str(e.details) + e.description for e in s.scalars(select(AuditEvent)))
    assert "hunter2" not in audit
    assert "hunter2" not in client.get(f"/api/v1/imports/{imp['id']}").text
    assert "hunter2" not in client.get(f"/api/v1/datasets/{ds['id']}/link").text

    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "unchanged"
    assert fake.calls[-1]["password"] == "hunter2-db" and fake.calls[-1]["known"] is None
    assert fake.calls[-1]["max_rows"] == 1_000_000

    fake.rows = list(reversed(V1))  # same rows, another order: still unchanged
    assert _refresh(client, ds["id"])["outcome"]["status"] == "unchanged"
    assert fake.calls[-1]["known"] and fake.calls[-1]["known"].startswith("rows:")

    fake.rows = [*V1, ["LATAM", 2]]
    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "loaded" and out["dataset"]["row_count"] == 4

    fake.error = DatabaseError("The database refused the user name or password for reader")
    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "failed" and "refused" in out["outcome"]["error"]


def test_schedule_and_limits_of_editing(client: TestClient) -> None:
    setup_admin(client)
    fake = _fake(client)
    ds = _import(client)["dataset"]
    base = f"/api/v1/datasets/{ds['id']}/link"
    link = client.get(base).json()["link"]

    r = client.put(base, json={"url": link["url"], "schedule": "daily"}, headers=H)
    assert r.status_code == 200 and r.json()["link"]["schedule"] == "daily"
    other = link["url"].replace("table=orders", "table=secrets")
    r = client.put(base, json={"url": other, "schedule": "daily"}, headers=H)
    assert r.status_code == 400 and "Connect a database" in r.text

    fake.rows = [*V1, ["LATAM", 2]]
    assert links.run_due(_svc(client), now=utcnow() + timedelta(days=1, minutes=1)) == 1
    assert client.get(f"/api/v1/datasets/{ds['id']}").json()["row_count"] == 4
    assert fake.calls[-1]["password"] == "hunter2-db"

    # Pointing the dataset at an https link drops the stored password.
    client.put(base, json={"url": "https://data.test/orders.csv", "schedule": "manual"}, headers=H)
    with _svc(client).db.transaction() as s:
        assert s.scalars(select(DatasetLink)).one().secret is None


def test_a_changed_secret_key_asks_for_the_password_again(client: TestClient) -> None:
    setup_admin(client)
    _fake(client)
    ds = _import(client)["dataset"]
    _svc(client).secret_key = "a-different-instance-key-0123456789"
    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "failed" and "enter it again" in out["outcome"]["error"]


def test_details_are_checked_and_internal_hosts_refused(client: TestClient) -> None:
    setup_admin(client)
    for body, message in (
        ({**CONN, "host": "db.example.com/x"}, "host name"),
        ({**CONN, "sslmode": "prefer"}, "SSL mode"),
        ({**CONN, "port": 0}, "port"),
    ):
        r = client.post("/api/v1/imports/database/tables", json=body, headers=H)
        assert r.status_code in (400, 422), r.text
        if r.status_code == 400:
            assert message in r.json()["error"]["message"]
    # The real connector refuses loopback and metadata addresses before connecting.
    for host in ("127.0.0.1", "169.254.169.254", "localhost"):
        r = client.post("/api/v1/imports/database/tables", json={**CONN, "host": host}, headers=H)
        assert r.status_code == 400 and "may not connect" in r.text, r.text
