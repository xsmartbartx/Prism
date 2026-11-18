"""Dashboard filters through the API and on share pages."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.server.test_api import CHART, H, client, import_sales, setup_admin

__all__ = ["client"]

UNITS_CSV = b"Order Date,Units\n2026-01-05,3\n2026-02-10,5\n2026-04-20,8\n"
UNITS_CHART = {
    "query": {"dimensions": ["Order Date"], "measures": [{"column": "Units", "function": "sum"}]},
    "view": {"mark": "bar", "encodings": [{"channel": "x", "field": "Order Date"}, {"channel": "y", "field": "Units"}]},
}


def _import_units(c: TestClient) -> dict[str, Any]:
    imp = c.post("/api/v1/imports", files={"file": ("units.csv", UNITS_CSV, "text/csv")}, headers=H).json()
    p = imp["proposal"]
    body = {
        "dataset_name": "Units",
        "header_row": p["header_row"],
        "data_start_row": p["data_start_row"],
        "columns": [{k: col[k] for k in ("index", "source_name", "name", "type", "role")} for col in p["columns"]],
    }
    r = c.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def _setup(c: TestClient) -> tuple[str, str, dict[str, Any]]:
    setup_admin(c)
    sales, units = import_sales(c), _import_units(c)
    a = c.post("/api/v1/charts", json={"dataset_id": sales["id"], "name": "By region", **CHART}, headers=H).json()
    b = c.post("/api/v1/charts", json={"dataset_id": units["id"], "name": "Units", **UNITS_CHART}, headers=H).json()
    dash = c.post(
        "/api/v1/dashboards",
        json={
            "name": "Sales",
            "layout": [{"chart_id": a["id"]}, {"chart_id": b["id"]}],
            "filters": [
                {"field": "Region", "kind": "values"},
                {"field": "Order Date", "kind": "date_range", "label": "Ordered"},
            ],
        },
        headers=H,
    )
    assert dash.status_code == 201, dash.text
    return a["id"], b["id"], dash.json()


def _tile(c: TestClient, dash_id: str, chart_id: str, query: str = "") -> dict[str, Any]:
    r = c.get(f"/api/v1/dashboards/{dash_id}/charts/{chart_id}/render?theme=light{query}")
    assert r.status_code == 200, r.text
    return r.json()


def test_fields_options_and_filtered_tiles(client: TestClient) -> None:
    a, b, dash = _setup(client)
    assert dash["filters"] == [
        {"field": "Region", "kind": "values", "label": "Region"},
        {"field": "Order Date", "kind": "date_range", "label": "Ordered"},
    ]

    fields = client.post("/api/v1/dashboards/filter-fields", json={"chart_ids": [a, b]}, headers=H).json()
    assert fields[0] == {"field": "Order Date", "types": ["date"], "charts": 2, "kinds": ["values", "date_range"]}
    assert {"field": "Region", "types": ["string"], "charts": 1, "kinds": ["values"]} in fields
    assert all(f["field"] != "Revenue" for f in fields)  # decimals cannot be picked

    did = dash["id"]
    opts = client.get(f"/api/v1/dashboards/{did}/filters/0/options").json()
    assert opts["values"] == ["APAC", "EU", "US"] and opts["truncated"] is False
    span = client.get(f"/api/v1/dashboards/{did}/filters/1/options").json()
    assert (span["min"], span["max"]) == ("2026-01-03", "2026-04-20")  # across both datasets
    assert client.get(f"/api/v1/dashboards/{did}/filters/7/options").status_code == 404

    plain = _tile(client, did, a)
    assert "APAC" in plain["svg"] and plain["applied"] == [] and plain["skipped"] == []
    eu = _tile(client, did, a, "&fv0=EU")
    assert eu["applied"] == ["Region"] and "APAC" not in eu["svg"] and "EU" in eu["svg"]
    january = _tile(client, did, a, "&ft1=2026-01-31")
    assert january["applied"] == ["Ordered"] and "APAC" not in january["svg"] and "US" in january["svg"]

    units = _tile(client, did, b, "&fv0=EU&ff1=2026-02-01")
    assert units["applied"] == ["Ordered"] and units["skipped"] == ["Region"]

    sales_id = next(d["id"] for d in client.get("/api/v1/datasets").json() if d["name"] == "Sales")
    other = client.post("/api/v1/charts", json={"dataset_id": sales_id, "name": "x", **CHART}, headers=H).json()
    assert client.get(f"/api/v1/dashboards/{did}/charts/{other['id']}/render").status_code == 404


def test_definitions_are_validated_and_follow_the_layout(client: TestClient) -> None:
    a, b, dash = _setup(client)
    did = dash["id"]
    base = {"name": "Sales", "layout": [{"chart_id": a}, {"chart_id": b}]}
    for bad, msg in (
        ([{"field": "Nope"}], "No chart"),
        ([{"field": "Region", "kind": "date_range"}], "not a date"),
        ([{"field": "Revenue"}], "decimals"),
        ([{"field": "Region"}, {"field": "Region"}], "twice"),
    ):
        r = client.put(f"/api/v1/dashboards/{did}", json={**base, "filters": bad}, headers=H)
        assert r.status_code == 400 and msg in r.json()["error"]["message"], r.text

    # Saving without "filters" keeps them, minus fields no remaining tile has.
    r = client.put(f"/api/v1/dashboards/{did}", json={"name": "Sales", "layout": [{"chart_id": b}]}, headers=H)
    assert [f["field"] for f in r.json()["filters"]] == ["Order Date"]
    r = client.put(f"/api/v1/dashboards/{did}", json={**base, "filters": []}, headers=H)
    assert r.json()["filters"] == []


def test_share_page_filters_without_javascript(client: TestClient) -> None:
    _, _, dash = _setup(client)
    share = client.post("/api/v1/shares", json={"artifact_type": "dashboard", "artifact_id": dash["id"]}, headers=H).json()
    anon = TestClient(client.app)

    page = anon.get(f"/s/{share['token']}").text
    assert '<form class="filters" method="get">' in page and "<script" not in page
    assert 'name="fv0" value="APAC"' in page and 'name="ff1"' in page and 'min="2026-01-03"' in page
    assert page.count("APAC") >= 2  # in the picker and in the unfiltered chart

    page = anon.get(f"/s/{share['token']}?fv0=EU&theme=dark").text
    assert 'value="EU" checked' in page and "Region · 1 selected" in page
    assert 'name="theme" value="dark"' in page
    assert "Not filtered by Region" in page  # the Units tile has no Region
    chart_part = page.split("</form>", 1)[1]
    assert "APAC" not in chart_part.split("Not filtered by", 1)[0]

    # Junk parameters never break the page.
    assert anon.get(f"/s/{share['token']}?fv0=&ff1=soon&fv99=x").status_code == 200


def _csv_dataset(c: TestClient, name: str, raw: bytes) -> str:
    imp = c.post("/api/v1/imports", files={"file": (f"{name}.csv", raw, "text/csv")}, headers=H).json()
    p = imp["proposal"]
    body = {
        "dataset_name": name,
        "header_row": p["header_row"],
        "data_start_row": p["data_start_row"],
        "columns": [{k: col[k] for k in ("index", "source_name", "name", "type", "role")} for col in p["columns"]],
    }
    r = c.post(f"/api/v1/imports/{imp['id']}/commit", json=body, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bar(c: TestClient, ds: str, x: str, y: str, filters: list[dict[str, Any]] | None = None) -> str:
    body = {
        "dataset_id": ds,
        "name": f"{x} chart",
        "query": {"dimensions": [x], "measures": [{"column": y, "function": "count"}], "filters": filters or []},
        "view": {"mark": "bar", "encodings": [{"channel": "x", "field": x}, {"channel": "y", "field": y}]},
    }
    r = c.post("/api/v1/charts", json=body, headers=H)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _dash(c: TestClient, charts: list[str], filters: list[dict[str, str]]) -> str:
    r = c.post("/api/v1/dashboards", json={"name": "D", "layout": [{"chart_id": x} for x in charts], "filters": filters}, headers=H)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_options_respect_each_charts_own_filters(client: TestClient) -> None:
    setup_admin(client)
    sales = import_sales(client)["id"]
    eu_only = _bar(client, sales, "Region", "Order ID", [{"column": "Region", "operator": "in", "value": ["EU"]}])
    did = _dash(client, [eu_only], [{"field": "Order ID"}, {"field": "Region"}])
    ids = client.get(f"/api/v1/dashboards/{did}/filters/0/options").json()["values"]
    assert ids == ["A-1001", "A-1003", "A-1006"]  # never the US or APAC orders the chart excludes
    assert client.get(f"/api/v1/dashboards/{did}/filters/1/options").json()["values"] == ["EU"]
    # A second, unfiltered chart over the same dataset widens the options (union).
    every = _bar(client, sales, "Region", "Order ID")
    did2 = _dash(client, [eu_only, every], [{"field": "Region"}])
    assert client.get(f"/api/v1/dashboards/{did2}/filters/0/options").json()["values"] == ["APAC", "EU", "US"]


def test_options_edge_cases(client: TestClient) -> None:
    setup_admin(client)
    named_n = _csv_dataset(client, "N", b"n,k\nalpha,10\nbeta,20\ngamma,30\n")
    did = _dash(client, [_bar(client, named_n, "n", "k")], [{"field": "n"}])
    assert client.get(f"/api/v1/dashboards/{did}/filters/0/options").json()["values"] == ["alpha", "beta", "gamma"]

    bools = _csv_dataset(client, "B", b"flag,k\ntrue,1\nfalse,2\ntrue,3\n")
    ints = _csv_dataset(client, "I", b"flag,k\n1,1\n0,2\n2,3\n")
    did = _dash(client, [_bar(client, bools, "flag", "k"), _bar(client, ints, "flag", "k")], [{"field": "flag"}])
    assert sorted(client.get(f"/api/v1/dashboards/{did}/filters/0/options").json()["values"]) == ["0", "1", "2", "false", "true"]

    long_value = "L" * 250
    texts = _csv_dataset(client, "T", f"note,k\nshort,1\n{long_value},2\n".encode())
    did = _dash(client, [_bar(client, texts, "note", "k")], [{"field": "note"}])
    opts = client.get(f"/api/v1/dashboards/{did}/filters/0/options").json()
    assert opts["values"] == ["short"] and opts["omitted_long"] == 1


def test_layout_save_drops_filters_that_no_longer_fit(client: TestClient) -> None:
    setup_admin(client)
    sales = import_sales(client)["id"]
    text_dates = _csv_dataset(client, "Q", b"Order Date,k\nQ1,1\nQ2,2\n")
    a, t = _bar(client, sales, "Order Date", "Order ID"), _bar(client, text_dates, "Order Date", "k")
    did = _dash(client, [a, t], [{"field": "Order Date", "kind": "date_range"}])
    r = client.put(f"/api/v1/dashboards/{did}", json={"name": "D", "layout": [{"chart_id": t}]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["filters"] == []  # only a text "Order Date" is left, so the range goes


def test_share_form_keeps_saved_selections(client: TestClient) -> None:
    _, _, dash = _setup(client)
    share = client.post("/api/v1/shares", json={"artifact_type": "dashboard", "artifact_id": dash["id"]}, headers=H).json()
    page = TestClient(client.app).get(f"/s/{share['token']}?fv0=Mars&ff1=2025-12-01&ft1=2026-09-30").text
    assert 'value="Mars" checked' in page  # not an option any more, still submitted on Apply
    assert 'min="2025-12-01"' in page and 'max="2026-09-30"' in page  # the inputs stay valid
