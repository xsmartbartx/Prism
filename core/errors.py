"""Error taxonomy for the Prism platform.

All Prism exceptions inherit from PrismError. This makes it possible
for higher layers to catch any Prism-raised exception without catching
Python builtins.
"""


class PrismError(Exception):
    """Base exception for all Prism platform errors."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code or self.__class__.__name__
        super().__init__(message)


class TypeMismatchError(PrismError):
    """Raised when a value does not match the expected column type."""


class ParseError(PrismError):
    """Raised when a value cannot be parsed as the expected type."""


class ValidationError(PrismError):
    """Raised when an artifact fails schema or policy validation."""


class BindingError(PrismError):
    """Raised when a source binding is invalid or inconsistent."""


class ConnectorError(PrismError):
    """Raised when a connector fails to read from a source."""


class SandboxError(PrismError):
    """Raised when the parse sandbox detects a violation."""


class PolicyViolation(PrismError):
    """Raised when a principal tries to perform an unauthorized action."""


class DriftDetected(PrismError):
    """Raised when a source's shape no longer matches its binding."""