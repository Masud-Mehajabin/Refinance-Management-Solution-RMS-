"""
Tests for refinance_service — procedure call handling and error paths.

Uses mocked database connections to test without a live Oracle instance.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest
import oracledb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.refinance_service import (
    BatchNumberMissingError,
    generate_batch_number,
    get_batch_details,
    get_pending_batches,
    get_refinance_details,
    submit_refinance_batch,
    SubmissionResult,
)
from database import DatabaseError


# ===================================================================
# get_refinance_details
# ===================================================================

class TestGetRefinanceDetails:
    @pytest.mark.parametrize("branch_id", [None, "", "   "])
    @patch("services.refinance_service.managed_connection")
    def test_blank_branch_requests_all_records(self, mock_conn_ctx, branch_id):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_result_cursor = MagicMock()
        mock_result_cursor.description = [("BRANCH_ID",)]
        mock_result_cursor.fetchall.return_value = []
        mock_var = MagicMock()
        mock_var.getvalue.return_value = mock_result_cursor
        mock_cursor.var.return_value = mock_var

        result = get_refinance_details(branch_id)

        assert result.empty
        mock_cursor.callproc.assert_called_once()
        assert mock_cursor.callproc.call_args.args[1][0] is None

    @patch("services.refinance_service.managed_connection")
    def test_null_cursor_returns_empty_df(self, mock_conn_ctx):
        """When the procedure returns a NULL cursor."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # var().getvalue() returns None → NULL cursor
        mock_var = MagicMock()
        mock_var.getvalue.return_value = None
        mock_cursor.var.return_value = mock_var

        df = get_refinance_details("0101")
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    @patch("services.refinance_service.managed_connection")
    def test_empty_result_returns_empty_df(self, mock_conn_ctx):
        """When the cursor returns no rows."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_result_cursor = MagicMock()
        mock_result_cursor.description = [("BRANCH_ID",), ("ACCOUNT_NUMBER",)]
        mock_result_cursor.fetchall.return_value = []

        mock_var = MagicMock()
        mock_var.getvalue.return_value = mock_result_cursor
        mock_cursor.var.return_value = mock_var

        df = get_refinance_details("0101")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == ["BRANCH_ID", "ACCOUNT_NUMBER"]

    @patch("services.refinance_service.managed_connection")
    def test_successful_retrieval(self, mock_conn_ctx):
        """Simulates a successful cursor with data."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_result_cursor = MagicMock()
        mock_result_cursor.description = [
            ("BRANCH_ID",), ("ACCOUNT_NUMBER",), ("CUSTOMER_ID",)
        ]
        mock_result_cursor.fetchall.return_value = [
            ("0101", "01010001", "CUST0001"),
            ("0101", "01010002", "CUST0002"),
        ]

        mock_var = MagicMock()
        mock_var.getvalue.return_value = mock_result_cursor
        mock_cursor.var.return_value = mock_var

        df = get_refinance_details("0101")
        assert len(df) == 2
        assert list(df.columns) == ["BRANCH_ID", "ACCOUNT_NUMBER", "CUSTOMER_ID"]


class TestGetPendingBatches:
    @pytest.mark.parametrize(
        ("batch_no", "expected_batch_no"),
        [(None, None), ("", None), ("  0012  ", "0012")],
    )
    @patch("services.refinance_service.managed_connection")
    def test_returns_cursor_rows_and_binds_optional_filter(
        self, mock_conn_ctx, batch_no, expected_batch_no
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        result_cursor = MagicMock()
        result_cursor.description = [("BATCH_NO",), ("NO_OF_LOAN",)]
        result_cursor.fetchall.return_value = [("0012", 3)]
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        batch_no_var = MagicMock()
        result_cursor_var = MagicMock()
        result_cursor_var.getvalue.return_value = result_cursor
        mock_cursor.var.side_effect = [batch_no_var, result_cursor_var]

        result = get_pending_batches(batch_no)

        assert list(result.columns) == ["BATCH_NO", "NO_OF_LOAN"]
        assert result.to_dict(orient="records") == [{"BATCH_NO": "0012", "NO_OF_LOAN": 3}]
        batch_no_var.setvalue.assert_called_once_with(0, expected_batch_no)
        assert mock_cursor.execute.call_args.args[1] == {
            "pbatch_no": batch_no_var,
            "presult_set_cur": result_cursor_var,
        }
        result_cursor.close.assert_called_once_with()
        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()

    @patch("services.refinance_service.managed_connection")
    def test_empty_cursor_keeps_actual_column_names(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        result_cursor = MagicMock()
        result_cursor.description = [("BATCH_NO",), ("MAKE_BY",)]
        result_cursor.fetchall.return_value = []
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        result_cursor_var = MagicMock()
        result_cursor_var.getvalue.return_value = result_cursor
        mock_cursor.var.side_effect = [MagicMock(), result_cursor_var]

        result = get_pending_batches()

        assert result.empty
        assert list(result.columns) == ["BATCH_NO", "MAKE_BY"]

    @patch("services.refinance_service.managed_connection")
    def test_oracle_error_is_logged_and_wrapped_safely(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = oracledb.DatabaseError("sensitive details")

        with pytest.raises(DatabaseError, match="Unable to retrieve pending batches") as exc_info:
            get_pending_batches()

        assert "sensitive details" not in str(exc_info.value)


class TestGetBatchDetails:
    @pytest.mark.parametrize(
        ("batch_no", "expected_batch_no"),
        [(None, None), ("", None), ("  0012  ", "0012")],
    )
    @patch("services.refinance_service.managed_connection")
    def test_returns_rows_and_binds_optional_filter(
        self, mock_conn_ctx, batch_no, expected_batch_no
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        result_cursor = MagicMock()
        result_cursor.description = [("BATCH_NO",), ("ACCOUNT_NUMBER",)]
        result_cursor.fetchall.return_value = [("0012", "0000456")]
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        batch_no_var = MagicMock()
        result_cursor_var = MagicMock()
        result_cursor_var.getvalue.return_value = result_cursor
        mock_cursor.var.side_effect = [batch_no_var, result_cursor_var]

        result = get_batch_details(batch_no)

        assert list(result.columns) == ["BATCH_NO", "ACCOUNT_NUMBER"]
        assert result.to_dict(orient="records") == [
            {"BATCH_NO": "0012", "ACCOUNT_NUMBER": "0000456"}
        ]
        batch_no_var.setvalue.assert_called_once_with(0, expected_batch_no)
        assert mock_cursor.execute.call_args.args[1] == {
            "Pbatch_no": batch_no_var,
            "Presult_set_cur": result_cursor_var,
        }
        assert "pkg_mgbl_refinance.get_details_by_batch" in mock_cursor.execute.call_args.args[0]
        result_cursor.close.assert_called_once_with()
        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()

    @patch("services.refinance_service.managed_connection")
    def test_empty_result_keeps_cursor_columns(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        result_cursor = MagicMock()
        result_cursor.description = [("BATCH_NO",), ("BB_APPROVAL_STATUS",)]
        result_cursor.fetchall.return_value = []
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        result_cursor_var = MagicMock()
        result_cursor_var.getvalue.return_value = result_cursor
        mock_cursor.var.side_effect = [MagicMock(), result_cursor_var]

        result = get_batch_details()

        assert result.empty
        assert list(result.columns) == ["BATCH_NO", "BB_APPROVAL_STATUS"]

    @patch("services.refinance_service.managed_connection")
    def test_oracle_error_is_wrapped_safely(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = oracledb.DatabaseError("sensitive details")

        with pytest.raises(DatabaseError, match="Unable to retrieve batch details") as exc_info:
            get_batch_details()

        assert "sensitive details" not in str(exc_info.value)


# ===================================================================
# submit_refinance_batch
# ===================================================================

class TestSubmitRefinanceBatch:
    def test_empty_xml_returns_failure(self):
        result = submit_refinance_batch(
            xml_data="",
            make_by="test",
            make_date=datetime.now(),
            authorize_by="test",
            authorize_date=datetime.now(),
        )
        assert result.success is False
        assert "empty" in result.message.lower()

    @patch("services.refinance_service.managed_connection")
    def test_successful_submission(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Simulate OUT parameters
        mock_msg_var = MagicMock()
        mock_msg_var.getvalue.return_value = "Batch created successfully"
        mock_batch_var = MagicMock()
        mock_batch_var.getvalue.return_value = "BATCH-20240315-001"

        mock_cursor.var.side_effect = [mock_msg_var, mock_batch_var]

        result = submit_refinance_batch(
            xml_data="<TRANSACTION_INFO><TRANS_DETAILS></TRANS_DETAILS></TRANSACTION_INFO>",
            make_by="test_user",
            make_date=datetime(2024, 3, 15),
            authorize_by="auth_user",
            authorize_date=datetime(2024, 3, 15),
            record_count=1,
        )

        assert result.success is True
        assert result.batch_number == "BATCH-20240315-001"
        assert result.record_count == 1

    @patch("services.refinance_service.managed_connection")
    def test_procedure_error_message(self, mock_conn_ctx):
        """Procedure returns an error message without raising an exception."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_msg_var = MagicMock()
        mock_msg_var.getvalue.return_value = "Error: duplicate batch detected"
        mock_batch_var = MagicMock()
        mock_batch_var.getvalue.return_value = ""

        mock_cursor.var.side_effect = [mock_msg_var, mock_batch_var]

        result = submit_refinance_batch(
            xml_data="<TRANSACTION_INFO><TRANS_DETAILS></TRANS_DETAILS></TRANSACTION_INFO>",
            make_by="test_user",
            make_date=datetime(2024, 3, 15),
            authorize_by="auth_user",
            authorize_date=datetime(2024, 3, 15),
        )

        assert result.success is False
        assert "error" in result.message.lower()

    @patch("services.refinance_service.managed_connection")
    def test_missing_batch_number(self, mock_conn_ctx):
        """Procedure completes but returns no batch number."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_msg_var = MagicMock()
        mock_msg_var.getvalue.return_value = "Processing complete"
        mock_batch_var = MagicMock()
        mock_batch_var.getvalue.return_value = None

        mock_cursor.var.side_effect = [mock_msg_var, mock_batch_var]

        result = submit_refinance_batch(
            xml_data="<TRANSACTION_INFO><TRANS_DETAILS></TRANS_DETAILS></TRANSACTION_INFO>",
            make_by="test_user",
            make_date=datetime(2024, 3, 15),
            authorize_by="auth_user",
            authorize_date=datetime(2024, 3, 15),
        )

        # No batch number → treated as unsuccessful
        assert result.success is False
        assert result.batch_number is None


class TestGenerateBatchNumber:
    @pytest.mark.parametrize(
        ("total_loan_no", "create_by"),
        [(None, None), ("10001", None), (None, "maker"), ("10001", "maker")],
    )
    @patch("services.refinance_service.managed_connection")
    def test_successful_generation_binds_optional_inputs_and_commits(
        self, mock_conn_ctx, total_loan_no, create_by
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        total_loan_var = MagicMock()
        create_by_var = MagicMock()
        batch_number_var = MagicMock()
        batch_number_var.getvalue.return_value = "87"
        mock_cursor.var.side_effect = [total_loan_var, create_by_var, batch_number_var]

        result = generate_batch_number(total_loan_no, create_by)

        assert result == "87"
        assert mock_cursor.execute.call_args.args[1] == {
            "ptotal_loan_no": total_loan_var,
            "pcreate_by": create_by_var,
            "pbatch_no": batch_number_var,
        }
        total_loan_var.setvalue.assert_called_once_with(0, total_loan_no)
        create_by_var.setvalue.assert_called_once_with(0, create_by)
        assert mock_cursor.var.call_args_list == [
            ((oracledb.DB_TYPE_NVARCHAR,), {"size": max(1, len(total_loan_no or ""))}),
            ((oracledb.DB_TYPE_NVARCHAR,), {"size": max(1, len(create_by or ""))}),
            ((oracledb.DB_TYPE_NVARCHAR,), {"size": 100}),
        ]
        mock_conn.commit.assert_called_once_with()
        mock_conn.rollback.assert_not_called()

    @patch("services.refinance_service.managed_connection")
    def test_missing_output_rolls_back_without_success(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        batch_number_var = MagicMock()
        batch_number_var.getvalue.return_value = None
        mock_cursor.var.side_effect = [MagicMock(), MagicMock(), batch_number_var]

        with pytest.raises(BatchNumberMissingError, match="no batch number was returned"):
            generate_batch_number()

        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_called_once_with()

    @patch("services.refinance_service.managed_connection")
    def test_oracle_error_rolls_back_and_returns_safe_database_error(self, mock_conn_ctx):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn_ctx.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_ctx.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = oracledb.DatabaseError("sensitive database detail")

        with pytest.raises(DatabaseError, match="Unable to generate the batch") as exc_info:
            generate_batch_number()

        assert "sensitive database detail" not in str(exc_info.value)
        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_called_once_with()
