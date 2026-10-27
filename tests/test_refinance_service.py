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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.refinance_service import (
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
