"""Query service: QuerySpec → compiled plan → DuckDB over the current version.

Results are cached by (dataset version content hash, plan hash). Both are
content addresses, so a cache entry can never serve stale numbers: a new
dataset version has a new content hash.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from data.query import QueryCompiler, QuerySpec, ResultSet
from data.query.duck import DuckDBExecutor
from server.config import Settings
from server.db.models import Dataset, DatasetVersion
from server.errors import BadRequest, NotFound
from server.services.context import Actor


@dataclass(frozen=True)
class QueryOutcome:
    result: ResultSet
    version: DatasetVersion
    column_types: dict[str, str]
    cached: bool


class _LRU:
    def __init__(self, capacity: int = 256) -> None:
        self._data: OrderedDict[tuple[str, str], ResultSet] = OrderedDict()
        self._cap = capacity
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> ResultSet | None:
        with self._lock:
            val = self._data.get(key)
            if val is not None:
                self._data.move_to_end(key)
            return val

    def put(self, key: tuple[str, str], val: ResultSet) -> None:
        with self._lock:
            self._data[key] = val
            self._data.move_to_end(key)
            while len(self._data) > self._cap:
                self._data.popitem(last=False)


def version_types(version: DatasetVersion) -> dict[str, str]:
    return {c["name"]: c["type"] for c in version.columns}


class QueryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.executor = DuckDBExecutor(timeout_s=settings.query_timeout_s)
        self.cache = _LRU()

    def current_version(
        self, s: Session, dataset: Dataset, version_id: str | None = None
    ) -> DatasetVersion:
        vid = version_id or dataset.current_version_id
        version = s.get(DatasetVersion, vid) if vid else None
        if version is None or version.dataset_id != dataset.id:
            raise NotFound("Dataset has no loaded version")
        return version

    def run(
        self,
        s: Session,
        actor: Actor | None,
        dataset: Dataset,
        spec: QuerySpec,
        *,
        version_id: str | None = None,
        max_limit: int | None = None,
    ) -> QueryOutcome:
        if actor is not None:
            actor.require("read")
        version = self.current_version(s, dataset, version_id)
        types = version_types(version)
        compiler = QueryCompiler(
            column_types=types, max_limit=max_limit or self.settings.query_row_limit
        )
        compiled = compiler.compile(spec)
        if not compiled.success or compiled.plan is None:
            raise BadRequest("; ".join(compiled.errors))
        key = (version.content_hash, compiled.plan.plan_hash)
        hit = self.cache.get(key)
        if hit is not None:
            return QueryOutcome(result=hit, version=version, column_types=types, cached=True)
        result = self.executor.execute(compiled.plan, Path(version.parquet_path))
        self.cache.put(key, result)
        return QueryOutcome(result=result, version=version, column_types=types, cached=False)


def jsonable_rows(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """Dates → ISO strings; everything else is already JSON-native."""
    out = []
    for r in rows:
        out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()})
    return out
