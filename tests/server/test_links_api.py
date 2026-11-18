"""Import from a link, refresh from it, and scheduled refresh (API and scheduler)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from core.clock import utcnow
from data.connectors.link import Fetched, LinkError, LinkPolicy
from server.app import create_app
from server.config import Settings
from server.db.models import AuditEvent, DatasetLink, Import, User
from server.services import links
from tests.server.test_api import H, client, setup_admin

__all__ = ["client"]

URL = "https://data.test/units.csv"
V1 = b"Region,Units\nEU,3\nUS,5\nAPAC,8\n"
V2 = V1 + b"LATAM,2\n"


class FakeLinks:
    """Stands in for the network: serves ``body`` for any link, or raises ``error``."""

    def __init__(self, body: bytes = V1) -> None:
        self.body = body
        self.etag: str | None = '"v1"'
        self.error: Exception | None = None
        self.not_modified = False
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        policy: LinkPolicy,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Fetched:
        self.calls.append({"url": url, "etag": etag, "max_bytes": policy.max_bytes})
        if self.error is not None:
            raise self.error
        if self.not_modified:
            return Fetched(url=url, not_modified=True, etag=etag)
        return Fetched(url=url, data=self.body, kind="csv", filename="units.csv", etag=self.etag)


def _fake(c: TestClient) -> FakeLinks:
    fake = FakeLinks()
    c.app.state.services.link_fetch = fake  # type: ignore[attr-defined]
    return fake


def _svc(c: TestClient) -> Any:
    return c.app.state.services  # type: ignore[attr-defined]


def _import_link(c: TestClient, url: str = URL) -> dict[str, Any]:
    r = c.post("/api/v1/imports/link", json={"url": url}, headers=H)
    assert r.status_code == 201, r.text
    imp = r.json()
    p = imp["proposal"]
    body = {
        "dataset_name": "Units",
        "header_row": p["header_row"],
        "data_start_row": p["data_start_row"],
        "columns": [
            {k: col[k] for k in ("index", "source_name", "name", "type", "role")}
            for col in p["columns"]
        ],
    }
    r = c.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H)
    assert r.status_code == 201, r.text
    return {"import": imp, "dataset": r.json()}


def _refresh(c: TestClient, dataset_id: str) -> dict[str, Any]:
    r = c.post(f"/api/v1/datasets/{dataset_id}/link/refresh", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _link_row(c: TestClient, dataset_id: str) -> DatasetLink:
    with _svc(c).db.transaction() as s:
        link = s.scalars(select(DatasetLink).where(DatasetLink.dataset_id == dataset_id)).one()
        s.expunge(link)
        return link


def test_import_from_link_and_refresh_now(client: TestClient) -> None:
    setup_admin(client)
    fake = _fake(client)
    made = _import_link(client)
    imp, ds = made["import"], made["dataset"]
    assert (imp["filename"], imp["source_host"], imp["file_kind"]) == ("units.csv", "data.test", "csv")
    assert ds["row_count"] == 3
    got = client.get(f"/api/v1/datasets/{ds['id']}/link").json()
    link = got["link"]
    assert got["can_schedule"] is True
    assert (link["url"], link["host"], link["schedule"], link["last_status"]) == (
        URL, "data.test", "manual", None,
    )

    # Same bytes: nothing new, and the server's ETag is kept for next time.
    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "unchanged" and out["dataset"]["current_version"]["version"] == 1
    assert fake.calls[-1]["etag"] is None

    fake.body, fake.etag = V2, '"v2"'
    out = _refresh(client, ds["id"])
    assert out["outcome"] == {"status": "loaded", "error": None, "version": 2, "rows": 4, "quarantined": 0}
    assert out["dataset"]["row_count"] == 4 and out["link"]["last_status"] == "loaded"
    assert fake.calls[-1]["etag"] == '"v1"'
    with _svc(client).db.transaction() as s:
        refreshed = s.scalars(select(Import).order_by(Import.created_at.desc())).first()
        assert refreshed is not None and refreshed.source_url == URL
        assert not Path(refreshed.storage_path).exists()  # downloads are not kept

    fake.not_modified = True
    assert _refresh(client, ds["id"])["outcome"]["status"] == "unchanged"
    assert fake.calls[-1]["etag"] == '"v2"'


def test_refresh_failures_are_recorded_not_raised(client: TestClient) -> None:
    setup_admin(client)
    fake = _fake(client)
    ds = _import_link(client)["dataset"]

    fake.body = b"Region,Count\nEU,3\n"  # Units is gone
    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "drift" and "Units" in out["outcome"]["error"]
    assert out["dataset"]["current_version"]["version"] == 1
    assert out["link"]["failures"] == 1

    fake.error = LinkError("data.test answered HTTP 500")
    out = _refresh(client, ds["id"])
    assert out["outcome"] == {"status": "failed", "error": "data.test answered HTTP 500",
                              "version": None, "rows": None, "quarantined": None}
    assert out["link"]["failures"] == 2 and out["link"]["last_error"] == "data.test answered HTTP 500"
    with _svc(client).db.transaction() as s:
        actions = s.scalars(select(AuditEvent.action).where(AuditEvent.target_id == ds["id"])).all()
    assert "dataset.drift" in actions and "dataset.refresh_failed" in actions

    fake.error, fake.body = None, V1
    out = _refresh(client, ds["id"])
    assert out["outcome"]["status"] == "unchanged" and out["link"]["failures"] == 0


def test_links_are_checked(client: TestClient) -> None:
    setup_admin(client)
    for url, message in (
        ("http://data.test/a.csv", "Only https"),
        ("https://u:p@data.test/a.csv", "user name or password"),
        ("https://127.0.0.1/a.csv", "may not reach"),  # the real fetcher, no network needed
        ("https://[::ffff:169.254.169.254]/latest", "may not reach"),
    ):
        r = client.post("/api/v1/imports/link", json={"url": url}, headers=H)
        assert r.status_code == 400 and message in r.json()["error"]["message"], r.text


def test_manage_the_link_and_schedule(client: TestClient) -> None:
    setup_admin(client)
    _fake(client)
    ds = _import_link(client)["dataset"]
    base = f"/api/v1/datasets/{ds['id']}/link"

    r = client.put(base, json={"url": URL, "schedule": "sometimes"}, headers=H)
    assert r.status_code == 400 and "Choose a schedule" in r.text
    r = client.put(base, json={"url": "ftp://data.test/x", "schedule": "daily"}, headers=H)
    assert r.status_code == 400

    link = client.put(base, json={"url": URL, "schedule": "daily"}, headers=H).json()["link"]
    assert link["schedule"] == "daily" and link["next_run_at"] is not None
    row = _link_row(client, ds["id"])
    assert row.next_run_at is not None
    assert timedelta(hours=23) < row.next_run_at - utcnow() <= timedelta(days=1)

    moved = client.put(base, json={"url": "https://data.test/v2.csv", "schedule": "daily"},
                       headers=H).json()["link"]
    assert moved["url"] == "https://data.test/v2.csv" and moved["last_status"] is None

    assert client.delete(base, headers=H).status_code == 204
    assert client.get(base).json()["link"] is None
    assert client.delete(base, headers=H).status_code == 404
    assert client.post(f"{base}/refresh", headers=H).status_code == 404

    # A link can be added to an uploaded dataset; deleting the dataset removes it.
    assert client.put(base, json={"url": URL}, headers=H).json()["link"]["schedule"] == "manual"
    assert client.delete(f"/api/v1/datasets/{ds['id']}", headers=H).status_code == 204
    with _svc(client).db.transaction() as s:
        assert s.scalars(select(DatasetLink)).all() == []


def test_scheduled_refresh(client: TestClient) -> None:
    setup_admin(client)
    fake = _fake(client)
    svc = _svc(client)
    ds = _import_link(client)["dataset"]
    base = f"/api/v1/datasets/{ds['id']}/link"
    client.put(base, json={"url": URL, "schedule": "hourly"}, headers=H)

    assert links.run_due(svc) == 0  # not due yet
    fake.body = V2
    later = utcnow() + timedelta(hours=1, minutes=1)
    assert links.run_due(svc, now=later) == 1
    assert client.get(f"/api/v1/datasets/{ds['id']}").json()["row_count"] == 4
    row = _link_row(client, ds["id"])
    assert row.last_status == "loaded" and row.lease_until is None
    assert row.next_run_at is not None and row.next_run_at - utcnow() > timedelta(minutes=55)
    with svc.db.transaction() as s:
        labels = s.scalars(
            select(AuditEvent.actor_label)
            .where(AuditEvent.action == "dataset.load")
            .order_by(AuditEvent.seq)
        ).all()
    assert labels[-1] == "admin@acme.test (schedule)"  # runs with the schedule owner's access

    # A link another process is refreshing is left alone.
    with svc.db.transaction() as s:
        link = s.scalars(select(DatasetLink)).one()
        link.next_run_at = utcnow() - timedelta(minutes=1)
        link.lease_until = utcnow() + timedelta(minutes=10)
    assert links.run_due(svc) == 0

    # Five failures in a row pause the schedule.
    fake.error = LinkError("data.test answered HTTP 503")
    for _ in range(links.MAX_FAILURES):
        with svc.db.transaction() as s:
            link = s.scalars(select(DatasetLink)).one()
            link.next_run_at, link.lease_until = utcnow() - timedelta(minutes=1), None
        assert links.run_due(svc) == 1
    row = _link_row(client, ds["id"])
    assert row.schedule == "manual" and row.next_run_at is None and "paused" in (row.last_error or "")


def test_schedule_pauses_when_its_owner_loses_access(client: TestClient) -> None:
    setup_admin(client)
    _fake(client)
    svc = _svc(client)
    ds = _import_link(client)["dataset"]
    client.put(f"/api/v1/datasets/{ds['id']}/link", json={"url": URL, "schedule": "weekly"}, headers=H)
    with svc.db.transaction() as s:
        user = s.scalars(select(User)).one()
        user.is_active = False
    assert links.run_due(svc, now=utcnow() + timedelta(weeks=1, minutes=1)) == 0
    row = _link_row(client, ds["id"])
    assert row.schedule == "manual" and "can no longer refresh" in (row.last_error or "")


@pytest.fixture
def community(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(env="test", data_dir=tmp_path / "var", secret_key="k" * 32,
                        base_url="http://testserver")
    with TestClient(create_app(settings)) as c:
        yield c


def test_community_refreshes_by_hand_only(community: TestClient) -> None:
    setup_admin(community)
    fake = _fake(community)
    ds = _import_link(community)["dataset"]
    assert fake.calls[0]["max_bytes"] == 25 * 1024 * 1024  # the plan's upload limit
    base = f"/api/v1/datasets/{ds['id']}/link"
    assert community.get(base).json()["can_schedule"] is False
    r = community.put(base, json={"url": URL, "schedule": "daily"}, headers=H)
    assert r.status_code == 402 and "Scheduled refresh from links" in r.text
    assert _refresh(community, ds["id"])["outcome"]["status"] == "unchanged"

    # A schedule left over from a lapsed plan is paused, not run.
    with _svc(community).db.transaction() as s:
        link = s.scalars(select(DatasetLink)).one()
        link.schedule, link.next_run_at = "daily", utcnow() - timedelta(minutes=1)
    assert links.run_due(_svc(community)) == 0
    assert "not included in the current plan" in (_link_row(community, ds["id"]).last_error or "")


def test_links_can_be_turned_off(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path / "var", secret_key="k" * 32,
                        base_url="http://testserver", link_imports=False)
    with TestClient(create_app(settings)) as c:
        setup_admin(c)
        r = c.post("/api/v1/imports/link", json={"url": URL}, headers=H)
        assert r.status_code == 403 and "turned off" in r.text
        assert links.run_due(_svc(c)) == 0
