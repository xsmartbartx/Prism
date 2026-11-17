"""Connectors — read sources into raw string rows behind one contract.

Every connector returns ``list[list[str]]``: the rawest faithful form
of the source. Typing happens later, once, against the column contract.
"""

from data.connectors.base import ConnectorLimits, SourceTable
from data.connectors.delimited import read_delimited
from data.connectors.parquet import is_parquet, read_parquet
from data.connectors.spreadsheet import list_sheets, read_sheet
from data.connectors.sqlite import is_sqlite, list_tables, read_table

__all__ = [
    "ConnectorLimits",
    "SourceTable",
    "is_parquet",
    "is_sqlite",
    "list_sheets",
    "list_tables",
    "read_delimited",
    "read_parquet",
    "read_sheet",
    "read_table",
]
