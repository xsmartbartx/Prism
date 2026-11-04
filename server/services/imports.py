"""Import service: upload → proposal → reviewed binding → dataset version.

This is the Phase 0 exit path from the architecture document: a person
drops a file, confirms the inference decisions the engine could not make
alone, and gets a typed, versioned dataset whose every step is audited.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.errors import ConnectorError, DriftDetected, PrismError
from core.nulls import DEFAULT_NULL_TOKENS
from core.types.column import ColumnContract, DriftPolicy
from data.connectors import ConnectorLimits, SourceTable, list_sheets, read_delimited, read_sheet
from data.detection.proposal import build_proposal
from data.load.runner import LoadColumn, LoadResult, load_rows
from data.load.store import DatasetStore
from data.profile import profile_table
from schemas.binding import ConnectorType, SourceBinding
from server.config import Settings
from server.db.models import (
    Binding,
    Dataset,
    DatasetVersion,
    Import,
    ImportStatus,
    new_id,
)
from server.errors import BadRequest, NotFound
from server.schemas import CommitImport
from server.services import audit
from server.services.context import Actor

ALLOWED_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
}
PROPOSAL_ROWS = 20_000


@dataclass(frozen=True)
class LoadedVersion:
    dataset: Dataset
    version: DatasetVersion
    result: LoadResult


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip(" .")
    return base[:200] or "upload"


class ImportService:
    def __init__(self, settings: Settings, store: DatasetStore) -> None:
        self.settings = settings
        self.store = store
        self.limits = ConnectorLimits()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def create(self, s: Session, actor: Actor, filename: str, data: bytes) -> Import:
        actor.require("author")
        name = safe_filename(filename)
        ext = Path(name).suffix.lower()
        kind = ALLOWED_EXTENSIONS.get(ext)
        if kind is None:
            raise BadRequest(
                f"Unsupported file type '{ext or '?'}'. Upload .csv, .tsv, .txt, .xlsx or .xlsm"
            )
        if not data:
            raise BadRequest("The file is empty")
        if len(data) > self.settings.max_upload_bytes:
            raise BadRequest(f"File exceeds the {self.settings.max_upload_mb} MB upload limit")
        if kind == "xlsx" and not data.startswith(b"PK"):
            raise BadRequest("File is not a valid .xlsx workbook")

        imp_id = new_id()
        folder = self.settings.uploads_dir / actor.workspace_id / imp_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"source{ext}"
        path.write_bytes(data)
        imp = Import(
            id=imp_id,
            workspace_id=actor.workspace_id,
            created_by=actor.user_id,
            filename=name,
            file_kind=kind,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            storage_path=str(path),
            sheet_names=[],
            status=ImportStatus.UPLOADED.value,
        )
        s.add(imp)
        s.flush()
        audit.record(
            s,
            actor,
            "import.upload",
            target_type="import",
            target_id=imp.id,
            description=f"Uploaded {name}",
            details={"size": len(data), "sha256": imp.sha256, "kind": kind},
        )
        try:
            if kind == "xlsx":
                imp.sheet_names = list_sheets(data, self.limits)
            self._propose(imp, data)
        except ConnectorError as exc:
            imp.status = ImportStatus.FAILED.value
            imp.error = str(exc)
        return imp

    def get(self, s: Session, actor: Actor, import_id: str) -> Import:
        imp = s.get(Import, import_id)
        if imp is None or imp.workspace_id != actor.workspace_id:
            raise NotFound("Import not found")
        return imp

    def list(self, s: Session, actor: Actor, limit: int = 50) -> list[Import]:
        q = (
            select(Import)
            .where(Import.workspace_id == actor.workspace_id)
            .order_by(Import.created_at.desc())
            .limit(limit)
        )
        return list(s.scalars(q))

    # ------------------------------------------------------------------
    # Proposal
    # ------------------------------------------------------------------

    def _read(
        self, kind: str, data: bytes, *, sheet: str | None, max_rows: int | None
    ) -> SourceTable:
        if kind == "xlsx":
            return read_sheet(data, sheet, limits=self.limits, max_rows=max_rows)
        return read_delimited(data, limits=self.limits, max_rows=max_rows)

    def _propose(
        self,
        imp: Import,
        data: bytes,
        *,
        sheet: str | None = None,
        header_row: int | None = None,
        locale: str | None = None,
    ) -> None:
        table = self._read(imp.file_kind, data, sheet=sheet, max_rows=PROPOSAL_ROWS)
        proposal = build_proposal(
            table.rows,
            header_row=header_row,
            locale=locale,
            sheet=table.sheet,
            delimiter=table.delimiter,
            encoding=table.encoding,
            warnings=table.warnings,
        )
        doc = proposal.to_dict()
        doc["sample_truncated"] = table.truncated
        if not proposal.columns:
            imp.status = ImportStatus.FAILED.value
            imp.error = "No tabular data was found in this file"
        else:
            status = ImportStatus.NEEDS_REVIEW if proposal.needs_review else ImportStatus.READY
            imp.status = status.value
            imp.error = None
        imp.proposal = doc

    def repropose(
        self,
        s: Session,
        actor: Actor,
        imp: Import,
        *,
        sheet: str | None,
        header_row: int | None,
        locale: str | None,
    ) -> Import:
        actor.require("author")
        if imp.status == ImportStatus.LOADED.value:
            raise BadRequest("This import has already been published")
        if sheet is not None and imp.file_kind == "xlsx":
            names = [sh["name"] for sh in imp.sheet_names]
            if sheet not in names:
                raise BadRequest(f"Sheet '{sheet}' not found")
        try:
            self._propose(imp, self._bytes(imp), sheet=sheet, header_row=header_row, locale=locale)
        except ConnectorError as exc:
            imp.status = ImportStatus.FAILED.value
            imp.error = str(exc)
        return imp

    def _bytes(self, imp: Import) -> bytes:
        path = Path(imp.storage_path)
        if not path.exists():
            raise NotFound("The uploaded file is no longer available; upload it again")
        return path.read_bytes()

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def commit(self, s: Session, actor: Actor, imp: Import, req: CommitImport) -> LoadedVersion:
        actor.require("author")
        if imp.status == ImportStatus.LOADED.value:
            raise BadRequest("This import has already been published")
        included = [c for c in req.columns if c.include]
        if not included:
            raise BadRequest("Select at least one column")
        names = [c.name.strip() for c in included]
        if len({n.lower() for n in names}) != len(names):
            raise BadRequest("Column names must be unique")

        binding = SourceBinding(
            name=req.dataset_name,
            connector_type=(
                ConnectorType.SPREADSHEET if imp.file_kind == "xlsx" else ConnectorType.CSV
            ),
            source=imp.filename,
            sheet_name=req.sheet if imp.file_kind == "xlsx" else None,
            header_row_index=max(req.header_row, 0),
            data_start_row=req.data_start_row,
            delimiter=(imp.proposal or {}).get("delimiter"),
            locale=req.locale,
            max_quarantine_ratio=req.max_quarantine_ratio,
            description=req.description or None,
            tags=req.tags,
            columns=[
                ColumnContract(
                    name=c.name.strip(),
                    type=c.type,
                    locale=c.locale or req.locale,
                    role=c.role,
                    nullable=c.nullable,
                    description=c.description,
                    source_name=c.source_name.strip() if req.header_row >= 0 else None,
                    source_index=c.index,
                    drift_policy=DriftPolicy.FAIL,
                )
                for c in included
            ],
        )
        binding.validate_binding()

        if req.target_dataset_id:
            dataset = s.get(Dataset, req.target_dataset_id)
            if dataset is None or dataset.workspace_id != actor.workspace_id:
                raise NotFound("Target dataset not found")
        else:
            dataset = Dataset(
                id=new_id(),
                workspace_id=actor.workspace_id,
                name=req.dataset_name,
                description=req.description,
                tags=req.tags,
                owner_id=actor.user_id,
            )
            s.add(dataset)
            s.flush()
            audit.record(
                s,
                actor,
                "dataset.create",
                target_type="dataset",
                target_id=dataset.id,
                description=f"Created dataset {dataset.name}",
            )

        header_present = req.header_row >= 0
        loaded = self._load(
            s,
            actor,
            dataset,
            binding,
            self._bytes(imp),
            imp.file_kind,
            import_id=imp.id,
            header_row=req.header_row if header_present else -1,
            source_sha256=imp.sha256,
        )
        imp.status = ImportStatus.LOADED.value
        imp.dataset_id = dataset.id
        return loaded

    def refresh(
        self, s: Session, actor: Actor, dataset: Dataset, filename: str, data: bytes
    ) -> LoadedVersion:
        """Load a new file against the dataset's current binding (new version)."""
        actor.require("author")
        binding_row = s.scalars(
            select(Binding).where(Binding.dataset_id == dataset.id).order_by(Binding.version.desc())
        ).first()
        if binding_row is None:
            raise BadRequest("Dataset has no binding to refresh against")
        binding = SourceBinding.model_validate(binding_row.document)
        imp = self.create(s, actor, filename, data)
        expected_kind = "xlsx" if binding.connector_type == ConnectorType.SPREADSHEET else "csv"
        if imp.file_kind != expected_kind:
            raise BadRequest(f"This dataset is refreshed from {expected_kind} files")
        header_present = any(c.source_name for c in binding.columns)
        try:
            loaded = self._load(
                s,
                actor,
                dataset,
                binding,
                data,
                imp.file_kind,
                import_id=imp.id,
                header_row=binding.header_row_index if header_present else -1,
                source_sha256=imp.sha256,
                relocate_header=header_present,
            )
        except DriftDetected as exc:
            imp.status = ImportStatus.FAILED.value
            imp.error = str(exc)
            audit.record(
                s,
                actor,
                "dataset.drift",
                target_type="dataset",
                target_id=dataset.id,
                description=str(exc),
                details={"import_id": imp.id},
            )
            raise
        imp.status = ImportStatus.LOADED.value
        imp.dataset_id = dataset.id
        return loaded

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _load(
        self,
        s: Session,
        actor: Actor,
        dataset: Dataset,
        binding: SourceBinding,
        data: bytes,
        kind: str,
        *,
        import_id: str | None,
        header_row: int,
        source_sha256: str,
        relocate_header: bool = False,
    ) -> LoadedVersion:
        try:
            table = self._read(kind, data, sheet=binding.sheet_name, max_rows=None)
        except ConnectorError as exc:
            raise BadRequest(str(exc)) from exc
        if table.truncated:
            raise BadRequest(f"File has more than {self.limits.max_rows:,} rows")
        rows = table.rows
        data_start = (
            binding.data_start_row if binding.data_start_row is not None else header_row + 1
        )
        if relocate_header:
            found = _locate_header(rows, [c.source_name or "" for c in binding.columns])
            if found is not None and found != header_row:
                data_start += found - header_row
                header_row = found

        cols = [
            LoadColumn(
                name=c.name,
                type=c.type,
                locale=c.locale,
                nullable=c.nullable,
                source_name=c.source_name,
                source_index=c.source_index,
                drift_policy=c.drift_policy,
            )
            for c in binding.columns
        ]
        tokens = frozenset(t.lower() for t in binding.null_tokens) or DEFAULT_NULL_TOKENS
        result = load_rows(
            rows,
            cols,
            header_row=header_row,
            data_start_row=data_start,
            max_quarantine_ratio=binding.max_quarantine_ratio,
            null_tokens=tokens,
        )

        latest = s.scalar(
            select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == dataset.id)
        )
        version_no = (latest or 0) + 1
        bhash = binding.content_hash()
        brow = s.scalars(
            select(Binding)
            .where(Binding.dataset_id == dataset.id, Binding.content_hash == bhash)
            .order_by(Binding.version.desc())
        ).first()
        if brow is None:
            bver = (
                s.scalar(select(func.max(Binding.version)).where(Binding.dataset_id == dataset.id))
                or 0
            ) + 1
            brow = Binding(
                id=new_id(),
                dataset_id=dataset.id,
                version=bver,
                document=binding.to_dict(),
                content_hash=bhash,
                created_by=actor.user_id,
            )
            s.add(brow)
            s.flush()
            audit.record(
                s,
                actor,
                "binding.publish",
                target_type="binding",
                target_id=brow.id,
                description=f"Published binding v{bver} for {dataset.name}",
                details={"dataset_id": dataset.id, "hash": bhash},
            )

        try:
            stored = self.store.write(result.table, dataset.workspace_id, dataset.id, version_no)
            qstored = (
                self.store.write(
                    result.quarantine,
                    dataset.workspace_id,
                    dataset.id,
                    version_no,
                    quarantine=True,
                )
                if result.quarantine is not None
                else None
            )
        except (OSError, PrismError) as exc:
            raise BadRequest(f"Could not store dataset version: {exc}") from exc

        version = DatasetVersion(
            id=new_id(),
            dataset_id=dataset.id,
            version=version_no,
            binding_id=brow.id,
            import_id=import_id,
            parquet_path=str(stored.path),
            quarantine_path=str(qstored.path) if qstored else None,
            row_count=result.row_count,
            quarantine_count=result.quarantine_count,
            content_hash=stored.content_hash,
            columns=[c.to_dict() for c in binding.columns],
            profile=profile_table(result.table),
            source_sha256=source_sha256,
            created_by=actor.user_id,
        )
        s.add(version)
        s.flush()
        dataset.current_version_id = version.id
        details: dict[str, Any] = {
            "version": version_no,
            "rows": result.row_count,
            "quarantined": result.quarantine_count,
            "binding_id": brow.id,
            "binding_hash": bhash,
            "content_hash": stored.content_hash,
            "source_sha256": source_sha256,
            "import_id": import_id,
        }
        if result.reasons:
            details["quarantine_reasons"] = result.reasons
        if result.drift:
            details["drift"] = result.drift
        audit.record(
            s,
            actor,
            "dataset.load",
            target_type="dataset",
            target_id=dataset.id,
            description=(
                f"Loaded v{version_no} of {dataset.name}: {result.row_count:,} rows"
                + (f", {result.quarantine_count:,} quarantined" if result.quarantine_count else "")
            ),
            details=details,
        )
        return LoadedVersion(dataset=dataset, version=version, result=result)


def _locate_header(rows: list[list[str]], source_names: list[str]) -> int | None:
    """Find the row (within the first 50) that contains every expected header."""
    wanted = {" ".join(n.split()).lower() for n in source_names if n}
    if not wanted:
        return None
    for i, row in enumerate(rows[:50]):
        cells = {" ".join(c.split()).lower() for c in row if c.strip()}
        if wanted <= cells:
            return i
    return None
