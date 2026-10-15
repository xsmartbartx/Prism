"""End-to-end integration test for Phase 0 pipeline."""
from __future__ import annotations

import csv
import io

from core.types.column import ColumnContract
from core.types.base import DataRole
from data.detection.csv import CsvDetector
from data.detection.inference import TypeInferenceEngine
from data.query.spec import AggFunction, AggregationSpec, QuerySpec, SortDir, SortSpec
from data.query.compiler import QueryCompiler
from data.query.executor import QueryExecutor
from presentation.spec.view_spec import Encoding, EncodingChannel, MarkType, ViewSpec
from presentation.render.svg_renderer import SvgRenderer
from catalog import CatalogIndex, ArtifactType, ShareManager


def _csv(data: list[list[str]]) -> io.StringIO:
    buf = io.StringIO()
    csv.writer(buf).writerows(data)
    buf.seek(0)
    return buf


class TestE2EPipeline:
    def test_csv_to_chart_to_share(self) -> None:
        # 1. Create CSV
        csv_file = _csv([
            ["dept", "name", "salary"],
            ["Eng", "Alice", "70000"],
            ["Eng", "Bob", "60000"],
            ["Mkt", "Charlie", "80000"],
        ])

        # 2. Detect structure
        det = CsvDetector()
        detect_r = det.detect(csv_file)
        assert detect_r.column_names == ["dept", "name", "salary"]

        # 3. Extract data for inference
        csv_file.seek(0)
        rows = list(csv.DictReader(csv_file))
        col_data: dict[str, list[str]] = {n: [] for n in detect_r.column_names}
        for r in rows:
            for n in detect_r.column_names:
                col_data[n].append(r.get(n, ""))

        # 4. Type inference
        engine = TypeInferenceEngine()
        infer_r = engine.infer_dataset(col_data)
        assert not infer_r.overall_ambiguous
        types = {}
        for c in infer_r.columns:
            b = c.best_candidate()
            assert b is not None
            types[c.column_name] = b.type_name
        assert types["dept"] == "string"
        assert types["salary"] == "integer"

        # 5. Register in catalog
        cat = CatalogIndex()
        cat.register("Salaries", ArtifactType.DATASET,
                     columns=list(col_data.keys()), tags=["test"], owner="alice")
        assert cat.count() == 1

        # 6. Query
        qc = QueryCompiler(dataset_columns=set(col_data.keys()))
        q = QuerySpec(dimensions=["dept"],
                      measures=[AggregationSpec(column="salary", function=AggFunction.SUM)],
                      sort=[SortSpec(column="dept", direction=SortDir.ASC)])
        cr = qc.compile(q)
        assert cr.success
        qr = QueryExecutor().execute(cr.plan, rows)
        assert qr.row_count == 2
        by_dept = {r["dept"]: r["salary"] for r in qr.rows}
        assert by_dept["Eng"] == 130000
        assert by_dept["Mkt"] == 80000

        # 7. Render
        vs = ViewSpec(mark=MarkType.BAR, encodings=[
            Encoding(channel=EncodingChannel.X, field="dept"),
            Encoding(channel=EncodingChannel.Y, field="salary"),
        ])
        svg = SvgRenderer().render(vs, list(qr.rows))
        assert "<svg" in svg
        assert "Eng" in svg

        # 8. Register chart + share
        chart = cat.register("Salary Chart", ArtifactType.CHART, owner="alice")
        sm = ShareManager()
        token = sm.create_share(chart.id, ArtifactType.CHART,
                                created_by="alice", expires_in_hours=24)
        assert sm.validate_token(token.token_id, signature=token.signature) is not None
        assert sm.list_shares(chart.id)[0].token_id == token.token_id

        # 9. Verify catalog search
        results = cat.search("salary")
        assert len(results) >= 1