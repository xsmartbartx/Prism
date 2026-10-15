"""Tests for catalog models and index."""
from __future__ import annotations

from catalog import ArtifactType, AuditAction, CatalogEntry, CatalogIndex


class TestCatalogEntry:
    def test_create(self) -> None:
        e = CatalogEntry(id="t1", name="Test", artifact_type=ArtifactType.DATASET)
        assert e.id == "t1"
        assert e.name == "Test"
        assert e.artifact_type == ArtifactType.DATASET

    def test_to_dict(self) -> None:
        e = CatalogEntry(id="d1", name="Sales", artifact_type=ArtifactType.DATASET,
            description="Data", tags=["fin"], columns=["a","b"], column_count=2,
            row_count=100)
        d = e.to_dict()
        assert d["name"] == "Sales"
        assert d["column_count"] == 2


class TestCatalogIndex:
    def setup_method(self) -> None:
        self.idx = CatalogIndex()

    def test_register(self) -> None:
        e = self.idx.register("Sales", ArtifactType.DATASET,
                              description="data", tags=["fin"])
        assert len(e.id) == 16
        assert self.idx.count() == 1

    def test_register_with_columns(self) -> None:
        e = self.idx.register("DS", ArtifactType.DATASET,
                              columns=["a","b","c"], row_count=500)
        assert e.column_count == 3

    def test_get(self) -> None:
        e = self.idx.register("X", ArtifactType.BINDING)
        assert self.idx.get(e.id) is not None

    def test_get_missing(self) -> None:
        assert self.idx.get("bad") is None

    def test_update(self) -> None:
        e = self.idx.register("Old", ArtifactType.DATASET, row_count=10)
        u = self.idx.update(e.id, name="New", row_count=20)
        assert u is not None and u.name == "New" and u.row_count == 20
        fetched = self.idx.get(e.id)
        assert fetched is not None and fetched.name == "New"

    def test_update_missing(self) -> None:
        assert self.idx.update("bad", name="X") is None

    def test_delete(self) -> None:
        e = self.idx.register("D", ArtifactType.DATASET)
        assert self.idx.delete(e.id) is True
        assert self.idx.get(e.id) is None

    def test_delete_missing(self) -> None:
        assert self.idx.delete("bad") is False

    def test_count_by_type(self) -> None:
        self.idx.register("A", ArtifactType.DATASET)
        self.idx.register("B", ArtifactType.DATASET)
        self.idx.register("C", ArtifactType.BINDING)
        assert self.idx.count_by_type(ArtifactType.DATASET) == 2
        assert self.idx.count_by_type(ArtifactType.BINDING) == 1


class TestCatalogSearch:
    def setup_method(self) -> None:
        self.idx = CatalogIndex()
        self.idx.register("Sales 2024", ArtifactType.DATASET,
                          description="Annual sales", tags=["fin","sales"])
        self.idx.register("HR Roster", ArtifactType.DATASET,
                          description="Employees", tags=["hr"])
        self.idx.register("Rev Chart", ArtifactType.CHART,
                          description="Revenue", tags=["fin","rev"])
        self.idx.register("ERP Conn", ArtifactType.BINDING,
                          description="ERP source", tags=["erp","fin"])

    def test_search_name(self) -> None:
        assert len(self.idx.search("Sales")) >= 1

    def test_search_desc(self) -> None:
        assert len(self.idx.search("employee")) >= 1

    def test_search_type(self) -> None:
        assert len(self.idx.search(artifact_type=ArtifactType.CHART)) == 1

    def test_search_tag(self) -> None:
        assert len(self.idx.search(tags=["fin"])) >= 2

    def test_search_all(self) -> None:
        assert len(self.idx.search()) == 4

    def test_search_none(self) -> None:
        assert len(self.idx.search("zzzxxx")) == 0

    def test_search_limit(self) -> None:
        assert len(self.idx.search(limit=2)) == 2

    def test_list_by_type(self) -> None:
        ds = self.idx.list_by_type(ArtifactType.DATASET)
        assert len(ds) == 2
        assert ds[0].name <= ds[1].name


class TestAuditLog:
    def setup_method(self) -> None:
        self.idx = CatalogIndex()

    def test_create_logged(self) -> None:
        self.idx.register("T", ArtifactType.DATASET, actor="alice")
        log = self.idx.get_audit_log()
        assert len(log) == 1
        assert log[0].action == AuditAction.CREATE
        assert log[0].actor == "alice"

    def test_update_logged(self) -> None:
        e = self.idx.register("T", ArtifactType.DATASET)
        self.idx.update(e.id, name="U", actor="bob")
        log = self.idx.get_audit_log(target_id=e.id)
        assert len(log) == 2
        assert log[0].action == AuditAction.UPDATE
        assert log[1].action == AuditAction.CREATE

    def test_delete_logged(self) -> None:
        e = self.idx.register("T", ArtifactType.DATASET)
        self.idx.delete(e.id, actor="carol")
        log = self.idx.get_audit_log(target_id=e.id)
        assert log[0].action == AuditAction.DELETE

    def test_log_order(self) -> None:
        self.idx.register("A", ArtifactType.DATASET)
        self.idx.register("B", ArtifactType.DATASET)
        log = self.idx.get_audit_log()
        assert len(log) == 2