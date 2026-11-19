# User guide

## Import a spreadsheet or database file

1. Go to **Datasets** and drop a file (or click to browse):
   - Excel workbooks: `.xlsx`, `.xlsm`
   - delimited text: `.csv`, `.tsv`, `.txt`
   - SQLite databases: `.sqlite`, `.sqlite3`, `.db`
   - Parquet files: `.parquet`
2. Prism analyses the file and opens **Review import**:
   - **Sheet** or **Table** — pick another worksheet (hidden sheets are marked) or, for a SQLite database, another table. Each import makes one dataset from one sheet or table; import the file again for another.
   - **Header row** — Prism skips title and note rows above the table; correct it if needed.
   - **Number & date format** — e.g. German `1.234,56` and `31.12.2026` vs US `1,234.56` and `12/31/2026`.
   - **Columns** — rename, change type (text, integer, decimal, date, true/false), set the role (dimension, measure, time, identifier, geography), or untick to skip.
3. Columns highlighted in amber need a decision: some values don't fit the proposed type. The *Evidence* column shows which.
4. Choose a **quarantine tolerance** and click **Publish dataset**.

Values such as `n/a`, `-`, `NULL` or `#N/A` become empty cells in number and date columns. Codes with leading zeros (ZIP codes, account numbers) stay text so they are not altered.

SQLite and Parquet columns already have types, but Prism still proposes and checks each column's type like any other file, so a refresh is validated the same way. From a SQLite database Prism offers ordinary tables only (views and virtual tables are not offered). Binary values (BLOBs) are not imported; the review lists the affected columns. In Parquet files, nested values (lists, structs, maps) are imported as JSON text and timestamps with a time zone are converted to UTC.

### Import from a link

Instead of a file, paste an `https://` link under the drop area on **Datasets** and click **Import from link**. Prism downloads the file and opens the same **Review import**; it works out from the content whether it is CSV, Excel, Parquet or SQLite. The dataset remembers the link, so it can be refreshed from it later (see below).

The link must lead straight to the file, and anyone with the link must be able to download it:

- **Google Sheets:** File → Share → **Publish to web**, choose the sheet and **Comma-separated values (.csv)**, and use the link it gives you.
- **OneDrive, Dropbox, GitHub and similar:** use their *download* or *raw* link, not the page that shows the file.
- An export URL from your own system (ERP, CRM, BI tool) works if it serves the file over HTTPS without a sign-in.

If the link returns a web page (usually a sign-in page) Prism says so instead of importing it. For security, links to private network addresses are refused unless your administrator has allowed them (see [Security](security.md#links)).

### Quarantine

Rows that don't match the column contract are not loaded and not "fixed". They appear on the dataset's **Quarantine** tab with the source row number and the reason. If more rows fail than the tolerance allows, the import stops with an explanation — a mostly broken file never becomes a mostly empty dataset.

## Refresh a dataset

Open the dataset → **Load new file**. The file is checked against the dataset's contract:

- Columns are matched by header name, so reordering columns or adding a title row is fine.
- A missing column stops the load (**drift**) — fix the file or create a new dataset.
- Every successful load becomes a new **version**; charts always show the latest version and record which version produced their numbers.

### Refresh from a link

A dataset imported from a link shows a **Source link** panel on its **Overview**. To give an existing dataset a link, open **Load new file** and paste it under **Or load it from a link**.

- **Refresh now** downloads the link. If the file has not changed since the last version (the server says so, or the bytes are identical), nothing is loaded and the panel says **No changes**. A changed file is checked like any other refresh and becomes a new version.
- **Refresh** chooses a schedule: only when you click, every hour, every day or every week (scheduled refresh needs the Pro or Business plan). Scheduled refreshes run with the access of the person who chose the schedule; if they leave the workspace or are no longer an author, the schedule pauses until another author sets it again.
- If a refresh fails — the link is down, or the file's columns changed (drift) — the panel shows why, and the current version stays as it was. After five failures in a row a schedule pauses itself, so a broken link does not fail forever unnoticed.
- **Change** points the dataset at another link; the bin icon removes the link (the dataset and its versions stay).

Only authors, stewards and admins see a dataset's link, because a link can contain an access token.

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

### Dashboard filters

In edit mode, **Filters → Add a filter** lets viewers narrow the whole dashboard at once (up to six filters):

- **Values**: viewers tick one or more values, such as regions or products. Works on text, whole-number, true/false and date fields.
- **Date range**: viewers pick a from and/or to date. Works on date fields.

A filter applies to every chart whose dataset has a field of that name. Matching ignores case and spacing, so `Region` and `region` match. A chart without the field stays unfiltered and says so (*Not filtered by Region*), so its numbers are never mistaken for the filtered slice. A filter only narrows what a chart already shows, on top of the chart's own filters.

The picked values are part of the page address, so copying the link shares the filtered view. Shared dashboard links (`/s/…`) show the same filters as a simple form; viewers can filter without signing in, and the page needs no JavaScript.

### Click to filter

Click a bar, a point on a line or a slice of a donut to filter the **other** charts on the dashboard to that value. No filter has to be set up first, and it works on any field. The chart you clicked keeps all its bars and highlights your choice; a chip above the charts (for example *Region: EU*) shows what is selected.

- Click the same mark again, press **Esc** or use the chip's **×** to clear it. Clicking another mark replaces the selection; hold **Shift** (or **Ctrl**/**⌘**) to add or remove values.
- On a time axis grouped by week, month, quarter or year, a click selects that whole period.
- Charts without the clicked field say *Not filtered by …*, as with dashboard filters. Click selections combine with the dashboard filters.
- The selection is in the page address too, so a copied link reproduces it. KPI cards, tables and scatter plots are not clickable, nor is a donut's *Other* slice.
- With a keyboard, **Tab** moves through the bars, points and slices (on charts with up to 60 of them) and **Enter** or **Space** selects one. Screen readers announce each one with its value.

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
