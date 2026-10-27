"""
conftest.py — shared fixtures for all tests.

Provides sample DataFrames that simulate cursor output from
GET_REFINANCE_DETAILS without requiring a live Oracle connection.
"""

from __future__ import annotations

import sys
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import pytest

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Realistic sample data (fictional — no real bank data)
# ---------------------------------------------------------------------------

SAMPLE_COLUMNS = [
    "BRANCH_ID", "ACCOUNT_NUMBER", "CUSTOMER_ID", "GROUP_ID",
    "ACCOUNT_TITLE", "BORROWER_NAME", "BORROWER_PHONE", "BORROWER_NID",
    "BUSINESS_ADDRESS", "DISTRICT_NM", "SECTOR", "SUBSECTOR",
    "PRODUCT_OF_ENTERPRISE", "ESTABLISHED_YEAR", "ESTABLISHED_STRUCTURE",
    "OWNERSHIP_GENDER", "TYPE_OF_SME", "TRADE_LICENSE_NO",
    "PAIDUP_CAPITAL", "NET_WORTH", "FIXED_ASSET_VALUE", "ANNUAL_SALES",
    "NET_PROFIT_AFTER_TAX", "NO_OF_EMPLOYEE", "NO_OF_EMPLOYEE_M",
    "NO_OF_EMPLOYEE_F", "LOAN_AMOUNT", "INTEREST_RATE",
    "OPEN_DATE", "DISBURSEMENT_DATE", "GRACE_PERIOD", "EXPIRY_DATE",
    "TENURE", "LOAN_PURPOSE", "LOAN_SCHEME", "SCHEME_SHORT_CODE",
    "FUND_CATEGORY", "OUTSTANDING_AMOUNT", "PRINCIPAL_AMOUNT",
    "INTEREST_AMOUNT", "TOTAL_INSTALLMENT", "CL_STATUS",
    "REPAY_DATE", "REMARKS",
]


def _make_row(idx: int = 1) -> dict:
    return {
        "BRANCH_ID": "0101",
        "ACCOUNT_NUMBER": f"010100{idx:04d}",
        "CUSTOMER_ID": f"CUST{idx:04d}",
        "GROUP_ID": f"GRP{idx:02d}",
        "ACCOUNT_TITLE": f"Test Account {idx}",
        "BORROWER_NAME": f"জনাব পরীক্ষা {idx}",  # Bengali Unicode
        "BORROWER_PHONE": f"0171000{idx:04d}",
        "BORROWER_NID": f"19850101{idx:06d}",
        "BUSINESS_ADDRESS": f"Test Address {idx}, Dhaka & Co.",  # '&' — XML special char
        "DISTRICT_NM": "ঢাকা",
        "SECTOR": "Manufacturing",
        "SUBSECTOR": "Garments",
        "PRODUCT_OF_ENTERPRISE": "Ready-made Garments",
        "ESTABLISHED_YEAR": 2015 + idx,
        "ESTABLISHED_STRUCTURE": "Proprietorship",
        "OWNERSHIP_GENDER": "Male",
        "TYPE_OF_SME": "Small",
        "TRADE_LICENSE_NO": f"TL-{idx:06d}",
        "PAIDUP_CAPITAL": 500000.00 * idx,
        "NET_WORTH": 750000.00 * idx,
        "FIXED_ASSET_VALUE": 300000.00 * idx,
        "ANNUAL_SALES": 2000000.00 * idx,
        "NET_PROFIT_AFTER_TAX": 150000.00 * idx,
        "NO_OF_EMPLOYEE": 10 + idx,
        "NO_OF_EMPLOYEE_M": 7 + idx,
        "NO_OF_EMPLOYEE_F": 3,
        "LOAN_AMOUNT": 1000000.00 * idx,
        "INTEREST_RATE": 9.5,
        "OPEN_DATE": datetime(2024, 1, 15),
        "DISBURSEMENT_DATE": datetime(2024, 2, 1),
        "GRACE_PERIOD": 3,
        "EXPIRY_DATE": datetime(2029, 1, 15),
        "TENURE": 60,
        "LOAN_PURPOSE": "Working Capital <Expansion>",  # '<' and '>' — XML special
        "LOAN_SCHEME": "SME Foundation",
        "SCHEME_SHORT_CODE": "SME-F",
        "FUND_CATEGORY": "Bangladesh Bank",
        "OUTSTANDING_AMOUNT": 800000.00 * idx,
        "PRINCIPAL_AMOUNT": 700000.00 * idx,
        "INTEREST_AMOUNT": 100000.00 * idx,
        "TOTAL_INSTALLMENT": 48,
        "CL_STATUS": "UC",
        "REPAY_DATE": datetime(2024, 3, 15),
        "REMARKS": None if idx % 2 == 0 else f"Remark for record {idx}",
    }


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Single-record DataFrame."""
    return pd.DataFrame([_make_row(1)])


@pytest.fixture
def multi_row_df() -> pd.DataFrame:
    """Three-record DataFrame."""
    return pd.DataFrame([_make_row(i) for i in range(1, 4)])


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Empty DataFrame with correct columns."""
    return pd.DataFrame(columns=SAMPLE_COLUMNS)


@pytest.fixture
def null_heavy_df() -> pd.DataFrame:
    """DataFrame where most values are None."""
    row = {col: None for col in SAMPLE_COLUMNS}
    row["BRANCH_ID"] = "0101"
    row["ACCOUNT_NUMBER"] = "01010001"
    return pd.DataFrame([row])


@pytest.fixture
def unicode_df() -> pd.DataFrame:
    """DataFrame with heavy Unicode content."""
    row = _make_row(1)
    row["BORROWER_NAME"] = "মোহাম্মদ আবদুল্লাহ"
    row["BUSINESS_ADDRESS"] = "গুলশান-২, ঢাকা-১২১২"
    row["PRODUCT_OF_ENTERPRISE"] = "হস্তশিল্প ও কুটিরশিল্প"
    row["LOAN_PURPOSE"] = "কর্মস্থল সম্প্রসারণ"
    row["REMARKS"] = "বিশেষ মন্তব্য ১২৩"
    return pd.DataFrame([row])
