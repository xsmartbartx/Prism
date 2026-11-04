"""Column statistics computed for every dataset version."""

from __future__ import annotations

from datetime import date
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc


def _jsonable(v: Any) -> Any:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and (v != v):
        return None
    return v


def profile_table(table: pa.Table, *, top_n: int = 5) -> dict[str, Any]:
    """Return ``{"row_count", "columns": {name: stats}}`` for a typed table."""
    cols: dict[str, Any] = {}
    n = table.num_rows
    for name in table.column_names:
        arr = table.column(name)
        nulls = arr.null_count
        stats: dict[str, Any] = {
            "type": str(arr.type),
            "nulls": nulls,
            "null_ratio": round(nulls / n, 4) if n else 0.0,
        }
        valid = pc.drop_null(arr)
        if len(valid):
            stats["distinct"] = pc.count_distinct(valid).as_py()
            if pa.types.is_integer(arr.type) or pa.types.is_floating(arr.type):
                mm = pc.min_max(valid).as_py()
                stats.update(
                    min=_jsonable(mm["min"]),
                    max=_jsonable(mm["max"]),
                    mean=_jsonable(round(pc.mean(valid).as_py(), 6)),
                    sum=_jsonable(pc.sum(valid).as_py()),
                )
            elif pa.types.is_date(arr.type):
                mm = pc.min_max(valid).as_py()
                stats.update(min=_jsonable(mm["min"]), max=_jsonable(mm["max"]))
            elif pa.types.is_boolean(arr.type):
                stats["true"] = pc.sum(valid.cast(pa.int64())).as_py()
            if pa.types.is_string(arr.type) or pa.types.is_boolean(arr.type):
                vc = pc.value_counts(valid).to_pylist()
                vc.sort(key=lambda d: (-d["counts"], str(d["values"])))
                stats["top"] = [
                    {"value": _jsonable(d["values"]), "count": d["counts"]} for d in vc[:top_n]
                ]
        else:
            stats["distinct"] = 0
        cols[name] = stats
    return {"row_count": n, "columns": cols}
