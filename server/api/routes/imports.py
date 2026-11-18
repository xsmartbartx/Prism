"""File upload and import review endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from server.api.deps import actor, services
from server.api.serializers import dataset_out, import_out, version_out
from server.container import Services
from server.errors import BadRequest
from server.schemas import CommitImport, ReproposeImport
from server.services import links
from server.services.context import Actor

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


async def read_upload(file: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise BadRequest(f"File exceeds the {limit // (1024 * 1024)} MB upload limit")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...), a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    from server.services.licensing import require_feature

    a.require("author")
    data = await read_upload(file, svc.settings.max_upload_bytes)
    with svc.db.transaction() as s:
        require_feature(svc, s, "upload_size", current=len(data))
        imp = svc.imports.create(s, a, file.filename or "upload.csv", data)
        return import_out(imp)


class LinkImport(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/link", status_code=201)
def import_link(
    body: LinkImport, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    """Download an https:// link and start an import from it, as if it were uploaded."""
    url, fetched = links.download_for_import(svc, a, body.url)
    with svc.db.transaction() as s:
        return import_out(links.create_import(svc, s, a, url, fetched))


@router.get("")
def list_imports(
    a: Actor = Depends(actor), svc: Services = Depends(services)
) -> list[dict[str, Any]]:
    with svc.db.transaction() as s:
        return [import_out(i) for i in svc.imports.list(s, a)]


@router.get("/{import_id}")
def get_import(
    import_id: str, a: Actor = Depends(actor), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        return import_out(svc.imports.get(s, a, import_id))


@router.post("/{import_id}/propose")
def repropose(
    import_id: str,
    body: ReproposeImport,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        imp = svc.imports.get(s, a, import_id)
        svc.imports.repropose(
            s, a, imp, sheet=body.sheet, header_row=body.header_row, locale=body.locale
        )
        return import_out(imp)


@router.post("/{import_id}/commit", status_code=201)
def commit(
    import_id: str,
    body: CommitImport,
    a: Actor = Depends(actor),
    svc: Services = Depends(services),
) -> dict[str, Any]:
    from server.services.licensing import require_feature

    with svc.db.transaction() as s:
        if not body.target_dataset_id:
            require_feature(svc, s, "datasets")
        imp = svc.imports.get(s, a, import_id)
        loaded = svc.imports.commit(s, a, imp, body)
        out = dataset_out(loaded.dataset, loaded.version)
        out["load"] = {
            "rows": loaded.result.row_count,
            "quarantined": loaded.result.quarantine_count,
            "reasons": loaded.result.reasons,
            "version": version_out(loaded.version)["version"],
        }
        return out
