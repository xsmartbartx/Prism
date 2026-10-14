"""Catalog data models — artifact entries and audit events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ArtifactType(str, Enum):
    """Types of artifacts in the catalog."""

    BINDING = "binding"
    DATASET = "dataset"
    CHART = "chart"
    DASHBOARD = "dashboard"


class AuditAction(str, Enum):
    """Actions recorded in the audit log."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    PUBLISH = "publish"
    IMPORT = "import"
    QUERY = "query"
    EXPORT = "export"
    SHARE = "share"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class CatalogEntry:
    """One entry in the catalog — a dataset, binding, chart, or dashboard."""

    id: str
    """Unique identifier for this artifact."""

    name: str
    """Human-readable name."""

    artifact_type: ArtifactType
    """What kind of artifact this is."""

    description: str = ""
    """Optional human-readable description."""

    tags: list[str] = field(default_factory=list)
    """Tags for categorization and discovery."""

    owner: str | None = field(default=None)
    """Who owns or created this artifact."""

    created_at: datetime = field(default_factory=datetime.utcnow)
    """When this artifact was first created."""

    updated_at: datetime | None = field(default=None)
    """When this artifact was last modified."""

    columns: list[str] = field(default_factory=list)
    """Column names (for datasets and bindings)."""

    column_count: int = 0
    """Number of columns (for datasets and bindings)."""

    row_count: int = 0
    """Number of rows (for datasets)."""

    source: str | None = field(default=None)
    """Source specification (file path, URI, etc.)."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "artifact_type": self.artifact_type.value,
            "description": self.description,
            "tags": list(self.tags),
            "owner": self.owner,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "columns": list(self.columns),
            "column_count": self.column_count,
            "row_count": self.row_count,
            "source": self.source,
        }


@dataclass(frozen=True)
class AuditEvent:
    """One immutable record in the audit log."""

    event_id: str
    """Unique identifier for this event."""

    timestamp: datetime = field(default_factory=datetime.utcnow)
    """When this event occurred."""

    actor: str | None = field(default=None)
    """Who performed the action (user ID, system, or agent name)."""

    action: AuditAction = field(default=AuditAction.CREATE)
    """What action was performed."""

    target_type: ArtifactType | None = field(default=None)
    """Type of the target artifact."""

    target_id: str | None = field(default=None)
    """ID of the target artifact."""

    description: str = ""
    """Human-readable description of what happened."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional structured data about the event."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "action": self.action.value,
            "target_type": self.target_type.value if self.target_type else None,
            "target_id": self.target_id,
            "description": self.description,
            "metadata": dict(self.metadata),
        }