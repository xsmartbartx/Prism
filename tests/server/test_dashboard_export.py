"""Dashboard export: one workbook, a sheet per chart, filters applied and summarised."""

from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from presentation.export import sheet_names, to_xlsx_workbook
from tests.server.test_api import client
from tests.server.test_dashboard_filters_api import _setup

__all__ = ["client"]


def _book(content: bytes) -> dict[str, list[list[Any]]]:
    wb = load_workbook(io.BytesIO(content), read_only=True)
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def test_export_applies_and_summarises_filters(client: TestClient) -> None:
    _, b, dash = _setup(client)
    did = dash["id"]
    r = client.get(f"/api/v1/dashboards/{did}/export?format=xlsx&fv0=EU")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="sales.xlsx"' in r.headers["content-disposition"].lower()
    book = _book(r.content)
    assert list(book) == ["About", "By region", "Units"]
    about = {row[0]: row[1] for row in book["About"]}
    assert about["Dashboard"] == "Sales" and about["Filter: Region"] == "EU"
    assert about["Units"] == "Not filtered by Region"  # that chart's data has no Region
    regions = [row[0] for row in book["By region"][1:]]
    assert regions == ["EU"]

    # A click selection applies to every chart but the one clicked.
    r = client.get(f"/api/v1/dashboards/{did}/export?fv0=EU&fv0=US&xf=Region&xv=US&xc={b}")
    book = _book(r.content)
    assert [row[0] for row in book["By region"][1:]] == ["US"]
    assert "Filter: Region" in {row[0] for row in book["About"]}

    # Exports are audited.
    from sqlalchemy import select

    from server.db.models import AuditEvent

    with client.app.state.services.db.transaction() as s:  # type: ignore[attr-defined]
        actions = s.scalars(select(AuditEvent.action).where(AuditEvent.target_id == did)).all()
    assert actions.count("dashboard.export") == 2


def test_export_requires_sign_in(client: TestClient) -> None:
    _, _, dash = _setup(client)
    anon = TestClient(client.app)
    assert anon.get(f"/api/v1/dashboards/{dash['id']}/export").status_code == 401
    assert client.get(f"/api/v1/dashboards/{dash['id']}/export?format=pdf").status_code == 422


def test_sheet_names_are_safe_and_unique() -> None:
    names = sheet_names(["Sales: Q1/Q2 [EU]", "x" * 40, "x" * 40, "about", "About", "''"])
    assert names[0] == "Sales_ Q1_Q2 _EU_"
    assert len(names[1]) == 31 and names[2].endswith("(2)") and len(names[2]) == 31
    assert names[3] == "about" and names[4] == "About (2)" and names[5] == "Sheet"


def test_workbook_neutralises_formulas() -> None:
    content = to_xlsx_workbook(
        [("=cmd", ["=x", "n"], [{"=x": "=HYPERLINK(\"http://evil\")", "n": -5}])],
        summary=[("Filter: =a", "=b")],
    )
    book = _book(content)
    assert book["About"][0] == ["Filter: =a", "'=b"]
    sheet = book["=cmd"]
    assert sheet[0][0] == "'=x" and sheet[1][0].startswith("'=HYPERLINK") and sheet[1][1] == -5
