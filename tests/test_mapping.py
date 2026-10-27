"""
Tests for column mapping — verifies the source-to-target field mapping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.refinance_service import (
    COLUMN_TO_XML_MAP,
    validate_column_mapping,
    get_xml_field_names,
)


# ===================================================================
# Mapping integrity
# ===================================================================

class TestColumnMapping:
    def test_mapping_not_empty(self):
        assert len(COLUMN_TO_XML_MAP) > 0

    def test_all_xml_names_unique(self):
        xml_names = list(COLUMN_TO_XML_MAP.values())
        assert len(xml_names) == len(set(xml_names)), "Duplicate XML element names"

    def test_all_source_names_unique(self):
        src_names = list(COLUMN_TO_XML_MAP.keys())
        assert len(src_names) == len(set(src_names)), "Duplicate source column names"

    def test_expected_xml_fields_count(self):
        """The mapping contains all 44 fields currently defined by the service."""
        assert len(COLUMN_TO_XML_MAP) == 44

    def test_specific_mappings(self):
        """Spot-check a few critical mappings."""
        assert COLUMN_TO_XML_MAP["BRANCH_ID"] == "Pbranch_id"
        assert COLUMN_TO_XML_MAP["ACCOUNT_NUMBER"] == "Paccount_number"
        assert COLUMN_TO_XML_MAP["LOAN_AMOUNT"] == "Ploan_amount"
        assert COLUMN_TO_XML_MAP["INTEREST_RATE"] == "Pinterest_Rate"
        assert COLUMN_TO_XML_MAP["OPEN_DATE"] == "Popen_date"
        assert COLUMN_TO_XML_MAP["REMARKS"] == "PRemarks"

    def test_get_xml_field_names(self):
        names = get_xml_field_names()
        assert isinstance(names, list)
        assert len(names) == 44
        assert "Pbranch_id" in names


# ===================================================================
# validate_column_mapping
# ===================================================================

class TestValidateColumnMapping:
    def test_all_columns_present(self, sample_df):
        mapped, missing = validate_column_mapping(sample_df)
        assert len(missing) == 0
        assert len(mapped) == 44

    def test_missing_columns_detected(self):
        df = pd.DataFrame({"BRANCH_ID": ["0101"], "ACCOUNT_NUMBER": ["001"]})
        mapped, missing = validate_column_mapping(df)
        assert "BRANCH_ID" in mapped
        assert "ACCOUNT_NUMBER" in mapped
        assert len(missing) == 42  # 44 - 2

    def test_case_insensitive_matching(self):
        df = pd.DataFrame({"branch_id": ["0101"], "account_number": ["001"]})
        mapped, missing = validate_column_mapping(df)
        assert "BRANCH_ID" in mapped
        assert "ACCOUNT_NUMBER" in mapped

    def test_empty_df(self, empty_df):
        mapped, missing = validate_column_mapping(empty_df)
        # Columns are present even though rows are empty
        assert len(missing) == 0

    def test_no_matching_columns(self):
        df = pd.DataFrame({"UNRELATED_COL": [1]})
        mapped, missing = validate_column_mapping(df)
        assert len(mapped) == 0
        assert len(missing) == 44
