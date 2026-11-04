"""Plans and offline license keys.

A license key is ``PRISM1.<payload>.<signature>`` where ``payload`` is
base64url JSON and ``signature`` is an Ed25519 signature over the
literal bytes ``PRISM1.<payload>``. Keys verify offline against the
vendor public key compiled into this module, so air-gapped installs work
and no customer data ever leaves the instance.

Without a valid key the instance runs the Community plan. An expired
key falls back to Community limits after a grace period; nothing is
deleted — existing datasets and dashboards stay readable, only creating
beyond the limits is blocked.
"""

from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.clock import utcnow
from core.errors import PrismError
from server.db.models import Dashboard, Dataset, Setting, User, Workspace
from server.errors import LimitExceeded

# Vendor verification key (public half; the signing key never ships).
VENDOR_PUBLIC_KEY = "CDDFMDN0f-ryaWkVS50ewR25dvyD58Ngzytg_pB1KIs"
KEY_PREFIX = "PRISM1"
GRACE_DAYS = 14
UNLIMITED = 10**9


class LicenseError(PrismError):
    """The license key is malformed, tampered with or for another product."""


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    max_users: int
    max_workspaces: int
    max_datasets: int
    max_dashboards: int
    max_upload_mb: int
    features: frozenset[str]

    def to_dict(self) -> dict[str, Any]:
        def lim(v: int) -> int | None:
            return None if v >= UNLIMITED else v

        return {
            "code": self.code,
            "name": self.name,
            "limits": {
                "users": lim(self.max_users),
                "workspaces": lim(self.max_workspaces),
                "datasets": lim(self.max_datasets),
                "dashboards": lim(self.max_dashboards),
                "upload_mb": lim(self.max_upload_mb),
            },
            "features": sorted(self.features),
        }


PLANS: dict[str, Plan] = {
    "community": Plan("community", "Community", 5, 1, 10, 5, 25, frozenset({"share"})),
    "pro": Plan(
        "pro",
        "Pro",
        25,
        3,
        UNLIMITED,
        UNLIMITED,
        500,
        frozenset({"share", "embed", "api", "white_label", "audit_export"}),
    ),
    "business": Plan(
        "business",
        "Business",
        UNLIMITED,
        UNLIMITED,
        UNLIMITED,
        UNLIMITED,
        2048,
        frozenset({"share", "embed", "api", "white_label", "audit_export", "priority_support"}),
    ),
}

FEATURE_NAMES = {
    "embed": "Embedding charts in other sites",
    "api": "API keys",
    "white_label": "Removing Prism branding from shared pages",
    "audit_export": "Audit log export",
}


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_key(key: str, public_key: str = VENDOR_PUBLIC_KEY) -> dict[str, Any]:
    """Verify signature and structure; return the payload. Does not check expiry."""
    parts = key.strip().split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise LicenseError("Not a Prism license key")
    try:
        sig = _b64d(parts[2])
        Ed25519PublicKey.from_public_bytes(_b64d(public_key)).verify(
            sig, f"{parts[0]}.{parts[1]}".encode()
        )
        payload = json.loads(_b64d(parts[1]))
    except InvalidSignature as exc:
        raise LicenseError("License signature is invalid") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise LicenseError("License key is malformed") from exc
    if payload.get("product") != "prism" or payload.get("plan") not in PLANS:
        raise LicenseError("License is not valid for this product")
    return dict(payload)


@dataclass
class LicenseState:
    plan: Plan
    status: str  # community | active | grace | expired | invalid
    source: str | None = None  # env | database
    license_id: str | None = None
    customer: str | None = None
    email: str | None = None
    issued_at: str | None = None
    expires_at: datetime | None = None
    error: str | None = None
    licensed_plan: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "plan": self.plan.to_dict(),
            "licensed_plan": self.licensed_plan,
            "source": self.source,
            "license_id": self.license_id,
            "customer": self.customer,
            "email": self.email,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "error": self.error,
            "warnings": self.warnings,
        }


def evaluate(
    key: str | None,
    *,
    public_key: str = VENDOR_PUBLIC_KEY,
    source: str | None = None,
    now: datetime | None = None,
) -> LicenseState:
    """Turn a (possibly absent) key into the effective plan."""
    community = PLANS["community"]
    if not key:
        return LicenseState(plan=community, status="community")
    try:
        payload = verify_key(key, public_key)
    except LicenseError as exc:
        return LicenseState(plan=community, status="invalid", source=source, error=str(exc))
    base = PLANS[payload["plan"]]
    seats = payload.get("seats")
    workspaces = payload.get("workspaces")
    plan = Plan(
        code=base.code,
        name=base.name,
        max_users=int(seats) if seats else base.max_users,
        max_workspaces=int(workspaces) if workspaces else base.max_workspaces,
        max_datasets=base.max_datasets,
        max_dashboards=base.max_dashboards,
        max_upload_mb=base.max_upload_mb,
        features=base.features | frozenset(payload.get("features", [])),
    )
    expires = payload.get("expires_at")
    exp_dt = datetime.fromisoformat(expires) if expires else None
    state = LicenseState(
        plan=plan,
        status="active",
        source=source,
        license_id=payload.get("lid"),
        customer=payload.get("customer"),
        email=payload.get("email"),
        issued_at=payload.get("issued_at"),
        expires_at=exp_dt,
        licensed_plan=base.code,
    )
    now = now or utcnow()
    if exp_dt is not None:
        if now > exp_dt + timedelta(days=GRACE_DAYS):
            state.status, state.plan = "expired", community
            state.warnings.append("License expired; Community limits apply. Renew to restore.")
        elif now > exp_dt:
            state.status = "grace"
            days = (exp_dt + timedelta(days=GRACE_DAYS) - now).days
            state.warnings.append(f"License expired; renew within {days} days to keep {plan.name}.")
        elif exp_dt - now < timedelta(days=30):
            state.warnings.append(f"License expires on {exp_dt.date().isoformat()}.")
    return state


# ----------------------------------------------------------------------
# Instance-level state (cached; invalidated when the stored key changes)
# ----------------------------------------------------------------------

_cache: dict[str, Any] = {}
_lock = threading.Lock()


def stored_key(s: Session) -> str | None:
    row = s.get(Setting, "license")
    return str(row.value.get("key")) if row and row.value.get("key") else None


def current_state(svc: Any, s: Session) -> LicenseState:
    env_key = svc.settings.license_key
    key, source = (env_key, "env") if env_key else (stored_key(s), "database")
    pub = svc.settings.license_public_key or VENDOR_PUBLIC_KEY
    cache_key = f"{source}:{key}:{pub}:{utcnow().date().isoformat()}"
    with _lock:
        hit = _cache.get(cache_key)
        if hit is not None:
            return hit  # type: ignore[no-any-return]
        state = evaluate(key, public_key=pub, source=source if key else None)
        _cache.clear()
        _cache[cache_key] = state
        return state


def install_key(svc: Any, s: Session, key: str) -> LicenseState:
    pub = svc.settings.license_public_key or VENDOR_PUBLIC_KEY
    verify_key(key, pub)  # raises LicenseError with a clear message
    state = evaluate(key, public_key=pub, source="database")
    if state.status == "expired":
        raise LicenseError("This license has expired")
    row = s.get(Setting, "license")
    if row is None:
        s.add(Setting(key="license", value={"key": key.strip()}))
    else:
        row.value = {"key": key.strip()}
    s.flush()
    with _lock:
        _cache.clear()
    return state


def remove_key(s: Session) -> None:
    row = s.get(Setting, "license")
    if row is not None:
        s.delete(row)
        s.flush()
    with _lock:
        _cache.clear()


# ----------------------------------------------------------------------
# Usage and enforcement
# ----------------------------------------------------------------------


def seat_count(s: Session) -> int:
    return int(s.scalar(select(func.count()).select_from(User).where(User.is_active)) or 0)


def dataset_count(s: Session, workspace_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(Dataset)
    if workspace_id:
        stmt = stmt.where(Dataset.workspace_id == workspace_id)
    return int(s.scalar(stmt) or 0)


def usage(s: Session) -> dict[str, int]:
    return {
        "users": seat_count(s),
        "workspaces": int(s.scalar(select(func.count()).select_from(Workspace)) or 0),
        "datasets": dataset_count(s),
        "dashboards": int(s.scalar(select(func.count()).select_from(Dashboard)) or 0),
    }


def require_feature(svc: Any, s: Session, feature: str, *, current: int | None = None) -> None:
    """Raise LimitExceeded when the active plan does not allow one more ``feature``."""
    state = current_state(svc, s)
    plan = state.plan
    hint = " Upgrade your plan in Settings → License." if plan.code != "business" else ""
    counters = {
        "users": (plan.max_users, "users"),
        "workspaces": (plan.max_workspaces, "workspaces"),
        "datasets": (plan.max_datasets, "datasets"),
        "dashboards": (plan.max_dashboards, "dashboards"),
    }
    if feature in counters:
        limit, label = counters[feature]
        used = current if current is not None else usage(s)[feature]
        if used >= limit:
            raise LimitExceeded(f"The {plan.name} plan allows {limit} {label}.{hint}")
        return
    if feature == "upload_size":
        if current is not None and current > plan.max_upload_mb * 1024 * 1024:
            raise LimitExceeded(
                f"The {plan.name} plan allows uploads up to {plan.max_upload_mb} MB.{hint}"
            )
        return
    if feature not in plan.features:
        name = FEATURE_NAMES.get(feature, feature)
        raise LimitExceeded(f"{name} is not included in the {plan.name} plan.{hint}")


def show_branding(svc: Any, s: Session) -> bool:
    """Public pages show 'Made with Prism' unless the plan allows white-labelling."""
    return "white_label" not in current_state(svc, s).plan.features
