"""KPI comparisons through the API: saved, rendered with today's date, and checked."""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient

from tests.server.test_api import H, client, setup_admin

__all__ = ["client"]


def _kpi(ds: str, query: dict[str, Any], **view: Any) -> dict[str, Any]:
    return {
        "dataset_id": ds, "name": "Revenue trend",
        "query": query,
        "view": {"mark": "kpi", "encodings": [{"channel": "x", "field": "Order Date"},
                                              {"channel": "y", "field": "Revenue"}], **view},
    }


MONTHLY = {
    "dimensions": ["Order Date"], "time_grain": {"Order Date": "month"},
    "measures": [{"column": "Revenue", "function": "sum"}],
    "sort": [{"column": "Order Date", "direction": "desc"}], "limit": 25,
}


def test_kpi_with_a_comparison(client: TestClient) -> None:
    setup_admin(client)
    ds = client.post("/api/v1/datasets/sample", headers=H).json()["id"]
    r = client.post("/api/v1/charts", headers=H, json=_kpi(ds, MONTHLY, compare="year"))
    assert r.status_code == 201, r.text
    svg = client.get(f"/api/v1/charts/{r.json()['id']}/render").text
    texts = re.findall(r">([^<>]+)</text>", svg)
    assert texts[0].startswith("Revenue · ") and " vs " in texts[2], texts
    assert "<polyline" in svg

    # Without a time bucket, or grouped by something else too, there is no one row per period.
    bad = {**MONTHLY, "time_grain": {}}
    r = client.post("/api/v1/charts", headers=H, json=_kpi(ds, bad, compare="previous"))
    assert r.status_code == 400 and "Pick a time bucket" in r.text, r.text
    bad = {**MONTHLY, "dimensions": ["Order Date", "Region"]}
    r = client.post("/api/v1/charts", headers=H, json=_kpi(ds, bad))
    assert r.status_code == 400 and "groups by its date field" in r.text, r.text
    r = client.post("/api/v1/charts", headers=H, json={
        "dataset_id": ds, "name": "x", "query": {"measures": [{"column": "Revenue", "function": "sum"}]},
        "view": {"mark": "kpi", "compare": "previous", "encodings": [{"channel": "y", "field": "Revenue"}]},
    })
    assert r.status_code == 400 and "needs a date field" in r.text, r.text
