"""Service container: one instance of each service per process."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from data.connectors.link import Fetched, fetch
from data.connectors.postgres import TableInfo, list_tables, read_table
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
    # Network access to sources; tests replace these with fakes.
    link_fetch: Callable[..., Fetched] = fetch  # data.connectors.link.fetch
    db_read: Callable[..., Fetched] = read_table  # data.connectors.postgres.read_table
    db_tables: Callable[..., list[TableInfo]] = list_tables

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
