"""Chart recommendation rules."""

from __future__ import annotations

import pytest

from data.query import QueryCompiler
from presentation.recommend import FieldInfo, recommend
from presentation.spec.view_spec import MarkType, Orientation, validate_view

F = {
    "region": FieldInfo("region", "string", "dimension", distinct=4),
    "product": FieldInfo("product", "string", "dimension", distinct=40),
    "day": FieldInfo("day", "date", "time", date_span_days=400),
    "revenue": FieldInfo("revenue", "float", "measure"),
    "units": FieldInfo("units", "integer", "measure"),
    "order_id": FieldInfo("order_id", "string", "identifier", distinct=1000),
}
TYPES = {f.name: f.type for f in F.values()}


@pytest.mark.parametrize(
    ("names", "mark"),
    [
        (["revenue"], MarkType.KPI),
        (["region", "revenue"], MarkType.BAR),
        (["day", "revenue"], MarkType.LINE),
        (["day", "region", "revenue"], MarkType.LINE),
        (["product", "region", "revenue"], MarkType.BAR),
        (["region"], MarkType.BAR),
        (["day"], MarkType.LINE),
        (["order_id"], MarkType.TABLE),
        (["order_id", "revenue", "units"], MarkType.SCATTER),
    ],
)
def test_recommendation_compiles_and_validates(names: list[str], mark: MarkType) -> None:
    rec = recommend([F[n] for n in names])
    assert rec.view.mark == mark, rec.reason
    compiled = QueryCompiler(column_types=TYPES).compile(rec.query)
    assert compiled.success, compiled.errors
    assert compiled.plan is not None
    assert validate_view(rec.view, list(compiled.plan.select_columns)) == []


def test_many_categories_go_horizontal() -> None:
    rec = recommend([F["product"], F["revenue"]])
    assert rec.view.orientation == Orientation.HORIZONTAL


def test_time_grain_from_span() -> None:
    rec = recommend([F["day"], F["revenue"]])
    assert rec.query.time_grain["day"].value == "month"
    assert rec.view.time_grain == "month"


def test_requires_fields() -> None:
    with pytest.raises(ValueError):
        recommend([])
