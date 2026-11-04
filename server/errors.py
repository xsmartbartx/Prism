"""Application-level errors, mapped to HTTP status codes by the API layer."""

from __future__ import annotations

from core.errors import PrismError


class NotFound(PrismError):
    """The artifact does not exist or is not visible to the caller (404)."""


class Forbidden(PrismError):
    """The caller is authenticated but lacks the required role (403)."""


class Unauthorized(PrismError):
    """No valid credentials were presented (401)."""


class Conflict(PrismError):
    """The request conflicts with current state (409)."""


class LimitExceeded(PrismError):
    """A plan limit would be exceeded; upgrade the license (402)."""


class BadRequest(PrismError):
    """The request is malformed or semantically invalid (400)."""


class TooManyRequests(PrismError):
    """Rate limit hit (429)."""
