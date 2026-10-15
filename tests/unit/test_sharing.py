"""Tests for the sharing module — share tokens, validation, revocation."""
from __future__ import annotations

from datetime import datetime, timedelta

from catalog import ArtifactType, AuditAction, ShareManager, ShareToken


class TestShareToken:
    def test_create_token(self) -> None:
        t = ShareToken(token_id="tok1", artifact_id="art1", artifact_type=ArtifactType.CHART)
        assert t.token_id == "tok1"
        assert t.artifact_id == "art1"
        assert not t.is_revoked

    def test_is_valid_default(self) -> None:
        t = ShareToken(token_id="t1", artifact_id="a1", artifact_type=ArtifactType.CHART)
        assert t.is_valid() is True

    def test_is_valid_revoked(self) -> None:
        t = ShareToken(token_id="t1", artifact_id="a1", artifact_type=ArtifactType.CHART, is_revoked=True)
        assert t.is_valid() is False

    def test_is_valid_expired(self) -> None:
        past = datetime.utcnow() - timedelta(hours=1)
        t = ShareToken(token_id="t1", artifact_id="a1", artifact_type=ArtifactType.CHART, expires_at=past)
        assert t.is_valid() is False

    def test_is_valid_uses_exhausted(self) -> None:
        t = ShareToken(token_id="t1", artifact_id="a1", artifact_type=ArtifactType.CHART, max_uses=3, use_count=3)
        assert t.is_valid() is False

    def test_is_valid_uses_remaining(self) -> None:
        t = ShareToken(token_id="t1", artifact_id="a1", artifact_type=ArtifactType.CHART, max_uses=5, use_count=2)
        assert t.is_valid() is True

    def test_to_dict(self) -> None:
        t = ShareToken(token_id="t1", artifact_id="a1", artifact_type=ArtifactType.CHART, created_by="alice")
        d = t.to_dict()
        assert d["token_id"] == "t1"
        assert d["created_by"] == "alice"


class TestShareManager:
    def setup_method(self) -> None:
        self.audit_events: list[tuple] = []
        def audit_cb(action, ttype, tid, actor, desc):
            self.audit_events.append((action, ttype, tid, actor, desc))
        self.mgr = ShareManager(audit_callback=audit_cb)

    def test_create_share(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART, created_by="alice")
        assert token.artifact_id == "chart-1"
        assert token.artifact_type == ArtifactType.CHART
        assert len(token.token_id) == 16
        assert len(token.signature) > 0

    def test_create_share_requires_id(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            self.mgr.create_share("", ArtifactType.CHART)

    def test_validate_token(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART)
        validated = self.mgr.validate_token(token.token_id)
        assert validated is not None
        assert validated.token_id == token.token_id

    def test_validate_token_with_signature(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART)
        validated = self.mgr.validate_token(token.token_id, signature=token.signature)
        assert validated is not None

    def test_validate_bad_signature(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART)
        validated = self.mgr.validate_token(token.token_id, signature="bad-sig")
        assert validated is None

    def test_validate_nonexistent(self) -> None:
        assert self.mgr.validate_token("no-such-token") is None

    def test_validate_expired_token(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART, expires_in_hours=-1)
        validated = self.mgr.validate_token(token.token_id)
        assert validated is None

    def test_revoke_share(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART)
        revoked = self.mgr.revoke_share(token.token_id, revoked_by="bob")
        assert revoked is not None
        assert revoked.is_revoked is True
        # Validate after revoke
        assert self.mgr.validate_token(token.token_id) is None

    def test_revoke_nonexistent(self) -> None:
        assert self.mgr.revoke_share("bad-id") is None

    def test_use_token(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART, max_uses=3)
        assert self.mgr.use_token(token.token_id) is True
        assert self.mgr.use_token(token.token_id) is True
        assert self.mgr.use_token(token.token_id) is True
        # Fourth use should fail
        assert self.mgr.use_token(token.token_id) is False

    def test_use_token_unlimited(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART)
        for _ in range(10):
            assert self.mgr.use_token(token.token_id) is True

    def test_list_shares(self) -> None:
        self.mgr.create_share("chart-1", ArtifactType.CHART, created_by="alice")
        self.mgr.create_share("chart-1", ArtifactType.CHART, created_by="bob")
        self.mgr.create_share("chart-2", ArtifactType.CHART)
        shares = self.mgr.list_shares("chart-1")
        assert len(shares) == 2
        shares2 = self.mgr.list_shares("chart-2")
        assert len(shares2) == 1

    def test_audit_on_create(self) -> None:
        self.mgr.create_share("chart-1", ArtifactType.CHART, created_by="alice")
        assert len(self.audit_events) == 1
        action, _, _, actor, _ = self.audit_events[0]
        assert action == AuditAction.SHARE
        assert actor == "alice"

    def test_audit_on_revoke(self) -> None:
        token = self.mgr.create_share("chart-1", ArtifactType.CHART)
        self.mgr.revoke_share(token.token_id, revoked_by="bob")
        assert len(self.audit_events) == 2
        _, _, _, actor, _ = self.audit_events[1]
        assert actor == "bob"