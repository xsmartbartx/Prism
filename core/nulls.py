"""Explicit null markers.

Spreadsheets spell "no value" many ways. Treating these tokens as null
is a declared, reviewable policy (it is recorded in the binding), not a
silent coercion.
"""

from __future__ import annotations

DEFAULT_NULL_TOKENS: frozenset[str] = frozenset(
    {"n/a", "na", "#n/a", "null", "none", "nil", "nan", "-", "--", "—", "?", "(blank)"}
)


def is_null(value: str, tokens: frozenset[str] = DEFAULT_NULL_TOKENS) -> bool:
    v = value.strip()
    return not v or v.lower() in tokens
