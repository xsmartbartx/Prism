"""Base type definitions for the Prism type system.

Every column in a Prism dataset has a DataType that determines how
values are parsed, validated, formatted, and compared. DataRole
describes the semantic role a column plays in analysis.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class DataRole(Enum):
    """Semantic role of a column in analysis.

    This is not the same as the data type. A string column can be a
    dimension (e.g., product name) or an identifier (e.g., order ID).
    """

    DIMENSION = "dimension"
    MEASURE = "measure"
    IDENTIFIER = "identifier"
    TIME = "time"
    GEOGRAPHY = "geography"
    METADATA = "metadata"


class DataType(ABC):
    """Abstract base for all Prism data types.

    A DataType provides:
      - parse: convert a string to the typed value
      - format: convert a typed value to a string (with locale)
      - validate: check if a value is of this type
      - eq / lt / gt: comparison operations
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Canonical, short name of this type (e.g., 'integer', 'float')."""
        ...

    @abstractmethod
    def parse(self, value: str) -> Any:
        """Parse a string into this type's Python representation.

        Raises ParseError if parsing fails.
        """
        ...

    def format(self, value: Any) -> str:
        """Format a typed value as a string for display.

        Defaults to str(); locale-aware subclasses override this.
        """
        return str(value)

    @abstractmethod
    def validate(self, value: Any) -> bool:
        """Return True if value is an instance of this type."""
        ...

    def eq(self, a: Any, b: Any) -> bool:
        """Compare two values for equality under this type's semantics."""
        return a == b

    def lt(self, a: Any, b: Any) -> bool:
        """Return True if a < b under this type's sort order."""
        return a < b

    def gt(self, a: Any, b: Any) -> bool:
        """Return True if a > b under this type's sort order."""
        return a > b