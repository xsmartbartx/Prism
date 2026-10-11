"""Tests for CSV structure detection — header detection, data regions, edge cases."""
from __future__ import annotations

from core.detection import DetectionConfidence
from data.detection.csv import detect_structure


class TestCsvDetectionNoHeader:
    def test_all_numeric_no_header(self) -> None:
        csv_data = "100,200,300\n101,201,301\n102,202,302"
        result = detect_structure(csv_data)
        assert result.header_row_index == -1
        assert result.data_start_row == 0
        assert result.column_count == 3

    def test_mixed_types_no_header(self) -> None:
        csv_data = "Alice,30,95.5\nBob,25,88.0\nCharlie,35,92.3"
        result = detect_structure(csv_data)
        assert result.column_count == 3


class TestCsvDetectionWithHeader:
    def test_simple_header(self) -> None:
        csv_data = "name,age,score\nAlice,30,95.5\nBob,25,88.0\nCharlie,35,92.3"
        result = detect_structure(csv_data)
        assert result.header_row_index == 0
        assert result.data_start_row == 1
        assert result.column_count == 3
        assert result.column_names == ["name", "age", "score"]

    def test_header_with_spaces(self) -> None:
        csv_data = "Product Name, Unit Price, Quantity\nWidget A,10.50,100\nWidget B,25.00,50"
        result = detect_structure(csv_data)
        assert result.header_row_index == 0
        assert result.data_start_row == 1
        assert result.column_names == ["Product Name", " Unit Price", " Quantity"]

    def test_header_high_confidence(self) -> None:
        csv_data = "department,revenue,cost\nSales,100000,45000\nEngineering,200000,120000"
        result = detect_structure(csv_data)
        assert result.header_row_index == 0
        assert result.confidence_score >= 0.7

    def test_realistic_sales_data(self) -> None:
        csv_data = (
            "Date,Product,Region,Units,Revenue\n"
            "2026-01-01,Widget A,North,100,1000.00\n"
            "2026-01-02,Widget B,South,200,2500.00\n"
            "2026-01-03,Widget A,East,150,1500.00\n"
            "2026-01-04,Widget C,West,75,1125.00"
        )
        result = detect_structure(csv_data)
        assert result.header_row_index == 0
        assert result.column_count == 5
        assert result.column_names == ["Date", "Product", "Region", "Units", "Revenue"]
        assert result.data_start_row == 1
        assert result.data_end_row == 4
        assert result.confidence_score >= 0.7


class TestCsvDetectionEdgeCases:
    def test_empty_content(self) -> None:
        result = detect_structure("")
        assert result.column_count == 0
        assert result.confidence == DetectionConfidence.NONE

    def test_single_row(self) -> None:
        csv_data = "just,one,row"
        result = detect_structure(csv_data)
        assert result.column_count == 3

    def test_blank_rows_at_top(self) -> None:
        csv_data = "\n\n\nname,value\nfoo,1\nbar,2"
        result = detect_structure(csv_data)
        assert result.header_row_index == 3
        assert result.data_start_row == 4
        assert result.column_names == ["name", "value"]

    def test_trailing_blank_rows(self) -> None:
        csv_data = "name,value\nfoo,1\nbar,2\n\n\n"
        result = detect_structure(csv_data)
        assert result.header_row_index == 0
        assert result.data_start_row == 1
        assert result.data_end_row == 2

    def test_inconsistent_column_count(self) -> None:
        csv_data = "name,age\nAlice,30,extra\nBob,25\nCharlie,35"
        result = detect_structure(csv_data)
        assert result.column_count == 3

    def test_max_rows_limit(self) -> None:
        lines = ["name,value"] + [f"row{i},{i}" for i in range(200)]
        csv_data = "\n".join(lines)
        result = detect_structure(csv_data, max_rows=50)
        assert result.header_row_index == 0
        assert result.column_count == 2