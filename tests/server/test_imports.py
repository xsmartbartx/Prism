"""Import service: upload, proposal, commit, refresh, drift, audit."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.errors import DriftDetected
from data.load.store import DatasetStore
from server.config import Settings
from server.db.models import AuditEvent, Binding, DatasetVersion, ImportStatus, Role
from server.errors import BadRequest, Forbidden
from server.schemas import ColumnDecision, CommitImport
from server.services import audit
from server.services.context import Actor
from server.services.imports import ImportService, safe_filename
from tests.server.conftest import make_actor

CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "parser-corpus"


def _commit_req(imp, name: str = "Sales") -> CommitImport:  # type: ignore[no-untyped-def]
    p = imp.proposal
    return CommitImport(
        dataset_name=name,
        header_row=p["header_row"],
        data_start_row=p["data_start_row"],
        locale=p["locale"],
        sheet=p.get("sheet"),
        columns=[
            ColumnDecision(
                index=c["index"],
                source_name=c["source_name"],
                name=c["name"],
                type=c["type"],
                role=c["role"],
                locale=c["locale"],
            )
            for c in p["columns"]
        ],
    )


@pytest.fixture
def svc(settings: Settings, store: DatasetStore) -> ImportService:
    return ImportService(settings, store)


def test_upload_proposes_and_commit_creates_version(
    svc: ImportService, session: Session, actor: Actor, store: DatasetStore
) -> None:
    imp = svc.create(session, actor, "title-rows.csv", (CORPUS / "title-rows.csv").read_bytes())
    assert imp.status == ImportStatus.READY.value
    assert imp.proposal["header_row"] == 3
    loaded = svc.commit(session, actor, imp, _commit_req(imp))
    assert loaded.version.version == 1
    assert loaded.version.row_count == 6
    assert loaded.dataset.current_version_id == loaded.version.id
    table = store.read(loaded.version.parquet_path)
    assert table.column_names == ["Order ID", "Region", "Order Date", "Revenue"]
    assert imp.status == ImportStatus.LOADED.value
    actions = [e.action for e in session.scalars(select(AuditEvent).order_by(AuditEvent.seq))]
    assert actions == ["import.upload", "dataset.create", "binding.publish", "dataset.load"]
    ok, broken, n = audit.verify_chain(session)
    assert ok and broken is None and n == 4


def test_refresh_relocates_header_and_reuses_binding(
    svc: ImportService, session: Session, actor: Actor
) -> None:
    raw = (CORPUS / "title-rows.csv").read_bytes()
    imp = svc.create(session, actor, "sales.csv", raw)
    first = svc.commit(session, actor, imp, _commit_req(imp))
    moved = b"Extra banner line,,,\n" + raw + b"A-2000,EU,2026-04-01,10\n"
    second = svc.refresh(session, actor, first.dataset, "sales.csv", moved)
    assert second.version.version == 2
    assert second.version.row_count == 7
    assert second.version.binding_id == first.version.binding_id


def test_refresh_with_missing_column_is_drift(
    svc: ImportService, session: Session, actor: Actor
) -> None:
    imp = svc.create(session, actor, "s.csv", (CORPUS / "title-rows.csv").read_bytes())
    first = svc.commit(session, actor, imp, _commit_req(imp))
    broken = b"Order ID,Region,Revenue\nA-1,EU,5\n"
    with pytest.raises(DriftDetected):
        svc.refresh(session, actor, first.dataset, "s.csv", broken)
    versions = session.scalars(select(DatasetVersion)).all()
    assert len(versions) == 1


def test_xlsx_import(svc: ImportService, session: Session, actor: Actor) -> None:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Monthly report"])
    ws.append([])
    ws.append(["Product", "Units", "Price"])
    for i in range(10):
        ws.append([f"P{i}", i * 3, 9.99 + i])
    buf = io.BytesIO()
    wb.save(buf)
    imp = svc.create(session, actor, "report.xlsx", buf.getvalue())
    assert imp.sheet_names == [{"name": "Data", "hidden": False}]
    assert imp.proposal["header_row"] == 2
    types = [c["type"] for c in imp.proposal["columns"]]
    assert types == ["string", "integer", "float"]
    loaded = svc.commit(session, actor, imp, _commit_req(imp, "Products"))
    assert loaded.version.row_count == 10
    assert loaded.version.profile["columns"]["Units"]["max"] == 27


def _sqlite_bytes(tmp_path: Path, script: str) -> bytes:
    import sqlite3

    path = tmp_path / f"db-{abs(hash(script))}.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(script)
    conn.commit()
    conn.close()
    return path.read_bytes()


SHOP_DB = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
INSERT INTO customers VALUES (1, 'Ada', 'UK'), (2, 'Lin', 'SG');
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, placed TEXT, total REAL);
INSERT INTO orders VALUES (10, 1, '2026-01-05', 120.5), (11, 2, '2026-01-06', 80.25),
                          (12, 1, '2026-01-07', 99.99);
"""


def test_sqlite_import_picks_a_table_and_refreshes(
    svc: ImportService, session: Session, actor: Actor, tmp_path: Path
) -> None:
    raw = _sqlite_bytes(tmp_path, SHOP_DB)
    imp = svc.create(session, actor, "shop.db", raw)
    assert imp.file_kind == "sqlite"
    assert [t["name"] for t in imp.sheet_names] == ["customers", "orders"]
    assert imp.proposal["sheet"] == "customers"

    imp = svc.repropose(session, actor, imp, sheet="orders", header_row=None, locale=None)
    assert imp.proposal["sheet"] == "orders"
    assert imp.proposal["header_row"] == 0
    types = [c["type"] for c in imp.proposal["columns"]]
    assert types == ["integer", "integer", "date", "float"]
    with pytest.raises(BadRequest, match="Table 'nope' not found"):
        svc.repropose(session, actor, imp, sheet="nope", header_row=None, locale=None)

    loaded = svc.commit(session, actor, imp, _commit_req(imp, "Orders"))
    assert loaded.version.row_count == 3
    binding = session.get(Binding, loaded.version.binding_id)
    assert binding is not None
    assert binding.document["connector_type"] == "sqlite"
    assert binding.document["sheet_name"] == "orders"

    more = _sqlite_bytes(
        tmp_path, SHOP_DB + "INSERT INTO orders VALUES (13, 2, '2026-01-08', 15.0);"
    )
    second = svc.refresh(session, actor, loaded.dataset, "shop-feb.sqlite", more)
    assert second.version.version == 2
    assert second.version.row_count == 4
    assert second.version.binding_id == loaded.version.binding_id
    with pytest.raises(BadRequest, match="refreshed from SQLite files"):
        svc.refresh(session, actor, loaded.dataset, "orders.csv", b"id,total\n1,2\n")


def test_parquet_import(svc: ImportService, session: Session, actor: Actor) -> None:
    import io
    from datetime import date

    import pyarrow as pa
    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(
        pa.table(
            {
                "region": ["EU", "US", "EU", "APAC"],
                "day": [date(2026, 1, d) for d in range(1, 5)],
                "units": [3, 5, 8, 13],
            }
        ),
        buf,
    )
    imp = svc.create(session, actor, "sales.parquet", buf.getvalue())
    assert imp.file_kind == "parquet"
    assert imp.sheet_names == []
    assert [c["type"] for c in imp.proposal["columns"]] == ["string", "date", "integer"]
    loaded = svc.commit(session, actor, imp, _commit_req(imp, "Sales"))
    assert loaded.version.row_count == 4
    assert loaded.version.profile["columns"]["units"]["max"] == 13


def test_rejects_bad_uploads(svc: ImportService, session: Session, actor: Actor) -> None:
    with pytest.raises(BadRequest, match="Unsupported"):
        svc.create(session, actor, "evil.exe", b"MZ")
    with pytest.raises(BadRequest, match="empty"):
        svc.create(session, actor, "a.csv", b"")
    with pytest.raises(BadRequest, match="not a valid"):
        svc.create(session, actor, "a.xlsx", b"not a zip")
    with pytest.raises(BadRequest, match="not a SQLite"):
        svc.create(session, actor, "a.db", b"id,name\n1,a\n")
    with pytest.raises(BadRequest, match="not a valid Parquet"):
        svc.create(session, actor, "a.parquet", b"id,name\n1,a\n")


def test_viewer_cannot_import(svc: ImportService, session: Session, actor: Actor) -> None:
    viewer = make_actor(session, Role.VIEWER, "viewer@example.com")
    with pytest.raises(Forbidden):
        svc.create(session, viewer, "a.csv", b"a,b\n1,2\n")


def test_commit_validates_names(svc: ImportService, session: Session, actor: Actor) -> None:
    imp = svc.create(session, actor, "a.csv", b"a,b\n1,2\n3,4\n")
    req = _commit_req(imp)
    req.columns[1].name = "A"
    with pytest.raises(BadRequest, match="unique"):
        svc.commit(session, actor, imp, req)


def test_safe_filename() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\Users\\x\\Report Q1.xlsx") == "Report Q1.xlsx"
    assert safe_filename("<script>.csv") == "_script_.csv"
