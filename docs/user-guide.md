# User guide

## Import a spreadsheet

1. Go to **Datasets** and drop an `.xlsx`, `.xlsm`, `.csv` or `.tsv` file (or click to browse).
2. Prism analyses the file and opens **Review import**:
   - **Sheet** — pick another worksheet (hidden sheets are marked).
   - **Header row** — Prism skips title and note rows above the table; correct it if needed.
   - **Number & date format** — e.g. German `1.234,56` and `31.12.2026` vs US `1,234.56` and `12/31/2026`.
   - **Columns** — rename, change type (text, integer, decimal, date, true/false), set the role (dimension, measure, time, identifier, geography), or untick to skip.
3. Columns highlighted in amber need a decision: some values don't fit the proposed type. The *Evidence* column shows which.
4. Choose a **quarantine tolerance** and click **Publish dataset**.

Values such as `n/a`, `-`, `NULL` or `#N/A` become empty cells in number and date columns. Codes with leading zeros (ZIP codes, account numbers) stay text so they are not altered.

### Quarantine

Rows that don't match the column contract are not loaded and not "fixed". They appear on the dataset's **Quarantine** tab with the source row number and the reason. If more rows fail than the tolerance allows, the import stops with an explanation — a mostly broken file never becomes a mostly empty dataset.

## Refresh a dataset

Open the dataset → **Load new file**. The file is checked against the dataset's contract:

- Columns are matched by header name, so reordering columns or adding a title row is fine.
- A missing column stops the load (**drift**) — fix the file or create a new dataset.
- Every successful load becomes a new **version**; charts always show the latest version and record which version produced their numbers.

## Build a chart

From a dataset click **New chart** (or **Charts → New chart**).

- **Chart type** — bar, line, area, donut, scatter, KPI or table.
- **Suggest best chart** — picks a sensible chart for the fields you've chosen.
- **X axis / Slices** — what to compare. Date columns get a **time bucket** (day, week, month, quarter, year).
- **Values** — aggregation (sum, average, count, distinct count, min, max, median) of a column, or *Row count*.
- **Split by** — one series per value of a second column (e.g. per region).
- **Filters** — equals, ranges, *is one of*, *contains*, *is empty*…
- **Sort & limit**, **Display** (title, number format incl. currency, horizontal or stacked bars, value labels).

The preview is rendered live by the server exactly as it will appear in exports and share pages. **Show data** reveals the numbers behind the chart. **Save** stores the chart; **SVG** and **Data** export it.

## Dashboards

**Dashboards → New dashboard**, then **Add chart**. In edit mode choose each tile's width and reorder tiles. **Save** when done.

## Share

**Share** on a chart or dashboard creates a public, read-only link:

- Optional expiry (1 day to 1 year), optional **embedding** via `<iframe>` (Pro/Business).
- The link is shown once — copy it. Every view is counted.
- **Revoke** any time; revoked or expired links show "Link unavailable".
- Deleting a chart, dashboard or dataset revokes its links automatically.

Viewers of a link see the chart as displayed — not the underlying dataset.

## Export

- Dataset: **Excel** or **CSV** (up to the instance row limit).
- Chart: **SVG** image or the chart's data as Excel.

Exports neutralise spreadsheet formulas in text cells (cells beginning with `=`, `+`, `-`, `@` are prefixed with `'`) so a malicious value can't execute when opened.

## Keyboard & accessibility

All controls are reachable by keyboard; dialogs close with <kbd>Esc</kbd>. Charts include a text title and description for screen readers, every mark has a tooltip with its exact value, and colours come from a colour-blind-safe palette.
