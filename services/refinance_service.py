"""
Refinance Service — data retrieval and batch submission.

Executes Oracle stored procedures and returns results as DataFrames or
structured response objects. Never modifies the existing PL/SQL packages.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import oracledb
import pandas as pd

from database import managed_connection, DatabaseError

logger = logging.getLogger("refinance_app.services.refinance")


class SubmissionOutcomeUncertainError(DatabaseError):
    """Raised when a commit failure makes the submission outcome uncertain."""


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

XML_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "ACCOUNT_TITLE": ("ENTERPRISE_NAME",),
    "BORROWER_NAME": ("BORROWER_FULL_NAME",),
    "ESTABLISHED_STRUCTURE": ("ESTABLISHED_OWNERSHIP_STRUCTURE",),
    "LOAN_AMOUNT": ("SANCTION_AMOUNT",),
}


def get_xml_field_names() -> list[str]:
    """Return the ordered list of XML element names for TRANS_DETAILS."""
    return list(COLUMN_TO_XML_MAP.values())


def _oracle_error_code(exc: Exception) -> str | None:
    for argument in exc.args:
        code = getattr(argument, "code", None)
        if isinstance(code, int) and code:
            return f"ORA-{abs(code):05d}"

    match = re.search(r"\bORA-\d{5}\b", str(exc))
    return match.group(0) if match else None


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


def get_refinance_batch_numbers() -> list[str]:
    """Return distinct batch numbers currently present in the refinance master table."""
    try:
        with managed_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT t.BATCH_NO
                      FROM MGBL_REFINANCE_MASTER t
                     WHERE t.BATCH_NO IS NOT NULL
                     ORDER BY t.BATCH_NO
                    """
                )
                return [
                    str(row[0]).strip()
                    for row in cur.fetchall()
                    if row[0] is not None and str(row[0]).strip()
                ]
    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error("Failed to retrieve refinance batch numbers: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to retrieve batch numbers. Please try again or contact the system administrator."
        ) from exc
    except Exception as exc:
        logger.error("Unexpected batch-number retrieval error: %s", exc, exc_info=True)
        raise DatabaseError(
            "Unable to retrieve batch numbers. Please try again or contact the system administrator."
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
    actual = set(c.upper() for c in df.columns)

    available = {
        source
        for expected in COLUMN_TO_XML_MAP
        for source in (expected, *XML_SOURCE_ALIASES.get(expected, ()))
        if source in actual
    }
    mapped = sorted(
        expected
        for expected in COLUMN_TO_XML_MAP
        if expected in actual
        or any(alias in actual for alias in XML_SOURCE_ALIASES.get(expected, ()))
    )
    missing = sorted(set(COLUMN_TO_XML_MAP) - set(mapped))

    if missing:
        logger.warning("Missing cursor columns for XML mapping: %s", missing)

    # Also report any extra columns in the cursor not in the map
    extra = sorted(actual - available)
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


def tag_batch_reference(batch_no: str, reference_no: str) -> int:
    """Assign a Bangladesh Bank reference number to every row in a batch."""
    try:
        with managed_connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE MGBL_REFINANCE_MASTER t
                           SET t.BB_REFERENCE_ID = :P_REFERENCE_NO
                         WHERE t.BATCH_NO = :P_BATCH_NO
                        """,
                        {
                            "P_REFERENCE_NO": reference_no,
                            "P_BATCH_NO": batch_no,
                        },
                    )
                    rows_updated = cur.rowcount

                if rows_updated > 0:
                    conn.commit()
                    logger.info(
                        "Assigned reference number to %d refinance record(s) for batch %s.",
                        rows_updated,
                        batch_no,
                    )
                else:
                    conn.rollback()
                return rows_updated
            except Exception:
                conn.rollback()
                raise
    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error("Reference tagging failed for batch %s: %s", batch_no, exc, exc_info=True)
        raise DatabaseError(
            "Unable to assign the reference number due to a database error. "
            "Please try again or contact the system administrator."
        ) from exc
    except Exception as exc:
        logger.error("Unexpected reference tagging error for batch %s: %s", batch_no, exc, exc_info=True)
        raise DatabaseError(
            "Unable to assign the reference number. Please try again or contact the system administrator."
        ) from exc


def submit_refinance_batch(
    xml_data: str,
    make_by: str | None,
    make_date: datetime | None,
    authorize_by: str | None,
    authorize_date: datetime | None,
    record_count: int = 0,
) -> SubmissionResult:
    """
    Call PKG_MGBL_REFINANCE.REFINANCE_MASTER_INFO_I with the generated XML.

    Parameters
    ----------
    xml_data : str
        The complete XML CLOB to submit.
    make_by : str | None
        Optional maker user identity.
    make_date : datetime | None
        Optional maker timestamp.
    authorize_by : str | None
        Optional authorizer identity.
    authorize_date : datetime | None
        Optional authorization timestamp.
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
    Commit only when the procedure returns a batch number and a non-error
    status message. Roll back missing/failed outputs and raised exceptions.
    The PL/SQL source is not part of this project, so this cannot undo work
    that the procedure itself may already have committed.
    """
    if not xml_data or not xml_data.strip():
        return SubmissionResult(
            success=False,
            message="Cannot submit an empty XML payload.",
            timestamp=datetime.now(),
        )

    try:
        with managed_connection() as conn:
            try:
                with conn.cursor() as cur:
                    p_xml_data = cur.var(oracledb.DB_TYPE_CLOB)
                    p_xml_data.setvalue(0, xml_data)
                    p_message = cur.var(oracledb.DB_TYPE_NVARCHAR, 4000)
                    p_batch_no = cur.var(oracledb.DB_TYPE_NVARCHAR, 100)

                    cur.execute(
                        """
                        BEGIN
                            pkg_mgbl_refinance.refinance_master_info_i(
                                pxml_data       => :pxml_data,
                                pmake_by        => :pmake_by,
                                pmake_date      => :pmake_date,
                                pauthorize_by   => :pauthorize_by,
                                pauthorize_date => :pauthorize_date,
                                pmessage        => :pmessage,
                                pbatch_no       => :pbatch_no
                            );
                        END;
                        """,
                        {
                            "pxml_data": p_xml_data,
                            "pmake_by": make_by,
                            "pmake_date": make_date,
                            "pauthorize_by": authorize_by,
                            "pauthorize_date": authorize_date,
                            "pmessage": p_message,
                            "pbatch_no": p_batch_no,
                        },
                    )

                    message = str(p_message.getvalue() or "").strip()
                    batch_value = p_batch_no.getvalue()
                    batch = str(batch_value).strip() if batch_value is not None else ""

                count_match = re.search(
                    r"^000\s*-\s*Successfully inserted\s+(\d+)\s+record\(s\)",
                    message,
                    re.IGNORECASE,
                )
                returned_count = int(count_match.group(1)) if count_match else 0
                is_success = (
                    bool(batch)
                    and count_match is not None
                    and returned_count == record_count
                )
                if not is_success:
                    conn.rollback()
                    logger.warning(
                        "Refinance submission was not confirmed by Oracle (%d records).",
                        record_count,
                    )
                    return SubmissionResult(
                        success=False,
                        message=message or "The Oracle procedure did not confirm a successful submission.",
                        batch_number=batch or None,
                        timestamp=datetime.now(),
                        record_count=returned_count,
                    )

            except Exception as exc:
                try:
                    conn.rollback()
                except Exception as rollback_exc:
                    logger.error(
                        "Rollback failed after refinance procedure error: %s",
                        rollback_exc,
                        exc_info=True,
                    )
                    raise SubmissionOutcomeUncertainError(
                        "The submission failed and its rollback could not be confirmed. "
                        "Verify the batch status before retrying."
                    ) from rollback_exc
                oracle_code = _oracle_error_code(exc)
                raise DatabaseError(
                    "Oracle rejected the refinance submission; the transaction was rolled back. "
                    + (
                        f"Oracle error code: {oracle_code}. "
                        if oracle_code
                        else ""
                    )
                    + "Check the application log for details, correct the input, and retry."
                ) from exc

            try:
                conn.commit()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception as rollback_exc:
                    logger.error(
                        "Rollback failed after refinance commit error: %s",
                        rollback_exc,
                        exc_info=True,
                    )
                logger.error("Refinance submission commit outcome is uncertain: %s", exc, exc_info=True)
                raise SubmissionOutcomeUncertainError(
                    "The database commit outcome is uncertain. Verify the batch status before retrying."
                ) from exc

            logger.info(
                "Refinance submission confirmed by Oracle (%d records).",
                record_count,
            )
            return SubmissionResult(
                success=True,
                message=message,
                batch_number=batch,
                timestamp=datetime.now(),
                record_count=returned_count,
            )

    except SubmissionOutcomeUncertainError:
        raise
    except DatabaseError:
        raise
    except oracledb.Error as exc:
        logger.error(
            "Procedure REFINANCE_MASTER_INFO_I failed: %s", exc, exc_info=True
        )
        oracle_code = _oracle_error_code(exc)
        raise DatabaseError(
            "Batch submission failed due to a database error. "
            + (
                f"Oracle error code: {oracle_code}. "
                if oracle_code
                else ""
            )
            + "Please verify the batch status before retrying."
        ) from exc
    except Exception as exc:
        logger.error(
            "Unexpected error during batch submission: %s", exc, exc_info=True
        )
        raise DatabaseError(
            "An unexpected error occurred during submission. "
            "Please verify the batch status before retrying."
        ) from exc
