# REST API

Interactive reference (OpenAPI): `https://<your-instance>/api/docs`. Machine-readable schema: `/api/openapi.json`.

## Authentication

Create a key in **API keys** (Pro/Business) and send it as a bearer token:

```bash
export PRISM=https://analytics.example.com
export KEY=prism_xxxxxxxx_...
curl -H "Authorization: Bearer $KEY" $PRISM/api/v1/datasets
```

Keys are scoped to the workspace they were created in and carry the creating user's role. Browser sessions use an HttpOnly cookie; cookie-authenticated write requests must send `X-Prism-CSRF: 1` (bearer requests don't need it).

Errors are JSON: `{"error": {"code": "NotFound", "message": "Dataset not found"}}` with HTTP status 400, 401, 402 (plan limit), 403, 404, 409, 422 (validation or drift), 429 or 504 (query timeout).

## Upload and publish a file

```bash
# 1. Upload: returns an import with a proposal (detected header, types, roles)
curl -H "Authorization: Bearer $KEY" -F file=@sales.xlsx $PRISM/api/v1/imports > import.json

# 2. Commit the proposal (edit types/names first if needed)
python3 - <<'PY' > commit.json
import json
p = json.load(open("import.json"))["proposal"]
print(json.dumps({
  "dataset_name": "Sales",
  "header_row": p["header_row"], "data_start_row": p["data_start_row"], "locale": p["locale"],
  "sheet": p["sheet"],
  "columns": [{k: c[k] for k in ("index", "source_name", "name", "type", "role", "locale")} for c in p["columns"]],
}))
PY
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d @commit.json $PRISM/api/v1/imports/$(jq -r .id import.json)/commit
```

## Refresh a dataset (e.g. nightly)

```bash
curl -H "Authorization: Bearer $KEY" -F file=@sales-2026-11.xlsx \
     $PRISM/api/v1/datasets/<dataset_id>/refresh
```

A 422 `DriftDetected` response means the file no longer matches the dataset's columns; nothing was loaded.

## Query

Every question is a declarative query spec — there is no raw SQL surface.

```bash
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  $PRISM/api/v1/datasets/<dataset_id>/query -d '{
    "dimensions": ["Order Date", "Region"],
    "time_grain": {"Order Date": "month"},
    "measures": [{"column": "Revenue", "function": "sum", "alias": "revenue"},
                 {"column": "*", "function": "count"}],
    "filters": [{"column": "Order Date", "operator": "gte", "value": "2026-01-01"},
                {"column": "Region", "operator": "in", "value": ["Europe", "APAC"]}],
    "sort": [{"column": "Order Date", "direction": "asc"}],
    "limit": 1000
  }'
```

| Field | Values |
|---|---|
| `function` | `sum`, `avg`, `count`, `count_distinct`, `min`, `max`, `median` (`count` of `"*"` counts rows) |
| `operator` | `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `between`, `contains`, `starts_with`, `is_null`, `not_null` |
| `time_grain` | `day`, `week`, `month`, `quarter`, `year` (date dimensions only) |
| `columns` | raw row projection when there are no dimensions/measures |

The response includes `rows`, `total` (before limit), `plan_hash` and `dataset_version` for lineage.

## Charts

```bash
# Render a saved chart as SVG
curl -H "Authorization: Bearer $KEY" "$PRISM/api/v1/charts/<chart_id>/render?theme=dark&width=1200" > chart.svg

# Ask for a recommendation
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"fields": ["Order Date", "Revenue"]}' $PRISM/api/v1/datasets/<dataset_id>/recommend
```

## Other endpoints

| Area | Endpoints |
|---|---|
| Datasets | `GET/PATCH/DELETE /api/v1/datasets/{id}`, `GET …/rows`, `GET …/quarantine`, `GET …/export?format=csv\|xlsx` |
| Charts | `GET/POST /api/v1/charts`, `PUT/DELETE /api/v1/charts/{id}`, `GET …/data`, `GET …/export?format=svg\|csv\|xlsx`, `POST /api/v1/charts/preview` |
| Dashboards | `GET/POST /api/v1/dashboards`, `GET/PUT/DELETE /api/v1/dashboards/{id}` |
| Shares | `POST /api/v1/shares`, `GET /api/v1/shares?artifact_id=`, `DELETE /api/v1/shares/{id}` |
| Audit | `GET /api/v1/audit`, `GET /api/v1/audit/verify` |
| Health | `GET /healthz`, `GET /readyz`, `GET /api/v1/version` |
