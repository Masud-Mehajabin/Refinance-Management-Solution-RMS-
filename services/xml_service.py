"""
XML Service — generates validated XML for refinance batch submission.

Produces the TRANSACTION_INFO / TRANS_DETAILS hierarchy expected by
PKG_MGBL_REFINANCE.REFINANCE_MASTER_INFO_I.

Uses xml.etree.ElementTree (standard library) with proper escaping.
Never concatenates raw, unescaped strings into XML.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element, SubElement, indent, tostring

import pandas as pd

from services.refinance_service import COLUMN_TO_XML_MAP

logger = logging.getLogger("refinance_app.services.xml_service")


# ---------------------------------------------------------------------------
# Value formatting helpers
# ---------------------------------------------------------------------------

def _format_value(value: Any) -> str:
    """
    Convert a single cell value to a string suitable for XML text content.

    Rules:
    - None / NaN  → empty string (the element is still present)
    - datetime    → DD-MON-YYYY (Oracle-compatible)
    - date        → DD-MON-YYYY
    - Decimal     → plain decimal string (no scientific notation)
    - float       → fixed-point with up to 2 decimal places (trailing zeros stripped)
    - int         → plain integer string
    - str         → stripped string (ElementTree handles XML escaping)
    """
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%b-%Y").upper()
    if isinstance(value, date):
        return value.strftime("%d-%b-%Y").upper()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        # Preserve meaningful zero values; strip unnecessary trailing zeros
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


# ---------------------------------------------------------------------------
# XML Generation
# ---------------------------------------------------------------------------

def generate_xml(df: pd.DataFrame) -> str:
    """
    Generate a UTF-8 XML string from a DataFrame of refinance records.

    Parameters
    ----------
    df : pd.DataFrame
        Records previously retrieved by GET_REFINANCE_DETAILS.

    Returns
    -------
    str
        The complete XML document as a string.

    Raises
    ------
    ValueError
        If the DataFrame is empty or required column mapping fails.
    """
    if df is None or df.empty:
        raise ValueError("Cannot generate XML from an empty dataset.")

    # Build an upper-case lookup from actual columns
    col_upper = {c.upper(): c for c in df.columns}

    # Pre-check: which mapped source columns are actually present?
    available_mappings: list[tuple[str, str]] = []
    missing_sources: list[str] = []

    for src_upper, xml_name in COLUMN_TO_XML_MAP.items():
        if src_upper in col_upper:
            available_mappings.append((col_upper[src_upper], xml_name))
        else:
            missing_sources.append(src_upper)

    if missing_sources:
        logger.warning(
            "Missing source columns (will produce empty XML elements): %s",
            missing_sources,
        )

    if not available_mappings:
        raise ValueError(
            "No cursor columns could be mapped to XML elements. "
            "Please verify the column mapping in refinance_service.py."
        )

    # --- Build the tree -------------------------------------------------------
    root = Element("TRANSACTION_INFO")

    for _, row in df.iterrows():
        detail = SubElement(root, "TRANS_DETAILS")
        for actual_col, xml_name in available_mappings:
            elem = SubElement(detail, xml_name)
            elem.text = _format_value(row.get(actual_col))
        # Also add empty elements for missing source columns so the
        # receiving procedure gets every expected field.
        for src_upper in missing_sources:
            xml_name = COLUMN_TO_XML_MAP[src_upper]
            elem = SubElement(detail, xml_name)
            elem.text = ""

    indent(root, space="    ")

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")

    logger.info(
        "Generated XML with %d TRANS_DETAILS elements (%d chars).",
        len(df), len(xml_str),
    )
    return xml_str


def validate_xml(xml_str: str) -> tuple[bool, str]:
    """
    Perform basic well-formedness validation on the generated XML.

    Returns
    -------
    (is_valid, message)
    """
    from xml.etree.ElementTree import fromstring, ParseError

    try:
        root = fromstring(xml_str)
    except ParseError as exc:
        return False, f"XML is malformed: {exc}"

    if root.tag != "TRANSACTION_INFO":
        return False, f"Root element is '{root.tag}', expected 'TRANSACTION_INFO'."

    details = root.findall("TRANS_DETAILS")
    if not details:
        return False, "XML contains no TRANS_DETAILS elements."

    return True, f"XML is well-formed with {len(details)} TRANS_DETAILS element(s)."
