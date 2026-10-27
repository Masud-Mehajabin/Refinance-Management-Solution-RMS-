"""
Refinance Service — data retrieval and batch submission.

Executes Oracle stored procedures and returns results as DataFrames or
structured response objects. Never modifies the existing PL/SQL packages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import oracledb
import pandas as pd

from database import managed_connection, DatabaseError

logger = logging.getLogger("refinance_app.services.refinance")


# ---------------------------------------------------------------------------
# Column-name mapping: cursor column  →  XML element name
# ---------------------------------------------------------------------------
# This mapping is the single source of truth for transforming GET_REFINANCE_DETAILS
# output into XML expected by REFINANCE_MASTER_INFO_I.
#
# *** IMPLEMENTATION DEPENDENCY ***
# The LEFT side (keys) must match the actual column names returned by
# GET_REFINANCE_DETAILS.  If the real cursor uses different names, update
# this dictionary BEFORE production deployment.
#
# The RIGHT side (values) must match the XML element names expected by
# REFINANCE_MASTER_INFO_I as documented in the project specification.
# ---------------------------------------------------------------------------

COLUMN_TO_XML_MAP: dict[str, str] = {
    "CUSTOMER_ID":            "Pcustomer_id",
    "BORROWER_PHONE":         "PBorrower_Phone",
    "BORROWER_NID":           "PBorrower_NID",
    "BUSINESS_ADDRESS":       "PBusiness_Address",
    "DISTRICT_NM":            "Pdistrict_nm",
    "SECTOR":                 "Psector",
    "SUBSECTOR":              "Psubsector",
    "PRODUCT_OF_ENTERPRISE":  "Pproduct_of_enterprise",
    "ESTABLISHED_YEAR":       "Pestablished_year",
    "OWNERSHIP_GENDER":       "POwnership_gender",
    "TYPE_OF_SME":            "Ptype_of_sme",
    "TRADE_LICENSE_NO":       "Ptrade_license_no",
    "PAIDUP_CAPITAL":         "Ppaidup_capital",
    "NET_WORTH":              "Pnet_worth",
    "FIXED_ASSET_VALUE":      "Pfixed_asset_value",
    "ANNUAL_SALES":           "Pannual_sales",
    "NET_PROFIT_AFTER_TAX":   "Pnet_profit_after_tax",
    "NO_OF_EMPLOYEE":         "Pno_of_employee",
    "NO_OF_EMPLOYEE_M":       "Pno_of_employee_m",
    "NO_OF_EMPLOYEE_F":       "Pno_of_employee_f",
    "INTEREST_RATE":          "Pinterest_Rate",
    "DISBURSEMENT_DATE":      "PDisbursement_date",
    "GRACE_PERIOD":           "PGrace_Period",
    "LOAN_PURPOSE":           "PLoan_purpose",
    "REMARKS":                "PRemarks",
    "BRANCH_ID":              "Pbranch_id",
    "ACCOUNT_NUMBER":         "Paccount_number",
    "GROUP_ID":               "Pgroup_id",
    "ACCOUNT_TITLE":          "Paccount_title",
    "BORROWER_NAME":          "Pborrower_name",
    "ESTABLISHED_STRUCTURE":  "Pestablished_structure",
    "LOAN_AMOUNT":            "Ploan_amount",
    "OPEN_DATE":              "Popen_date",
    "EXPIRY_DATE":            "Pexpiry_date",
    "TENURE":                 "Ptenure",
    "LOAN_SCHEME":            "Ploan_scheme",
    "SCHEME_SHORT_CODE":      "Pscheme_short_code",
    "FUND_CATEGORY":          "Pfund_category",
    "OUTSTANDING_AMOUNT":     "Poutstanding_amount",
    "PRINCIPAL_AMOUNT":       "Pprincipal_amount",
    "INTEREST_AMOUNT":        "Pinterest_amount",
    "TOTAL_INSTALLMENT":      "Ptotal_installment",
    "CL_STATUS":              "Pcl_status",
    "REPAY_DATE":             "Prepay_date",
}


def get_xml_field_names() -> list[str]:
    """Return the ordered list of XML element names for TRANS_DETAILS."""
    return list(COLUMN_TO_XML_MAP.values())


# ---------------------------------------------------------------------------
# Data Retrieval
# ---------------------------------------------------------------------------

def get_refinance_details(branch_id: str | None = None) -> pd.DataFrame:
    """
    Call PKG_MGBL_REFINANCE.GET_REFINANCE_DETAILS and return the
    result-set cursor as a pandas DataFrame.

    Parameters
    ----------
    branch_id : str | None
        A branch identifier, or None to request records for all branches.

    Returns
    -------
    pd.DataFrame
        Records with column names taken directly from the cursor description.

    Raises
    ------
    DatabaseError
        On connection or procedure execution failure (user-safe message).
    """
    branch_id = branch_id.strip() if branch_id and branch_id.strip() else None

    try:
        with managed_connection() as conn:
            with conn.cursor() as cur:
                # OUT parameter — SYS_REFCURSOR
                ref_cursor = cur.var(oracledb.CURSOR)

                cur.callproc(
                    "PKG_MGBL_REFINANCE.GET_REFINANCE_DETAILS",
                    [branch_id, ref_cursor],
                )

                result_cursor: oracledb.Cursor = ref_cursor.getvalue()

                if result_cursor is None:
                    logger.warning(
                        "Procedure returned NULL cursor for branch %s.", branch_id
                    )
                    return pd.DataFrame()

                # Extract column names from the cursor description
                columns = [
                    col[0] for col in result_cursor.description
                ] if result_cursor.description else []

                rows = result_cursor.fetchall()
                result_cursor.close()

                if not rows:
                    logger.info(
                        "No records returned for branch %s.", branch_id
                    )
                    return pd.DataFrame(columns=columns)

                df = pd.DataFrame(rows, columns=columns)
                logger.info(
                    "Retrieved %d records for branch %s.", len(df), branch_id
                )
                return df

    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error(
            "Procedure GET_REFINANCE_DETAILS failed: %s", exc, exc_info=True
        )
        raise DatabaseError(
            "Failed to retrieve refinance details. "
            "Please try again or contact support."
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error during retrieval: %s", exc, exc_info=True)
        raise DatabaseError(
            "An unexpected error occurred while retrieving refinance data."
        ) from exc


def get_pending_batches(batch_no: str | None = None) -> pd.DataFrame:
    """Fetch pending batch records using the package's optional batch filter."""
    batch_no = batch_no.strip() if batch_no and batch_no.strip() else None

    try:
        with managed_connection() as conn:
            with conn.cursor() as cur:
                batch_no_var = cur.var(
                    oracledb.DB_TYPE_NVARCHAR,
                    size=max(1, len(batch_no or "")),
                )
                batch_no_var.setvalue(0, batch_no)
                result_cursor_var = cur.var(oracledb.CURSOR)
                cur.execute(
                    """
                    BEGIN
                        pkg_mgbl_refinance.get_upapproved_batch(
                            pbatch_no       => :pbatch_no,
                            presult_set_cur => :presult_set_cur
                        );
                    END;
                    """,
                    {
                        "pbatch_no": batch_no_var,
                        "presult_set_cur": result_cursor_var,
                    },
                )
                result_cursor = result_cursor_var.getvalue()
                if result_cursor is None:
                    logger.info(
                        "GET_UPAPPROVED_BATCH returned a NULL cursor for batch %s.",
                        batch_no,
                    )
                    return pd.DataFrame()

                try:
                    columns = (
                        [column[0] for column in result_cursor.description]
                        if result_cursor.description
                        else []
                    )
                    rows = result_cursor.fetchall()
                finally:
                    result_cursor.close()

                result = pd.DataFrame(rows, columns=columns)
                logger.info(
                    "Retrieved %d pending batch records for batch %s.",
                    len(result),
                    batch_no,
                )
                return result
    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error("Procedure GET_UPAPPROVED_BATCH failed: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to retrieve pending batches. Please try again or contact the system administrator."
        ) from exc
    except Exception as exc:
        logger.error("Unexpected pending batch retrieval error: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to retrieve pending batches. Please try again or contact the system administrator."
        ) from exc


def get_batch_details(batch_no: str | None = None) -> pd.DataFrame:
    """Fetch batch details using the package's optional batch filter."""
    batch_no = batch_no.strip() if batch_no and batch_no.strip() else None

    try:
        with managed_connection() as conn:
            with conn.cursor() as cur:
                batch_no_var = cur.var(
                    oracledb.DB_TYPE_NVARCHAR,
                    size=max(1, len(batch_no or "")),
                )
                batch_no_var.setvalue(0, batch_no)
                result_cursor_var = cur.var(oracledb.CURSOR)
                cur.execute(
                    """
                    BEGIN
                        pkg_mgbl_refinance.get_details_by_batch(
                            Pbatch_no       => :Pbatch_no,
                            Presult_set_cur => :Presult_set_cur
                        );
                    END;
                    """,
                    {
                        "Pbatch_no": batch_no_var,
                        "Presult_set_cur": result_cursor_var,
                    },
                )
                result_cursor = result_cursor_var.getvalue()
                if result_cursor is None:
                    logger.info(
                        "GET_DETAILS_BY_BATCH returned a NULL cursor for batch %s.",
                        batch_no,
                    )
                    return pd.DataFrame()

                try:
                    columns = (
                        [column[0] for column in result_cursor.description]
                        if result_cursor.description
                        else []
                    )
                    rows = result_cursor.fetchall()
                finally:
                    result_cursor.close()

                result = pd.DataFrame(rows, columns=columns)
                logger.info(
                    "Retrieved %d batch detail records for batch %s.",
                    len(result),
                    batch_no,
                )
                return result
    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error("Procedure GET_DETAILS_BY_BATCH failed: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to retrieve batch details. Please try again or contact the system administrator."
        ) from exc
    except Exception as exc:
        logger.error("Unexpected batch detail retrieval error: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to retrieve batch details. Please try again or contact the system administrator."
        ) from exc


def validate_column_mapping(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """
    Check whether every expected source column exists in the DataFrame.

    Returns
    -------
    (mapped_columns, missing_columns)
        mapped_columns  — source columns that exist in both df and the map.
        missing_columns — source columns expected by the map but absent in df.
    """
    expected = set(COLUMN_TO_XML_MAP.keys())
    actual = set(c.upper() for c in df.columns)

    mapped = sorted(expected & actual)
    missing = sorted(expected - actual)

    if missing:
        logger.warning("Missing cursor columns for XML mapping: %s", missing)

    # Also report any extra columns in the cursor not in the map
    extra = sorted(actual - expected)
    if extra:
        logger.info("Extra cursor columns not in XML map: %s", extra)

    return mapped, missing


# ---------------------------------------------------------------------------
# Batch Submission
# ---------------------------------------------------------------------------

@dataclass
class SubmissionResult:
    """Encapsulates the outcome of a batch submission call."""
    success: bool
    message: str
    batch_number: Optional[str] = None
    timestamp: Optional[datetime] = None
    record_count: int = 0


class BatchNumberMissingError(Exception):
    """Raised when batch generation completes without an output batch number."""


def generate_batch_number(
    total_loan_no: str | None = None,
    create_by: str | None = None,
) -> str:
    """Generate and persist a refinance batch reference through Oracle."""
    try:
        with managed_connection() as conn:
            try:
                with conn.cursor() as cur:
                    total_loan_no_var = cur.var(
                        oracledb.DB_TYPE_NVARCHAR,
                        size=max(1, len(total_loan_no or "")),
                    )
                    total_loan_no_var.setvalue(0, total_loan_no)
                    create_by_var = cur.var(
                        oracledb.DB_TYPE_NVARCHAR,
                        size=max(1, len(create_by or "")),
                    )
                    create_by_var.setvalue(0, create_by)
                    batch_number_var = cur.var(oracledb.DB_TYPE_NVARCHAR, size=100)
                    cur.execute(
                        """
                        BEGIN
                            pkg_mgbl_refinance.generate_batch_number(
                                ptotal_loan_no => :ptotal_loan_no,
                                pcreate_by     => :pcreate_by,
                                pbatch_no      => :pbatch_no
                            );
                        END;
                        """,
                        {
                            "ptotal_loan_no": total_loan_no_var,
                            "pcreate_by": create_by_var,
                            "pbatch_no": batch_number_var,
                        },
                    )
                    batch_number = batch_number_var.getvalue()

                if batch_number is None or not str(batch_number).strip():
                    conn.rollback()
                    raise BatchNumberMissingError(
                        "Batch generation completed, but no batch number was returned. "
                        "Please verify the database procedure."
                    )

                conn.commit()
                return str(batch_number).strip()
            except BatchNumberMissingError:
                raise
            except Exception:
                conn.rollback()
                raise
    except (DatabaseError, BatchNumberMissingError):
        raise
    except Exception as exc:
        logger.error("Batch number generation failed: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to generate the batch. Please contact the system administrator if the problem persists."
        ) from exc


def submit_refinance_batch(
    xml_data: str,
    make_by: str,
    make_date: datetime,
    authorize_by: str,
    authorize_date: datetime,
    record_count: int = 0,
) -> SubmissionResult:
    """
    Call PKG_MGBL_REFINANCE.REFINANCE_MASTER_INFO_I with the generated XML.

    Parameters
    ----------
    xml_data : str
        The complete XML CLOB to submit.
    make_by : str
        The maker user identity.
    make_date : datetime
        Maker timestamp.
    authorize_by : str
        Authorizer identity.
    authorize_date : datetime
        Authorization timestamp.
    record_count : int
        Number of records in the submission (for logging / display).

    Returns
    -------
    SubmissionResult
        Structured result including the procedure's Pmessage and PBatch_NO.

    Implementation Dependency
    -------------------------
    The correct values for ``authorize_by`` and ``authorize_date`` must be
    determined from the bank's actual business and authorization rules.
    This function accepts them as parameters and does NOT manufacture
    authorization identities.

    Transaction Behavior
    --------------------
    The existing procedure's commit/rollback behavior has not been inspected.
    This function does NOT issue an explicit COMMIT or ROLLBACK to avoid
    conflicting with the procedure's own transaction management.
    If inspection reveals the procedure does not commit, an explicit COMMIT
    should be added here after verification.
    """
    if not xml_data or not xml_data.strip():
        return SubmissionResult(
            success=False,
            message="Cannot submit an empty XML payload.",
            timestamp=datetime.now(),
        )

    try:
        with managed_connection() as conn:
            with conn.cursor() as cur:
                # OUT bind variables
                p_message = cur.var(oracledb.DB_TYPE_NVARCHAR, 4000)
                p_batch_no = cur.var(oracledb.DB_TYPE_NVARCHAR, 100)

                cur.callproc(
                    "PKG_MGBL_REFINANCE.REFINANCE_MASTER_INFO_I",
                    [
                        xml_data,       # Pxml_data   IN CLOB
                        make_by,        # Pmake_by    IN NVARCHAR2
                        make_date,      # Pmake_date  IN DATE
                        authorize_by,   # Pauthorize_by   IN NVARCHAR2
                        authorize_date, # Pauthorize_date IN DATE
                        p_message,      # Pmessage    OUT NVARCHAR2
                        p_batch_no,     # PBatch_NO   OUT NVARCHAR2
                    ],
                )

                msg = p_message.getvalue() or ""
                batch = p_batch_no.getvalue() or ""

                logger.info(
                    "Procedure returned — message: %s, batch: %s",
                    msg, batch,
                )

                # Determine success from the procedure's own output.
                # Convention: a non-empty batch number with a non-error
                # message indicates success.  Adjust after inspecting the
                # actual procedure contract.
                is_success = bool(batch) and "error" not in msg.lower()

                return SubmissionResult(
                    success=is_success,
                    message=msg,
                    batch_number=batch if batch else None,
                    timestamp=datetime.now(),
                    record_count=record_count,
                )

    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error(
            "Procedure REFINANCE_MASTER_INFO_I failed: %s", exc, exc_info=True
        )
        return SubmissionResult(
            success=False,
            message=(
                "Batch submission failed due to a database error. "
                "The batch may NOT have been created. "
                "Please check before retrying."
            ),
            timestamp=datetime.now(),
            record_count=record_count,
        )
    except Exception as exc:
        logger.error(
            "Unexpected error during batch submission: %s", exc, exc_info=True
        )
        return SubmissionResult(
            success=False,
            message=(
                "An unexpected error occurred during submission. "
                "Outcome is uncertain — please verify before retrying."
            ),
            timestamp=datetime.now(),
            record_count=record_count,
        )
