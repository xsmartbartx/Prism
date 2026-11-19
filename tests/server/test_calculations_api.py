"""Calculated fields through the API: define, preview, chart, filter, protect."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.server.test_api import H, client, import_sales, setup_admin

__all__ = ["client"]

FIELDS = [
    {"name": "Big order", "expression": "IF([Revenue] >= 1000, 'Big', 'Small')"},
    {"name": "Revenue k", "expression": "ROUND([Revenue] / 1000, 2)"},
    {"name": "Order year", "expression": "YEAR([Order Date])"},
]


def _put(c: TestClient, ds: str, fields: list[dict[str, str]]) -> Any:
    return c.put(f"/api/v1/datasets/{ds}/calculations", json={"calculations": fields}, headers=H)


def _setup(c: TestClient) -> str:
    setup_admin(c)
    ds = import_sales(c)["id"]
    r = _put(c, ds, FIELDS)
    assert r.status_code == 200, r.text
    return str(ds)


def test_define_and_list(client: TestClient) -> None:
    ds = _setup(client)
    got = client.get(f"/api/v1/datasets/{ds}").json()["calculations"]
    assert [(f["name"], f["type"]) for f in got] == [
        ("Big order", "string"), ("Revenue k", "float"), ("Order year", "integer"),
    ]
    rows = client.get(f"/api/v1/datasets/{ds}/rows?limit=3").json()
    assert {"Big order", "Revenue k", "Order year"} <= set(rows["columns"])

    for fields, message in (
        ([{"name": "Bad", "expression": "[Region] + 1"}], "Bad: '+' needs a number, not text"),
        ([{"name": "Region", "expression": "1"}], "already a column"),
        ([{"name": "X", "expression": "DROP()"}], "Unknown function DROP"),
    ):
        r = _put(client, ds, fields)
        assert r.status_code == 400 and message in r.json()["error"]["message"], r.text
    # Nothing was saved by the failed attempts.
    assert len(client.get(f"/api/v1/datasets/{ds}").json()["calculations"]) == 3


def test_preview(client: TestClient) -> None:
    ds = _setup(client)
    r = client.post(f"/api/v1/datasets/{ds}/calculations/preview", headers=H, json={
        "expression": "[Revenue k] * 2",
        "calculations": FIELDS,
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["type"] == "float" and out["columns"] == ["Revenue k"]
    first = out["rows"][0]
    assert first["value"] == first["inputs"]["Revenue k"] * 2
    bad = client.post(f"/api/v1/datasets/{ds}/calculations/preview", headers=H,
                      json={"expression": "[Nope] * 2"})
    assert bad.status_code == 400 and "no column [Nope]" in bad.text


def test_charts_and_dashboard_filters_use_fields(client: TestClient) -> None:
    ds = _setup(client)
    chart = {
        "dataset_id": ds,
        "name": "By size",
        "query": {"dimensions": ["Big order"],
                  "measures": [{"column": "Revenue k", "function": "sum"}]},
        "view": {"mark": "bar", "encodings": [{"channel": "x", "field": "Big order"},
                                               {"channel": "y", "field": "Revenue k"}]},
    }
    r = client.post("/api/v1/charts", json=chart, headers=H)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    data = client.get(f"/api/v1/charts/{cid}/data").json()
    assert {row["Big order"] for row in data["rows"]} <= {"Big", "Small"}

    dash = client.post("/api/v1/dashboards", headers=H, json={
        "name": "D", "layout": [{"chart_id": cid}],
        "filters": [{"field": "Big order", "kind": "values"}],
    })
    assert dash.status_code == 201, dash.text
    did = dash.json()["id"]
    opts = client.get(f"/api/v1/dashboards/{did}/filters/0/options").json()
    assert set(opts["values"]) <= {"Big", "Small"} and opts["values"]
    tile = client.get(f"/api/v1/dashboards/{did}/charts/{cid}/render?fv0=Big").json()
    assert tile["applied"] == ["Big order"] and "Small" not in tile["svg"]

    # A field a chart uses cannot be removed or renamed out from under it.
    r = _put(client, ds, FIELDS[1:])
    assert r.status_code == 409 and "By size" in r.text, r.text
    r = _put(client, ds, [*FIELDS, {"name": "Extra", "expression": "[Big order] = 'Big'"}])
    assert r.status_code == 200


def test_viewers_cannot_edit(client: TestClient) -> None:
    ds = _setup(client)
    anon = TestClient(client.app)
    assert anon.put(f"/api/v1/datasets/{ds}/calculations", json={"calculations": []},
                    headers=H).status_code == 401
