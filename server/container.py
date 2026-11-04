"""Service container: one instance of each service per process."""

from __future__ import annotations

from dataclasses import dataclass

from data.load.store import DatasetStore
from server.config import Settings
from server.db import Database
from server.services.artifacts import ArtifactService
from server.services.auth import AuthService
from server.services.imports import ImportService
from server.services.queries import QueryService


@dataclass
class Services:
    settings: Settings
    db: Database
    store: DatasetStore
    auth: AuthService
    imports: ImportService
    queries: QueryService
    artifacts: ArtifactService
    secret_key: str

    @classmethod
    def build(cls, settings: Settings, db: Database | None = None) -> Services:
        settings.ensure_dirs()
        database = db or Database(settings.resolved_database_url)
        store = DatasetStore(settings.datasets_dir)
        queries = QueryService(settings)
        return cls(
            settings=settings,
            db=database,
            store=store,
            auth=AuthService(settings.session_hours, settings.login_rate_limit),
            imports=ImportService(settings, store),
            queries=queries,
            artifacts=ArtifactService(store, queries),
            secret_key=settings.resolved_secret_key(),
        )
