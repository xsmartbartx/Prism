"""CSV structure detector — finds tables inside CSV files.

Strategy:
  1. Read the first N rows (sample)
  2. Profile each column for data types
  3. Determine if the first row is a header or data
  4. Locate the start and end of the data region
  5. Assign a confidence score
"""

from __future__ import annotations

import csv
import io

from core.detection import DetectedStructure, DetectionConfidence, _score_to_enum
from data.detection.profiler import classify_value, profile_rows
from data.detection.header import detect_header, detect_data_region

_SAMPLE_SIZE = 100


def _calculate_confidence(
    rows: list[list[str]],
    header_row_index: int,
    header_confidence: float,
    data_start_row: int,
    column_count: int,
) -> float:
    """Calculate overall detection confidence."""
    if column_count >= 2:
        consistent_cols = 0
        for row in rows[data_start_row:]:
            if len(row) == column_count:
                consistent_cols += 1
        data_rows = max(len(rows) - data_start_row, 1)
        consistency_bonus = consistent_cols / data_rows * 0.1

    overall_confidence = min(1.0, header_confidence + consistency_bonus)

    # Penalize if header and data are too similar
    if header_row_index >= 0 and len(rows) > header_row_index + 1:
        header_row = rows[header_row_index] if header_row_index < len(rows) else []
        data_rows_for_compare = rows[header_row_index + 1: header_row_index + 3]
        if header_row and data_rows_for_compare:
            # Compare header types against first data row
            header_types = [classify_value(c) for c in header_row]
            data_type_matches = []
            for data_row in data_rows_for_compare:
                if data_row:
                    data_types = [classify_value(c) for c in data_row]
                    match_count = sum(1 for h, d in zip(header_types, data_types) if h == d)
                    data_type_matches.append(match_count / max(len(header_types), 1))
            avg_match = sum(data_type_matches) / max(len(data_type_matches), 1)
            if avg_match > 0.8:
                overall_confidence = max(0.0, overall_confidence - 0.1)

    return round(overall_confidence, 4)


def detect_structure(
    content: str,
    max_rows: int = _SAMPLE_SIZE,
) -> DetectedStructure:
    """Detect the structure of a CSV-formatted string.

    Args:
        content: The CSV content as a string.
        max_rows: Maximum number of rows to sample for detection.

    Returns:
        A DetectedStructure with the best-guess layout.
    """
    reader = csv.reader(io.StringIO(content))
    rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if i >= max_rows:
            break
        rows.append(row)

    if not rows:
        return DetectedStructure(
            header_row_index=-1,
            data_start_row=0,
            column_count=0,
            confidence=DetectionConfidence.NONE,
            confidence_score=0.0,
        )

    # Skip leading blank rows before structure detection
    first_data_idx = 0
    while first_data_idx < len(rows):
        row = rows[first_data_idx]
        if [c for c in row if c.strip()]:
            break
        first_data_idx += 1

    # Work with non-blank rows for detection
    non_blank_rows = rows[first_data_idx:]
    if not non_blank_rows:
        return DetectedStructure(
            header_row_index=-1,
            data_start_row=len(rows),
            column_count=0,
            confidence=DetectionConfidence.NONE,
            confidence_score=0.0,
        )

    max_cols = max(len(row) for row in non_blank_rows)
    column_count = max_cols
    profiles = profile_rows(non_blank_rows)

    header_row_index, header_confidence = detect_header(non_blank_rows, profiles)

    # Adjust header/data row indices to account for leading blank rows
    if header_row_index >= 0:
        header_row_index += first_data_idx
    data_start_row, data_end_row = detect_data_region(rows, header_row_index)

    # Build column names
    column_names: list[str] = []
    if header_row_index >= 0 and header_row_index < len(rows):
        header_row = rows[header_row_index]
        for col_idx in range(column_count):
            name = (
                header_row[col_idx]
                if col_idx < len(header_row)
                else f"column_{col_idx}"
            )
            column_names.append(name)
    else:
        column_names = [f"column_{i}" for i in range(column_count)]

    overall_confidence = _calculate_confidence(
        non_blank_rows, max(header_row_index - first_data_idx, 0) if header_row_index >= 0 else header_row_index,
        header_confidence, data_start_row - first_data_idx, column_count
    )

    return DetectedStructure(
        header_row_index=header_row_index,
        data_start_row=data_start_row,
        data_end_row=data_end_row,
        column_count=column_count,
        column_names=column_names,
        confidence=_score_to_enum(overall_confidence),
        confidence_score=overall_confidence,
    )