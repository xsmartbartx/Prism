"""End-to-end integration test for Phase 0 pipeline."""
from __future__ import annotations

import csv
import io

from data.detection.csv import detect_structure
from data.detection.inference import TypeInferenceEngine
from data.query.spec import AggFunction, AggregationSpec, QuerySpec, SortDir, SortSpec
from data.query.compiler import QueryCompiler
from data.query.executor import QueryExecutor
from presentation.spec.view_spec import Encoding, EncodingChannel, MarkType, ViewSpec
from presentation.render.svg_renderer import SvgRenderer
from catalog import CatalogIndex, ArtifactType, ShareManager


class TestE2EPipeline:
    def test_csv_to_chart_to_share(self) -> None:
        # 1. CSV data with enough rows for header detection
        csv_content = "dept,name,salary\nEng,Alice,70000\nEng,Bob,60000\nMkt,Charlie,80000\nMkt,Diana,65000\nEng,Eve,55000\n"

        # 2. Detect structure
        dr = detect_structure(csv_content)
        # Use parsed column names if detected, otherwise fall back to CSV header
        if dr.header_row_index >= 0:
            cols = dr.column_names
        else:
            # Parse header directly from CSV
            reader = csv.reader(io.StringIO(csv_content))
            cols = next(reader)

        assert len(cols) == 3
        assert "dept" in cols[0].lower() or cols[0] == "dept"
        assert "salary" in cols[2].lower() or cols[2] == "salary"

        # 3. Parse data
        rows = list(csv.DictReader(io.StringIO(csv_content)))

        # 4. Type inference
        col_data = {n: [] for n in cols}
        for r in rows:
            for n in cols:
                col_data[n].append(r.get(n, ""))
        engine = TypeInferenceEngine()
        ir = engine.infer_dataset(col_data)
        assert not ir.overall_ambiguous

        # 5. Catalog
        cat = CatalogIndex()
        cat.register("Salaries", ArtifactType.DATASET, columns=cols)
        assert cat.count() == 1

        # 6. Query: sum salary by dept
        qc = QueryCompiler(dataset_columns=set(cols))
        q = QuerySpec(dimensions=[cols[0]],
                      measures=[AggregationSpec(column=cols[2], function=AggFunction.SUM)])
        cr = qc.compile(q)
        assert cr.success
        qr = QueryExecutor().execute(cr.plan, rows)
        assert qr.row_count == 2

        # 7. Render
        vs = ViewSpec(mark=MarkType.BAR, encodings=[
            Encoding(channel=EncodingChannel.X, field=cols[0]),
            Encoding(channel=EncodingChannel.Y, field=cols[2]),
        ])
        svg = SvgRenderer().render(vs, list(qr.rows))
        assert "<svg" in svg

        # 8. Share
        chart = cat.register("Salary Chart", ArtifactType.CHART)
        sm = ShareManager()
        token = sm.create_share(chart.id, ArtifactType.CHART, expires_in_hours=24)
        assert sm.validate_token(token.token_id, signature=token.signature) is not None

        # 9. Verify
        assert cat.count() == 2
        assert len(cat.search("salary")) >= 1