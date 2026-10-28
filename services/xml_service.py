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

from services.refinance_service import COLUMN_TO_XML_MAP, XML_SOURCE_ALIASES

logger = logging.getLogger("refinance_app.services.xml_service")

REQUIRED_XML_FIELDS = (
    "BRANCH_ID",
    "ACCOUNT_NUMBER",
    "ACCOUNT_TITLE",
    "BORROWER_NID",
    "LOAN_AMOUNT",
    "INTEREST_RATE",
    "OPEN_DATE",
    "CL_STATUS",
)


# ---------------------------------------------------------------------------
# Value formatting helpers
# ---------------------------------------------------------------------------

def _format_value(value: Any) -> str:
    """
    Convert a single cell value to a string suitable for XML text content.

    Rules:
    - None / NaN  → empty string (the element is still present)
    - datetime    → YYYY-MM-DD
    - date        → YYYY-MM-DD
    - Decimal     → plain decimal string (no scientific notation)
    - float       → fixed-point with up to 2 decimal places (trailing zeros stripped)
    - int         → plain integer string
    - str         → stripped string (ElementTree handles XML escaping)
    """
    if value is None or (
        pd.api.types.is_scalar(value) and pd.isna(value)
    ):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
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

    missing_sources = [
        src_upper
        for src_upper in COLUMN_TO_XML_MAP
        if src_upper not in col_upper
        and not any(alias in col_upper for alias in XML_SOURCE_ALIASES.get(src_upper, ()))
    ]

    if missing_sources:
        logger.warning(
            "Missing source columns (will produce empty XML elements): %s",
            missing_sources,
        )

    if len(missing_sources) == len(COLUMN_TO_XML_MAP):
        raise ValueError(
            "No cursor columns could be mapped to XML elements. "
            "Please verify the column mapping in refinance_service.py."
        )

    # --- Build the tree -------------------------------------------------------
    root = Element("TRANSACTION_INFO")

    for record_number, (_, row) in enumerate(df.iterrows(), start=1):
        detail = SubElement(root, "TRANS_DETAILS", {"record_number": str(record_number)})
        for src_upper, xml_name in COLUMN_TO_XML_MAP.items():
            elem = SubElement(detail, xml_name)
            actual_col = col_upper.get(src_upper)
            if actual_col is None:
                actual_col = next(
                    (
                        col_upper[alias]
                        for alias in XML_SOURCE_ALIASES.get(src_upper, ())
                        if alias in col_upper
                    ),
                    None,
                )
            elem.text = _format_value(row.get(actual_col)) if actual_col else ""

    indent(root, space="    ")

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")

    logger.info(
        "Generated XML with %d TRANS_DETAILS elements (%d chars).",
        len(df), len(xml_str),
    )
    return xml_str


def missing_required_xml_values(df: pd.DataFrame) -> list[str]:
    """Return required target fields that are blank for one or more records."""
    columns = {str(column).upper(): column for column in df.columns}
    missing: list[str] = []

    for source_name in REQUIRED_XML_FIELDS:
        actual_column = columns.get(source_name)
        if actual_column is None:
            actual_column = next(
                (
                    columns[alias]
                    for alias in XML_SOURCE_ALIASES.get(source_name, ())
                    if alias in columns
                ),
                None,
            )
        if actual_column is None:
            missing.append(COLUMN_TO_XML_MAP[source_name])
            continue

        values = df[actual_column]
        blank_values = values.isna() | values.astype("string").str.strip().eq("").fillna(False)
        if blank_values.any():
            missing.append(COLUMN_TO_XML_MAP[source_name])

    return missing


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
