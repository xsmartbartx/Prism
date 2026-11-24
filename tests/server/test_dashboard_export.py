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
    # An apostrophe that truncation leaves at the end is removed (Excel refuses it).
    shortened = sheet_names([("a" * 30) + "'b", ("a" * 26) + "'bbbb", ("a" * 26) + "'bbbb"])
    assert shortened[0] == "a" * 30
    assert not any(n.endswith("'") or n.startswith("'") for n in shortened)
    assert len(set(shortened)) == 3


def test_any_name_downloads(client: TestClient) -> None:
    _, _, dash = _setup(client)
    did = dash["id"]
    renamed = client.put(f"/api/v1/dashboards/{did}", headers={"X-Prism-CSRF": "1"},
                         json={"name": "销售 Ü", "layout": dash["layout"]})
    assert renamed.status_code == 200, renamed.text
    r = client.get(f"/api/v1/dashboards/{did}/export")
    assert r.status_code == 200, r.text
    disposition = r.headers["content-disposition"]
    assert 'filename="U.xlsx"' in disposition
    assert "filename*=UTF-8''%E9%94%80%E5%94%AE%20%C3%9C.xlsx" in disposition


def test_workbook_neutralises_formulas() -> None:
    content = to_xlsx_workbook(
        [("=cmd", ["=x", "n"], [{"=x": "=HYPERLINK(\"http://evil\")", "n": -5}])],
        summary=[("Filter: =a", "=b")],
    )
    book = _book(content)
    assert book["About"][0] == ["Filter: =a", "'=b"]
    sheet = book["=cmd"]
    assert sheet[0][0] == "'=x" and sheet[1][0].startswith("'=HYPERLINK") and sheet[1][1] == -5


def test_dataset_and_chart_exports_take_any_name(client: TestClient) -> None:
    a, _, _ = _setup(client)
    sales = next(d for d in client.get("/api/v1/datasets").json() if d["name"] == "Sales")
    h = {"X-Prism-CSRF": "1"}
    assert client.patch(f"/api/v1/datasets/{sales['id']}", json={"name": "Продажи"},
                        headers=h).status_code == 200
    r = client.get(f"/api/v1/datasets/{sales['id']}/export?format=csv")
    assert r.status_code == 200 and "filename*=UTF-8''" in r.headers["content-disposition"]
    chart = client.get(f"/api/v1/charts/{a}").json()
    client.put(f"/api/v1/charts/{a}", headers=h, json={**chart, "name": "Ventes Été"})
    r = client.get(f"/api/v1/charts/{a}/export?format=xlsx")
    assert r.status_code == 200 and "Ventes%20%C3%89t%C3%A9.xlsx" in r.headers["content-disposition"]


def test_pivot_chart_through_the_api(client: TestClient) -> None:
    from tests.server.test_api import H, setup_admin

    setup_admin(client)
    ds = client.post("/api/v1/datasets/sample", headers=H).json()["id"]  # has Region × Channel

    def pivot(function: str) -> str:
        body = {
            "dataset_id": ds, "name": f"Pivot {function}",
            "query": {"dimensions": ["Region", "Channel"],
                      "measures": [{"column": "Revenue", "function": function}], "limit": 5000},
            "view": {"mark": "pivot", "heatmap": True,
                     "encodings": [{"channel": "x", "field": "Region"},
                                   {"channel": "color", "field": "Channel"},
                                   {"channel": "y", "field": "Revenue"}]},
        }
        r = client.post("/api/v1/charts", json=body, headers=H)
        assert r.status_code == 201, r.text
        svg = client.get(f"/api/v1/charts/{r.json()['id']}/render").text
        assert "<svg" in svg and "fill-opacity" in svg
        return svg

    assert ">Total</text>" in pivot("sum")
    assert ">Total</text>" not in pivot("avg")  # an average of averages would be wrong
