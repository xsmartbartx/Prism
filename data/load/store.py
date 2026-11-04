"""Dataset store — immutable, content-addressed Parquet dataset versions.

Layout::

    <root>/<workspace_id>/<dataset_id>/v<version>.parquet
    <root>/<workspace_id>/<dataset_id>/v<version>.quarantine.parquet

Writes are atomic (temp file + rename) so a crash mid-load never leaves
a partial version visible. A version file is never modified after it is
written; a refresh produces a new version.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

PRISM_TO_ARROW: dict[str, pa.DataType] = {
    "integer": pa.int64(),
    "float": pa.float64(),
    "string": pa.string(),
    "date": pa.date32(),
    "boolean": pa.bool_(),
}


def arrow_schema(columns: list[tuple[str, str]]) -> pa.Schema:
    """Build an Arrow schema from ``(name, prism_type)`` pairs."""
    return pa.schema([pa.field(name, PRISM_TO_ARROW[t], nullable=True) for name, t in columns])


@dataclass(frozen=True)
class StoredVersion:
    path: Path
    content_hash: str
    row_count: int
    size_bytes: int


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DatasetStore:
    """Filesystem-backed Parquet store (S3-compatible backends can follow the same API)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, workspace_id: str, dataset_id: str) -> Path:
        for part in (workspace_id, dataset_id):
            if not part.isalnum():
                raise ValueError(f"Unsafe path component: {part!r}")
        return self.root / workspace_id / dataset_id

    def version_path(
        self, workspace_id: str, dataset_id: str, version: int, *, quarantine: bool = False
    ) -> Path:
        suffix = ".quarantine.parquet" if quarantine else ".parquet"
        return self._dir(workspace_id, dataset_id) / f"v{int(version)}{suffix}"

    def write(
        self,
        table: pa.Table,
        workspace_id: str,
        dataset_id: str,
        version: int,
        *,
        quarantine: bool = False,
    ) -> StoredVersion:
        """Atomically write ``table`` as an immutable version file."""
        target = self.version_path(workspace_id, dataset_id, version, quarantine=quarantine)
        if target.exists():
            raise FileExistsError(f"Dataset version already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            pq.write_table(table, tmp, compression="zstd")
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        return StoredVersion(
            path=target,
            content_hash=_file_sha256(target),
            row_count=table.num_rows,
            size_bytes=target.stat().st_size,
        )

    def read(self, path: Path | str) -> pa.Table:
        return pq.read_table(self._checked(path))

    def _checked(self, path: Path | str) -> Path:
        p = Path(path).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("Path is outside the dataset store")
        return p

    def delete_dataset(self, workspace_id: str, dataset_id: str) -> None:
        d = self._dir(workspace_id, dataset_id)
        if d.exists():
            shutil.rmtree(d)

    def usage_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*.parquet"))
