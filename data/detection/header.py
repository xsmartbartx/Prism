"""Header and data region detection for CSV sources."""

from __future__ import annotations

from data.detection.profiler import classify_value, profile_rows


def detect_header(
    rows: list[list[str]],
    profiles: dict[int, ColumnProfile],
) -> tuple[int, float]:
    """Detect whether the first row is a header.

    Returns (header_row_index, confidence).
    """
    if not rows:
        return -1, 0.0

    first_row = rows[0]
    total_columns = len(first_row)
    if total_columns == 0:
        return -1, 0.0

    header_like_count = 0
    data_like_count = 0

    for col_idx in range(total_columns):
        if col_idx >= len(first_row):
            continue
        raw = first_row[col_idx].strip()
        if not raw:
            continue

        classification = classify_value(raw)

        if classification == "string":
            profile = profiles.get(col_idx)
            if profile and profile.numeric_ratio > 0.3:
                header_like_count += 1
            elif profile and profile.cardinality > 5:
                header_like_count += 0.5
            else:
                header_like_count += 0.3
        elif classification == "numeric":
            data_like_count += 1
        elif classification == "date":
            data_like_count += 0.5
        elif classification == "boolean":
            data_like_count += 0.5

    # Check if first row differs from second row
    has_data_different_from_header = 0.0
    if len(rows) > 1 and total_columns > 0:
        second_row = rows[1]
        same_type_count = 0
        for col_idx in range(min(total_columns, min(len(second_row), len(first_row)))):
            c1 = classify_value(first_row[col_idx])
            c2 = classify_value(second_row[col_idx])
            if c1 == c2:
                same_type_count += 1
        similarity = same_type_count / total_columns
        if similarity > 0.6:
            has_data_different_from_header = -0.2
        elif similarity < 0.3:
            has_data_different_from_header = 0.3

    header_score = (header_like_count / total_columns) if total_columns > 0 else 0.0
    header_score += has_data_different_from_header
    header_score = max(0.0, min(1.0, header_score))

    data_score = (data_like_count / total_columns) if total_columns > 0 else 0.0
    if data_score > 0.5:
        header_score = max(0.0, header_score - 0.5)

    if header_score >= 0.5:
        return 0, header_score
    return -1, 1.0 - header_score


def detect_data_region(
    rows: list[list[str]],
    header_row_index: int,
) -> tuple[int, int | None]:
    """Detect the data region start and end rows."""
    if not rows:
        return 0, None

    start_row = max(header_row_index + 1, 0) if header_row_index >= 0 else 0

    while start_row < len(rows):
        row = rows[start_row]
        if [c for c in row if c.strip()]:
            break
        start_row += 1

    end_row = None
    for i in range(len(rows) - 1, start_row - 1, -1):
        row = rows[i]
        if len([c for c in row if c.strip()]) >= 1:
            end_row = i
            break

    return start_row, end_row