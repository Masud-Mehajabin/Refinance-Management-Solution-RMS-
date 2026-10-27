"""
Tests for xml_service — XML generation and validation.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.xml_service import generate_xml, validate_xml, _format_value
from services.refinance_service import COLUMN_TO_XML_MAP


# ===================================================================
# _format_value
# ===================================================================

class TestFormatValue:
    def test_none(self):
        assert _format_value(None) == ""

    def test_nan(self):
        assert _format_value(float("nan")) == ""

    def test_datetime(self):
        dt = datetime(2024, 3, 15, 10, 30, 0)
        assert _format_value(dt) == "15032024"

    def test_integer(self):
        assert _format_value(42) == "42"

    def test_zero(self):
        assert _format_value(0) == "0"

    def test_zero_float(self):
        assert _format_value(0.0) == "0"

    def test_meaningful_zero_int(self):
        """Meaningful zero values must be preserved."""
        assert _format_value(0) == "0"

    def test_float_with_decimals(self):
        assert _format_value(1234.56) == "1234.56"

    def test_float_whole_number(self):
        assert _format_value(1000.0) == "1000"

    def test_string_stripped(self):
        assert _format_value("  hello  ") == "hello"

    def test_unicode_passthrough(self):
        assert _format_value("ঢাকা") == "ঢাকা"


# ===================================================================
# generate_xml
# ===================================================================

class TestGenerateXml:
    def test_single_record(self, sample_df):
        xml = generate_xml(sample_df)
        root = fromstring(xml)
        assert root.tag == "TRANSACTION_INFO"
        details = root.findall("TRANS_DETAILS")
        assert len(details) == 1

    def test_multiple_records(self, multi_row_df):
        xml = generate_xml(multi_row_df)
        root = fromstring(xml)
        details = root.findall("TRANS_DETAILS")
        assert len(details) == 3

    def test_correct_xml_element_names(self, sample_df):
        """Every TRANS_DETAILS child must use the XML names from the mapping."""
        xml = generate_xml(sample_df)
        root = fromstring(xml)
        detail = root.find("TRANS_DETAILS")
        child_tags = [child.tag for child in detail]
        expected_tags = list(COLUMN_TO_XML_MAP.values())
        assert child_tags == expected_tags

    def test_null_values_produce_empty_elements(self, null_heavy_df):
        """NULL source values must result in present-but-empty XML elements."""
        xml = generate_xml(null_heavy_df)
        root = fromstring(xml)
        detail = root.find("TRANS_DETAILS")
        # Account number is set; most others are None
        acct = detail.find("Paccount_number")
        assert acct is not None
        assert acct.text == "01010001"
        # A None column should be empty string (or None text)
        name = detail.find("Pborrower_name")
        assert name is not None
        assert (name.text or "") == ""

    def test_unicode_content(self, unicode_df):
        xml = generate_xml(unicode_df)
        root = fromstring(xml)
        detail = root.find("TRANS_DETAILS")
        name = detail.find("Pborrower_name")
        assert name.text == "মোহাম্মদ আবদুল্লাহ"

    def test_xml_special_characters_escaped(self, sample_df):
        """Ampersands, angle brackets etc. must be properly escaped."""
        xml = generate_xml(sample_df)
        # The raw XML string must NOT contain bare '&' or '<' in text
        # (they would cause a parse error). If fromstring succeeds, escaping is correct.
        root = fromstring(xml)
        detail = root.find("TRANS_DETAILS")
        addr = detail.find("PBusiness_Address")
        assert "&" in addr.text  # the unescaped ampersand from the source
        purpose = detail.find("PLoan_purpose")
        assert "<" in purpose.text  # the unescaped angle bracket from the source

    def test_date_formatting(self, sample_df):
        xml = generate_xml(sample_df)
        root = fromstring(xml)
        detail = root.find("TRANS_DETAILS")
        open_date = detail.find("Popen_date")
        assert open_date.text == "15012024"

    def test_each_record_has_the_same_ordered_fields_and_its_own_values(self, multi_row_df):
        root = fromstring(generate_xml(multi_row_df))
        details = root.findall("TRANS_DETAILS")
        expected_tags = list(COLUMN_TO_XML_MAP.values())

        assert len(details) == len(multi_row_df)
        assert [detail.get("record_number") for detail in details] == ["1", "2", "3"]
        for detail in details:
            assert [child.tag for child in detail] == expected_tags
        assert [detail.findtext("Paccount_number") for detail in details] == [
            str(value) for value in multi_row_df["ACCOUNT_NUMBER"]
        ]

    def test_numeric_formatting(self, sample_df):
        xml = generate_xml(sample_df)
        root = fromstring(xml)
        detail = root.find("TRANS_DETAILS")
        rate = detail.find("Pinterest_Rate")
        assert rate.text == "9.5"

    def test_empty_dataframe_raises(self, empty_df):
        with pytest.raises(ValueError, match="empty"):
            generate_xml(empty_df)

    def test_none_dataframe_raises(self):
        with pytest.raises(ValueError, match="empty"):
            generate_xml(None)

    def test_xml_declaration_present(self, sample_df):
        xml = generate_xml(sample_df)
        assert xml.startswith("<?xml")

    def test_utf8_encoding_declared(self, sample_df):
        xml = generate_xml(sample_df)
        assert 'encoding="UTF-8"' in xml


# ===================================================================
# validate_xml
# ===================================================================

class TestValidateXml:
    def test_valid_xml(self, sample_df):
        xml = generate_xml(sample_df)
        is_valid, msg = validate_xml(xml)
        assert is_valid is True
        assert "1 TRANS_DETAILS" in msg

    def test_malformed_xml(self):
        is_valid, msg = validate_xml("<broken><xml")
        assert is_valid is False
        assert "malformed" in msg.lower()

    def test_wrong_root_element(self):
        xml = "<WRONG_ROOT><TRANS_DETAILS></TRANS_DETAILS></WRONG_ROOT>"
        is_valid, msg = validate_xml(xml)
        assert is_valid is False
        assert "WRONG_ROOT" in msg

    def test_no_trans_details(self):
        xml = "<TRANSACTION_INFO></TRANSACTION_INFO>"
        is_valid, msg = validate_xml(xml)
        assert is_valid is False
        assert "no trans_details" in msg.lower()

    def test_multiple_trans_details(self, multi_row_df):
        xml = generate_xml(multi_row_df)
        is_valid, msg = validate_xml(xml)
        assert is_valid is True
        assert "3 TRANS_DETAILS" in msg
