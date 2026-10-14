"""In-memory searchable catalog index."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from catalog.models import ArtifactType, CatalogEntry, AuditEvent, AuditAction


def _gid(name: str, t: ArtifactType) -> str:
    raw = f"{t.value}:{name}:{datetime.utcnow().isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class CatalogIndex:
    """Thread-safe in-memory catalog index."""

    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}
        self._by_type: dict[ArtifactType, dict[str, CatalogEntry]] = {t: {} for t in ArtifactType}
        self._audit_log: list[AuditEvent] = []

    def register(self, name: str, artifact_type: ArtifactType, *,
                 description: str = "", tags: list[str] | None = None,
                 owner: str | None = None, columns: list[str] | None = None,
                 row_count: int = 0, source: str | None = None,
                 actor: str | None = None) -> CatalogEntry:
        entry_id = _gid(name, artifact_type)
        now = datetime.utcnow()
        cols = columns or []
        entry = CatalogEntry(id=entry_id, name=name, artifact_type=artifact_type,
            description=description, tags=tags or [], owner=owner,
            created_at=now, updated_at=now, columns=cols,
            column_count=len(cols), row_count=row_count, source=source)
        self._entries[entry_id] = entry
        self._by_type[artifact_type][entry_id] = entry
        self._log(AuditAction.CREATE, artifact_type, entry_id, actor)
        return entry

    def update(self, entry_id: str, *, name: str | None = None,
               description: str | None = None, tags: list[str] | None = None,
               owner: str | None = None, row_count: int | None = None,
               actor: str | None = None) -> CatalogEntry | None:
        entry = self._entries.get(entry_id)
        if not entry: return None
        now = datetime.utcnow()
        updated = CatalogEntry(id=entry.id, name=name or entry.name,
            artifact_type=entry.artifact_type,
            description=description if description is not None else entry.description,
            tags=tags if tags is not None else entry.tags,
            owner=owner if owner is not None else entry.owner,
            created_at=entry.created_at, updated_at=now,
            columns=entry.columns, column_count=entry.column_count,
            row_count=row_count or entry.row_count, source=entry.source)
        self._entries[entry_id] = updated
        self._by_type[entry.artifact_type][entry_id] = updated
        self._log(AuditAction.UPDATE, entry.artifact_type, entry_id, actor)
        return updated

    def delete(self, entry_id: str, actor: str | None = None) -> bool:
        entry = self._entries.pop(entry_id, None)
        if not entry: return False
        self._by_type[entry.artifact_type].pop(entry_id, None)
        self._log(AuditAction.DELETE, entry.artifact_type, entry_id, actor)
        return True

    def get(self, entry_id: str) -> CatalogEntry | None:
        return self._entries.get(entry_id)

    def search(self, query: str = "", *, artifact_type: ArtifactType | None = None,
               tags: list[str] | None = None, limit: int = 50) -> list[CatalogEntry]:
        pool = self._by_type.get(artifact_type, self._entries) if artifact_type else self._entries
        q = query.lower()
        results = []
        for entry in pool.values():
            if q:
                in_name = q in entry.name.lower()
                in_desc = q in entry.description.lower()
                in_tags = any(q in t.lower() for t in entry.tags)
                in_cols = any(q in c.lower() for c in entry.columns)
                if not (in_name or in_desc or in_tags or in_cols):
                    continue
            if tags:
                et = set(t.lower() for t in entry.tags)
                if not set(t.lower() for t in tags).issubset(et):
                    continue
            results.append(entry)
        results.sort(key=lambda e: e.name.lower())
        return results[:limit]

    def list_by_type(self, t: ArtifactType, limit: int = 100) -> list[CatalogEntry]:
        entries = list(self._by_type.get(t, {}).values())
        entries.sort(key=lambda e: e.name.lower())
        return entries[:limit]

    def count(self) -> int: return len(self._entries)
    def count_by_type(self, t: ArtifactType) -> int: return len(self._by_type.get(t, {}))

    def _log(self, action: AuditAction, target_type: ArtifactType,
             target_id: str, actor: str | None = None) -> AuditEvent:
        e = AuditEvent(event_id=uuid.uuid4().hex[:16], action=action,
            actor=actor, target_type=target_type, target_id=target_id)
        self._audit_log.append(e)
        return e

    def get_audit_log(self, limit: int = 100, target_id: str | None = None) -> list[AuditEvent]:
        events = [e for e in self._audit_log if e.target_id == target_id] if target_id else self._audit_log
        return events[-limit:][::-1]