"""Instance administration: license, usage, instance info."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from server import __version__
from server.api.deps import Principal, principal, services
from server.container import Services
from server.db.models import Setting
from server.errors import Forbidden
from server.services import audit, licensing

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class LicenseIn(BaseModel):
    key: str = Field(min_length=10, max_length=8192)


def _require_superadmin(p: Principal) -> None:
    if not p.user.is_superadmin:
        raise Forbidden("Only the instance owner can manage the license")


def instance_id(svc: Services) -> str:
    with svc.db.transaction() as s:
        row = s.get(Setting, "instance")
        if row is None:
            row = Setting(key="instance", value={"id": secrets.token_hex(8)})
            s.add(row)
        return str(row.value["id"])


@router.get("/license")
def get_license(
    p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    with svc.db.transaction() as s:
        state = licensing.current_state(svc, s)
        out = state.to_dict()
        out["usage"] = licensing.usage(s)
        out["plans"] = {code: plan.to_dict() for code, plan in licensing.PLANS.items()}
        out["can_manage"] = p.user.is_superadmin
        out["instance_id"] = instance_id(svc)
        out["env_locked"] = bool(svc.settings.license_key)
        return out


@router.put("/license")
def put_license(
    body: LicenseIn, p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    _require_superadmin(p)
    with svc.db.transaction() as s:
        state = licensing.install_key(svc, s, body.key)
        audit.record(
            s,
            p.actor,
            "license.install",
            target_type="license",
            target_id=state.license_id,
            description=f"Installed {state.plan.name} license for {state.customer}",
        )
        return state.to_dict()


@router.delete("/license", status_code=204)
def delete_license(p: Principal = Depends(principal), svc: Services = Depends(services)) -> None:
    _require_superadmin(p)
    with svc.db.transaction() as s:
        licensing.remove_key(s)
        audit.record(
            s,
            p.actor,
            "license.remove",
            target_type="license",
            description="Removed license key; Community plan applies",
        )


@router.get("/instance")
def instance(
    p: Principal = Depends(principal), svc: Services = Depends(services)
) -> dict[str, Any]:
    p.actor.require("admin")
    db_url = svc.settings.resolved_database_url
    return {
        "version": __version__,
        "instance_id": instance_id(svc),
        "database": db_url.split(":", 1)[0],
        "storage_bytes": svc.store.usage_bytes(),
        "base_url": svc.settings.base_url,
        "max_upload_mb": svc.settings.max_upload_mb,
    }
