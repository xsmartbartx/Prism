"""Connectors — read sources into raw string rows behind one contract.

Every connector returns ``list[list[str]]``: the rawest faithful form
of the source. Typing happens later, once, against the column contract.
"""

from data.connectors.base import ConnectorLimits, SourceTable
from data.connectors.delimited import read_delimited
from data.connectors.spreadsheet import list_sheets, read_sheet

__all__ = ["ConnectorLimits", "SourceTable", "list_sheets", "read_delimited", "read_sheet"]
