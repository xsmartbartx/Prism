"""Datasets that follow a link: import from a URL, refresh now, refresh on a schedule.

A link refresh is an ordinary refresh (same binding, drift rules and versioning
as uploading a new file) whose bytes come from the link. It skips work twice
over: a ``304 Not Modified`` answer, or a download whose SHA-256 equals the
current version's source, records "unchanged" and makes no new version.

Downloads never run inside a database transaction: the session is opened to
read what is needed, closed for the download, and opened again to load.

Scheduled refreshes run in the app process (``server.scheduler``) with the
access of the person who set the schedule, and are claimed with a lease so two
processes sharing one database never refresh the same link at once. After
``MAX_FAILURES`` failures in a row a schedule is paused (set back to manual),
so a dead link does not fail forever unnoticed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from core.clock import utcnow
from core.errors import DriftDetected, PrismError
from data.connectors.link import Fetched, LinkPolicy, check_url
from server.db.models import (
    Dataset,
    DatasetLink,
    DatasetVersion,
    Import,
    Membership,
    RefreshSchedule,
    Role,
    User,
)
from server.errors import BadRequest, Forbidden, NotFound
from server.services import audit
from server.services.context import Actor

log = logging.getLogger("prism.links")

INTERVALS = {
    RefreshSchedule.HOURLY.value: timedelta(hours=1),
    RefreshSchedule.DAILY.value: timedelta(days=1),
    RefreshSchedule.WEEKLY.value: timedelta(weeks=1),
}
SCHEDULES = tuple(s.value for s in RefreshSchedule)
MAX_FAILURES = 5
LEASE = timedelta(minutes=15)
_AUTHOR_ROLES = {Role.AUTHOR, Role.STEWARD, Role.ADMIN}


@dataclass(frozen=True)
class Outcome:
    status: str  # loaded | unchanged | failed | drift
    error: str | None = None
    version: int | None = None
    rows: int | None = None
    quarantined: int | None = None


# ----------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------


def require_enabled(svc: Any) -> None:
    if not svc.settings.link_imports:
        raise Forbidden("Importing from links is turned off on this Prism instance")


def link_policy(svc: Any, s: Session) -> LinkPolicy:
    from server.services.licensing import current_state

    plan_bytes = current_state(svc, s).plan.max_upload_mb * 1024 * 1024
    return LinkPolicy(
        max_bytes=min(svc.settings.max_upload_bytes, plan_bytes),
        allow_private=svc.settings.link_allow_private,
        timeout_s=svc.settings.link_timeout_s,
    )


def _host(url: str) -> str:
    try:
        return check_url(url).host
    except PrismError:
        return "the link"


# ----------------------------------------------------------------------
# Import from a link
# ----------------------------------------------------------------------


def download_for_import(svc: Any, actor: Actor, url: str) -> tuple[str, Fetched]:
    """Check permissions and the address, then download (outside any transaction)."""
    actor.require("author")
    require_enabled(svc)
    target = check_url(url)
    with svc.db.transaction() as s:
        policy = link_policy(svc, s)
    return target.url, svc.link_fetch(target.url, policy)


def create_import(svc: Any, s: Session, actor: Actor, url: str, fetched: Fetched) -> Import:
    imp: Import = svc.imports.create(s, actor, fetched.filename, fetched.data)
    imp.source_url = url
    audit.record(
        s,
        actor,
        "import.link",
        target_type="import",
        target_id=imp.id,
        description=f"Downloaded {imp.filename} from {_host(url)}",
        details={"host": _host(url), "kind": fetched.kind},
    )
    return imp


def attach(s: Session, actor: Actor, dataset: Dataset, url: str) -> DatasetLink:
    """Remember the link a dataset was imported from (manual refresh until a schedule is set)."""
    link = s.scalars(select(DatasetLink).where(DatasetLink.dataset_id == dataset.id)).first()
    if link is None:
        link = DatasetLink(
            dataset_id=dataset.id,
            workspace_id=dataset.workspace_id,
            url=url,
            schedule=RefreshSchedule.MANUAL.value,
            owner_id=actor.user_id,
            failures=0,
        )
        s.add(link)
    elif link.url != url:
        _reset(link)
        link.url = url
    s.flush()
    return link


# ----------------------------------------------------------------------
# Manage a dataset's link
# ----------------------------------------------------------------------


def get_link(s: Session, actor: Actor, dataset: Dataset) -> DatasetLink | None:
    actor.require("author")  # the address may carry an access token
    return s.scalars(select(DatasetLink).where(DatasetLink.dataset_id == dataset.id)).first()


def set_link(
    svc: Any, s: Session, actor: Actor, dataset: Dataset, url: str, schedule: str
) -> DatasetLink:
    from server.services.licensing import require_feature

    actor.require("author")
    require_enabled(svc)
    if schedule not in SCHEDULES:
        raise BadRequest(f"Choose a schedule: {', '.join(SCHEDULES)}")
    target = check_url(url)
    if schedule != RefreshSchedule.MANUAL.value:
        require_feature(svc, s, "scheduled_refresh")
    link = s.scalars(select(DatasetLink).where(DatasetLink.dataset_id == dataset.id)).first()
    created = link is None
    if link is None:
        link = DatasetLink(
            dataset_id=dataset.id, workspace_id=dataset.workspace_id, url=target.url, failures=0
        )
        s.add(link)
    url_changed = link.url != target.url
    if url_changed:
        _reset(link)
        link.url = target.url
    if created or url_changed or link.schedule != schedule:
        link.next_run_at = _next_run(schedule, utcnow())
        link.failures = 0
    link.schedule = schedule
    link.owner_id = actor.user_id
    s.flush()
    audit.record(
        s,
        actor,
        "dataset.link",
        target_type="dataset",
        target_id=dataset.id,
        description=f"{dataset.name} refreshes from {target.host} ({schedule})",
        details={"host": target.host, "schedule": schedule},
    )
    return link


def delete_link(s: Session, actor: Actor, dataset: Dataset) -> None:
    link = get_link(s, actor, dataset)
    if link is None:
        raise NotFound("This dataset has no link")
    s.delete(link)
    audit.record(
        s,
        actor,
        "dataset.unlink",
        target_type="dataset",
        target_id=dataset.id,
        description=f"{dataset.name} no longer refreshes from {_host(link.url)}",
    )


def _reset(link: DatasetLink) -> None:
    link.etag = link.last_modified = None
    link.last_status = link.last_error = None
    link.failures = 0


def _next_run(schedule: str, now: datetime) -> datetime | None:
    step = INTERVALS.get(schedule)
    return now + step if step else None


# ----------------------------------------------------------------------
# Refresh
# ----------------------------------------------------------------------


def refresh(svc: Any, actor: Actor, dataset_id: str, *, scheduled: bool = False) -> Outcome:
    """Download the link and load it as a new version when it changed.

    Failures are recorded on the link and returned, never raised, so the caller
    always sees what happened and the record survives the failed load.
    """
    actor.require("author")
    require_enabled(svc)
    with svc.db.transaction() as s:
        ds = s.get(Dataset, dataset_id)
        if ds is None or ds.workspace_id != actor.workspace_id:
            raise NotFound("Dataset not found")
        link = s.scalars(select(DatasetLink).where(DatasetLink.dataset_id == ds.id)).first()
        if link is None:
            raise NotFound("This dataset has no link to refresh from")
        url, etag, last_modified = link.url, link.etag, link.last_modified
        current = s.get(DatasetVersion, ds.current_version_id) if ds.current_version_id else None
        current_sha = current.source_sha256 if current else None
        policy = link_policy(svc, s)

    try:
        fetched = svc.link_fetch(url, policy, etag=etag, last_modified=last_modified)
    except PrismError as exc:
        return _record(svc, actor, dataset_id, Outcome("failed", str(exc)), scheduled)

    if fetched.not_modified or hashlib.sha256(fetched.data).hexdigest() == current_sha:
        return _record(svc, actor, dataset_id, Outcome("unchanged"), scheduled, fetched)

    try:
        with svc.db.transaction() as s:
            ds = s.get(Dataset, dataset_id)
            if ds is None:
                raise NotFound("Dataset not found")
            loaded = svc.imports.refresh(s, actor, ds, fetched.filename, fetched.data)
            imp = s.get(Import, loaded.version.import_id) if loaded.version.import_id else None
            if imp is not None:
                imp.source_url = url
                # The link is the source of truth; keeping every download would only fill the disk.
                Path(imp.storage_path).unlink(missing_ok=True)
            outcome = Outcome(
                "loaded",
                version=loaded.version.version,
                rows=loaded.result.row_count,
                quarantined=loaded.result.quarantine_count,
            )
            _apply(s, ds.id, outcome, scheduled, fetched)
            return outcome
    except DriftDetected as exc:
        return _record(svc, actor, dataset_id, Outcome("drift", str(exc)), scheduled)
    except PrismError as exc:
        return _record(svc, actor, dataset_id, Outcome("failed", str(exc)), scheduled)


def _record(
    svc: Any,
    actor: Actor,
    dataset_id: str,
    outcome: Outcome,
    scheduled: bool,
    fetched: Fetched | None = None,
) -> Outcome:
    with svc.db.transaction() as s:
        ds = s.get(Dataset, dataset_id)
        if ds is None:
            return outcome
        final = _apply(s, ds.id, outcome, scheduled, fetched)
        if final.status in ("failed", "drift"):
            audit.record(
                s,
                actor,
                "dataset.drift" if final.status == "drift" else "dataset.refresh_failed",
                target_type="dataset",
                target_id=ds.id,
                description=f"Refreshing {ds.name} from its link failed: {final.error}",
                details={"via": "schedule" if scheduled else "link"},
            )
        return final


def _apply(
    s: Session,
    dataset_id: str,
    outcome: Outcome,
    scheduled: bool,
    fetched: Fetched | None,
) -> Outcome:
    link = s.scalars(select(DatasetLink).where(DatasetLink.dataset_id == dataset_id)).first()
    if link is None:
        return outcome
    now = utcnow()
    link.last_run_at = now
    link.last_status = outcome.status
    link.last_error = outcome.error
    link.lease_until = None
    if fetched is not None:
        link.etag = fetched.etag
        link.last_modified = fetched.last_modified
    if outcome.status in ("loaded", "unchanged"):
        link.failures = 0
    else:
        link.failures = (link.failures or 0) + 1
    if scheduled:
        link.next_run_at = _next_run(link.schedule, now)
    if link.failures >= MAX_FAILURES and link.schedule != RefreshSchedule.MANUAL.value:
        pause = (
            f" Scheduled refresh is paused after {MAX_FAILURES} failures in a row; "
            "fix the link, then choose a schedule again."
        )
        link.schedule = RefreshSchedule.MANUAL.value
        link.next_run_at = None
        link.last_error = (link.last_error or "") + pause
        outcome = Outcome(outcome.status, link.last_error)
    s.flush()
    return outcome


# ----------------------------------------------------------------------
# Schedule
# ----------------------------------------------------------------------


def _pause(s: Session, link: DatasetLink, reason: str) -> None:
    link.schedule = RefreshSchedule.MANUAL.value
    link.next_run_at = None
    link.lease_until = None
    link.last_run_at = utcnow()
    link.last_status = "failed"
    link.last_error = reason
    audit.record(
        s,
        None,
        "dataset.refresh_failed",
        target_type="dataset",
        target_id=link.dataset_id,
        description=reason,
        details={"via": "schedule"},
        workspace_id=link.workspace_id,
    )


def scheduled_actor(s: Session, link: DatasetLink) -> Actor | None:
    """The schedule's owner, if they may still refresh this dataset."""
    user = s.get(User, link.owner_id) if link.owner_id else None
    if user is None or not user.is_active:
        return None
    role = s.scalar(
        select(Membership.role).where(
            Membership.user_id == user.id, Membership.workspace_id == link.workspace_id
        )
    )
    if role is None or Role(role) not in _AUTHOR_ROLES:
        return None
    return Actor(
        user_id=user.id,
        label=f"{user.email} (schedule)",
        workspace_id=link.workspace_id,
        role=Role(role),
        via="system",
    )


def run_due(svc: Any, now: datetime | None = None, limit: int = 10) -> int:
    """Refresh up to ``limit`` links whose schedule is due. Returns how many ran."""
    from server.services.licensing import current_state

    if not svc.settings.link_imports:
        return 0
    now = now or utcnow()
    with svc.db.transaction() as s:
        due = s.scalars(
            select(DatasetLink.id)
            .where(
                DatasetLink.schedule != RefreshSchedule.MANUAL.value,
                DatasetLink.next_run_at <= now,
                or_(DatasetLink.lease_until.is_(None), DatasetLink.lease_until < now),
            )
            .order_by(DatasetLink.next_run_at)
            .limit(limit)
        ).all()
    ran = 0
    for link_id in due:
        with svc.db.transaction() as s:
            claimed = s.execute(
                update(DatasetLink)
                .where(
                    DatasetLink.id == link_id,
                    DatasetLink.next_run_at <= now,
                    or_(DatasetLink.lease_until.is_(None), DatasetLink.lease_until < now),
                )
                .values(lease_until=now + LEASE)
            )
            if getattr(claimed, "rowcount", 0) != 1:
                continue  # another process took it
            link = s.get(DatasetLink, link_id)
            if link is None:
                continue
            dataset_id = link.dataset_id
            actor = scheduled_actor(s, link)
            if "scheduled_refresh" not in current_state(svc, s).plan.features:
                _pause(
                    s,
                    link,
                    "Scheduled refresh is not included in the current plan; it was paused.",
                )
                continue
            if actor is None:
                _pause(
                    s,
                    link,
                    "The person who set this schedule can no longer refresh the dataset; "
                    "an author must choose the schedule again.",
                )
                continue
        try:
            refresh(svc, actor, dataset_id, scheduled=True)
        except Exception:  # a bug must not stop the other schedules or keep the lease
            log.exception("Scheduled refresh of dataset %s failed", dataset_id)
            _record(svc, actor, dataset_id, Outcome("failed", "Internal error"), True)
        ran += 1
    return ran
