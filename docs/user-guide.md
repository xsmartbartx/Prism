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

### Import from a PostgreSQL database

On **Datasets**, click **Connect a PostgreSQL database**, enter the server's host, port, database, user and password, and click **Show tables**. Prism lists the tables and views that account can read; pick one and click **Import table** to open the usual **Review import**. The dataset remembers the database, so it can be refreshed from it later, by hand or on a schedule (see *Refresh from a link or database* below).

- Use an account that can only read the data you want to report on. Prism reads in a read-only session in any case, never runs SQL you type, and reads one whole table or view at a time: for a subset or a join, ask your database administrator for a view.
- **Connection**: *Encrypted (require)* encrypts the connection; *verify-full* also checks the server's certificate against public authorities (managed databases such as Neon or Supabase); *Not encrypted* is for databases on your own private network.
- The password is stored encrypted on the Prism server and used only to refresh. Removing the dataset's source, or the dataset, deletes it.
- Up to one million rows per table. Binary columns are skipped, and JSON values are imported as text.
- Databases on private network addresses (an office server, say) are only reachable if your administrator has allowed private networks (see [Security](security.md#links)).

### Quarantine

Rows that don't match the column contract are not loaded and not "fixed". They appear on the dataset's **Quarantine** tab with the source row number and the reason. If more rows fail than the tolerance allows, the import stops with an explanation — a mostly broken file never becomes a mostly empty dataset.

## Refresh a dataset

Open the dataset → **Load new file**. The file is checked against the dataset's contract:

- Columns are matched by header name, so reordering columns or adding a title row is fine.
- A missing column stops the load (**drift**) — fix the file or create a new dataset.
- Every successful load becomes a new **version**; charts always show the latest version and record which version produced their numbers.

### Refresh from a link or database

A dataset imported from a link shows a **Source link** panel on its **Overview** (a **Source database** panel for a database table; everything below applies to both). To give an existing dataset a link, open **Load new file** and paste it under **Or load it from a link**.

- **Refresh now** downloads the link or reads the table again. If nothing has changed since the last version (the server says so, the bytes are identical, or the table holds the same rows in any order), nothing is loaded and the panel says **No changes**. A changed file is checked like any other refresh and becomes a new version.
- **Refresh** chooses a schedule: only when you click, every hour, every day or every week (scheduled refresh needs the Pro or Business plan). Scheduled refreshes run with the access of the person who chose the schedule; if they leave the workspace or are no longer an author, the schedule pauses until another author sets it again.
- If a refresh fails — the link is down, or the file's columns changed (drift) — the panel shows why, and the current version stays as it was. After five failures in a row a schedule pauses itself, so a broken link does not fail forever unnoticed.
- **Change** points the dataset at another link; the bin icon removes the link or database (the dataset and its versions stay). To read another table, import it as a new dataset.

Only authors, stewards and admins see a dataset's link, because a link can contain an access token.

## Calculated fields

On a dataset's **Overview**, **Calculated fields → Add field** creates a column computed from the others, for example a profit, a margin, a size band or the order year. Give it a name and a formula; Prism checks the formula as you type and shows the result for the first rows. Charts, dashboard filters and click-to-filter then use it like any column, and every new version of the dataset recalculates it.

Write column names in brackets and text in single quotes:

| Formula | Gives |
|---|---|
| `[Revenue] - [Cost]` | a number |
| `ROUND(([Revenue] - [Cost]) / [Revenue] * 100, 1)` | a percentage with one decimal |
| `IF([Units] >= 10, 'Bulk', 'Single')` | text |
| `YEAR([Order Date])`, `[Order Date] + 30`, `DAYS_BETWEEN([Ordered], [Shipped])` | a year, a date, a number of days |
| `[Order Date] >= '2026-01-01' AND [Region] <> 'EU'` | true/false |
| `UPPER([Region]) & ' – ' & [Channel]` | text joined together |

Functions: `SUM`, `AVG`, `MIN`, `MAX`, `MEDIAN`, `COUNT`, `COUNTD` (see *Aggregate fields* below), `ROUND`, `ABS`, `FLOOR`, `CEIL`, `IF`, `COALESCE`, `ISEMPTY`, `YEAR`, `QUARTER`, `MONTH`, `DAY`, `WEEKDAY`, `DAYS_BETWEEN`, `UPPER`, `LOWER`, `TRIM`, `LEN`, `LEFT`, `RIGHT`, `CONTAINS`, `CONCAT`; operators `+ - * / %`, `&` (join text), `= <> < <= > >=`, `AND`, `OR`, `NOT`. Dividing by zero gives an empty value rather than an error. A field may use the fields listed above it.

A field that a chart uses cannot be removed or renamed until the chart stops using it. Only authors and above can add or change fields.

### Aggregate fields (measures)

A formula that uses `SUM`, `AVG`, `MIN`, `MAX`, `MEDIAN`, `COUNT` or `COUNTD` (count distinct) is an **aggregate field**: charts calculate it for each group they show, rather than row by row. This is how to get ratios right. A margin per region is `(SUM([Revenue]) - SUM([Cost])) / SUM([Revenue])`; averaging a per-row margin would weigh a 1 € order the same as a 10,000 € one.

| Formula | Gives, for each group |
|---|---|
| `(SUM([Revenue]) - SUM([Cost])) / SUM([Revenue]) * 100` | the true margin % |
| `SUM([Revenue]) / COUNT()` | revenue per row (order) |
| `COUNTD([Customer])` | the number of different customers |
| `SUM([Revenue]) / SUM([Units])` | the average price per unit |

Every column in an aggregate field must be inside an aggregate, and aggregates do not go inside each other. An aggregate field can use row fields and earlier aggregate fields. The preview shows its value over the whole dataset. In the chart builder they appear under **Aggregate fields** in **Values**, with the function shown as *formula*; they cannot be axes, colours or filters.

## Build a chart

From a dataset click **New chart** (or **Charts → New chart**).

- **Chart type** — bar, line, area, donut, scatter, KPI, table or pivot.
- **Suggest best chart** — picks a sensible chart for the fields you've chosen.
- **X axis / Slices** — what to compare. Date columns get a **time bucket** (day, week, month, quarter, year).
- **Values** — aggregation (sum, average, count, distinct count, min, max, median) of a column, or *Row count*.
- **Split by** — one series per value of a second column (e.g. per region).
- **Filters** — equals, ranges, *is one of*, *contains*, *is empty*…
- **Sort & limit**, **Display** (title, number format incl. currency, horizontal or stacked bars, value labels).

The preview is rendered live by the server exactly as it will appear in exports and share pages. **Show data** reveals the numbers behind the chart. **Save** stores the chart; **SVG** and **Data** export it.

### Pivot tables

A pivot lays one value out as a grid: pick a field for **Rows**, optionally one for **Columns**, and a **Value** (for example *sum of Revenue* by *Region* × *Channel*). Empty combinations show *–*.

- **Totals** adds a total for each row and column and a grand total, when they add up correctly: for sums and counts they are sums, for minimums and maximums the smallest or largest value. Averages, medians and distinct counts get no totals, because a total of those would be wrong.
- **Heat map** shades each cell by its value, darkest for the largest.
- Up to 200 rows and 20 columns are shown; a note says when there are more (filter, or swap rows and columns). Totals still include every row and column.
- On a dashboard, clicking a row filters the other charts to it.

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
- The selection is in the page address too, so a copied link reproduces it. KPI cards, tables and scatter plots are not clickable, nor is a donut's *Other* slice; on a pivot table, click a row.
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

### Export a dashboard

On a dashboard, with the filters and click selections you want:

- **Print** opens a print view: the dashboard's name, the filters in words, the time it was generated, and every chart in light colours laid out for paper. The print dialog opens when the charts are ready; choose *Save as PDF* to send it as a monthly report. Add `?preview` to the print view's address to look at it without the dialog.
- **Excel** downloads one workbook with a sheet per chart (its data as the chart shows it, filters applied) and an *About* sheet listing the dashboard, the time, who exported it, the filters, and any chart the filters could not apply to. Text that a spreadsheet could run as a formula is neutralised, as in every Prism export. Exports are recorded in the audit log.


## Keyboard & accessibility

All controls are reachable by keyboard; dialogs close with <kbd>Esc</kbd>. Charts include a text title and description for screen readers, every mark has a tooltip with its exact value, and colours come from a colour-blind-safe palette.
