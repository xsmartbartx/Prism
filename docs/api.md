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
DATASET_ID=…   # from GET /api/v1/datasets
curl -H "Authorization: Bearer $KEY" -F file=@sales-2026-11.xlsx \
     "$PRISM/api/v1/datasets/$DATASET_ID/refresh"
```

A 422 `DriftDetected` response means the file no longer matches the dataset's columns; nothing was loaded.

## Import and refresh from a link

```bash
# Start an import from a link (then review and commit it like an upload)
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"url": "https://example.com/exports/sales.csv"}' $PRISM/api/v1/imports/link

# Set or change a dataset's link and schedule: manual | hourly | daily | weekly
curl -X PUT -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"url": "https://example.com/exports/sales.csv", "schedule": "daily"}' \
     "$PRISM/api/v1/datasets/$DATASET_ID/link"

# Refresh now
curl -X POST -H "Authorization: Bearer $KEY" "$PRISM/api/v1/datasets/$DATASET_ID/link/refresh"
```

## Calculated fields

```bash
# Replace a dataset's calculated fields (each may use the ones before it)
curl -X PUT -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"calculations": [{"name": "Profit", "expression": "[Revenue] - [Cost]"}]}' \
     "$PRISM/api/v1/datasets/$DATASET_ID/calculations"

# Check a formula and see its first results
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"expression": "ROUND([Profit] / [Revenue] * 100, 1)", "calculations": [{"name": "Profit", "expression": "[Revenue] - [Cost]"}]}' \
     "$PRISM/api/v1/datasets/$DATASET_ID/calculations/preview"
```

`GET /api/v1/datasets/{id}` lists them under `calculations` (`name`, `expression`, `type`, `aggregate`); queries, charts and dashboard filters refer to row fields by name like columns. An aggregate field (its formula uses `SUM`, `COUNT`, …) is a measure: use it as `{"column": "<field>", "function": "value"}`; it cannot be a dimension or a filter. Its preview returns its value over the whole dataset. An invalid formula answers 400 with the reason; removing a field a chart uses answers 409.

## Import from a PostgreSQL database

```bash
# Tables and views the account can read
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"host": "db.example.com", "port": 5432, "database": "shop", "user": "reader", "password": "…", "sslmode": "require"}' \
     $PRISM/api/v1/imports/database/tables

# Read one into an import (then review and commit it); "sslmode": require | verify-full | disable
curl -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"host": "db.example.com", "database": "shop", "user": "reader", "password": "…", "table": "sales.orders"}' \
     $PRISM/api/v1/imports/database
```

The committed dataset's link (`GET …/link`) has `kind: "database"` and a password-free `url`; `PUT …/link` with that same `url` changes only its schedule. Refreshes use the same `…/link/refresh` endpoint.

`POST …/link/refresh` always answers 200 with `outcome.status`: `loaded` (a new version, with `version`, `rows`, `quarantined`), `unchanged`, `drift` or `failed` (with `error`). `GET …/link` returns `{link, can_schedule}` and `DELETE …/link` stops following the link. Scheduling needs the Pro or Business plan (402 otherwise).

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

A KPI over time is a `kpi` chart with an `x` encoding on a date field and one `y` value; its query groups by that field only, with a `time_grain`, and fetches enough periods for the trend and the comparison (sorted newest first, with a `limit`). View options: `"compare": "previous" | "year"`, `"higher_is_better"` (default `true`), `"sparkline"` (default `true`) and `"complete_periods"` (default `true`: the period containing today is left out).

```json
{"query": {"dimensions": ["Order Date"], "time_grain": {"Order Date": "month"}, "measures": [{"column": "Revenue", "function": "sum"}],
           "sort": [{"column": "Order Date", "direction": "desc"}], "limit": 25},
 "view": {"mark": "kpi", "compare": "year", "encodings": [{"channel": "x", "field": "Order Date"}, {"channel": "y", "field": "Revenue"}]}}
```

A pivot table is a chart with `"mark": "pivot"`: the `x` encoding is the rows, an optional `color` encoding the columns and one `y` encoding the value; the query groups by both fields with that one measure. `"totals"` (default `true`) adds row, column and grand totals when the measure's function allows them (`sum`, `count`, `min`, `max`; never for `avg`, `median`, `count_distinct` or aggregate fields), and `"heatmap": true` shades cells by value. The query must group by those two fields only, so each cell is one row; other groupings, or ungrouped `columns`, answer 400. Give the query a `limit` that covers every cell (the builder uses 5000).

```json
{"query": {"dimensions": ["Region", "Channel"], "measures": [{"column": "Revenue", "function": "sum"}], "limit": 5000},
 "view": {"mark": "pivot", "heatmap": true, "encodings": [{"channel": "x", "field": "Region"},
          {"channel": "color", "field": "Channel"}, {"channel": "y", "field": "Revenue"}]}}
```

## Other endpoints

| Area | Endpoints |
|---|---|
| Datasets | `GET/PATCH/DELETE /api/v1/datasets/{id}`, `GET …/rows`, `GET …/quarantine`, `GET …/export?format=csv\|xlsx` |
| Charts | `GET/POST /api/v1/charts`, `PUT/DELETE /api/v1/charts/{id}`, `GET …/data`, `GET …/export?format=svg\|csv\|xlsx`, `POST /api/v1/charts/preview` |
| Dashboards | `GET/POST /api/v1/dashboards`, `GET/PUT/DELETE /api/v1/dashboards/{id}` (body: `name`, `description`, `layout`, optional `filters: [{field, kind: values\|date_range, label}]`) |
| Dashboard filters | `POST /api/v1/dashboards/filter-fields` (`{chart_ids}` → fields a filter can use), `GET /api/v1/dashboards/{id}/filters/{index}/options` (values or date span), `GET /api/v1/dashboards/{id}/charts/{chart_id}/render?fv0=EU&ff1=2026-01-01&ft1=2026-03-31` (`{svg, applied, skipped}`); a click selection adds `xf=<field>&xv=<value>…[&xg=<grain>]&xc=<clicked chart id>`, applied to every tile but the clicked one. Clickable marks carry `class="pick" data-pick="<raw value>"`, and their `<svg>` carries `data-pick-field` (and `data-pick-grain`) |
| Dashboard export | `GET /api/v1/dashboards/{id}/export?format=xlsx` with the same filter parameters as tiles (`fv0=…`, `ff1=…`, `xf=…`): a workbook with an *About* sheet and a sheet per chart (explorers and above) |
| Shares | `POST /api/v1/shares`, `GET /api/v1/shares?artifact_id=`, `DELETE /api/v1/shares/{id}` |
| Audit | `GET /api/v1/audit`, `GET /api/v1/audit/verify` |
| Health | `GET /healthz`, `GET /readyz`, `GET /api/v1/version` |
