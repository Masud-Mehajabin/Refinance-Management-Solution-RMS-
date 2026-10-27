"""
Dialogs — confirmation and result display components for batch submission.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from services.refinance_service import SubmissionResult


def render_confirmation_dialog(
    branch_id: str,
    record_count: int,
) -> bool:
    """
    Render a confirmation section before batch submission.

    Returns True if the user confirms, False otherwise.
    Uses Streamlit session state to track confirmation.
    """
    st.markdown(
        '<div class="banner-warning">'
        "⚠️ <strong>Batch Submission Confirmation</strong>"
        "</div>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Branch:** {branch_id}")
    with col2:
        st.markdown(f"**Records to submit:** {record_count}")

    st.warning(
        "You are about to generate and submit a refinance batch. "
        "This is a consequential banking operation. "
        "Please review the data before proceeding."
    )

    col_confirm, col_cancel = st.columns([1, 1])

    with col_confirm:
        confirmed = st.button(
            "✅  Confirm & Submit",
            type="primary",
            key="confirm_submit",
            use_container_width=True,
        )
    with col_cancel:
        cancelled = st.button(
            "❌  Cancel",
            key="cancel_submit",
            use_container_width=True,
        )

    if cancelled:
        st.session_state["submission_stage"] = None
        st.rerun()

    return confirmed


def render_submission_result(result: SubmissionResult) -> None:
    """Display the outcome of a batch submission."""
    if result.success:
        st.markdown(
            '<div class="banner-success">'
            "✅ <strong>Batch submitted successfully!</strong>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="result-card">', unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown(
                f'<div class="result-label">Batch Number</div>'
                f'<div class="batch-number">{result.batch_number or "N/A"}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="result-label">Procedure Message</div>'
                f'<div class="result-value">{result.message}</div>',
                unsafe_allow_html=True,
            )

        with col2:
            st.markdown(
                f'<div class="result-label">Records Submitted</div>'
                f'<div class="result-value">{result.record_count}</div>',
                unsafe_allow_html=True,
            )
            ts_display = (
                result.timestamp.strftime("%d-%b-%Y %H:%M:%S")
                if result.timestamp else "N/A"
            )
            st.markdown(
                f'<div class="result-label">Submission Timestamp</div>'
                f'<div class="result-value">{ts_display}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="result-label">Status</div>'
                f'<div class="result-value">Successful</div>',
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    else:
        st.markdown(
            '<div class="banner-error">'
            "❌ <strong>Batch submission was not successful.</strong>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="result-card">', unsafe_allow_html=True)

        st.markdown(
            f'<div class="result-label">Procedure Message</div>'
            f'<div class="result-value">{result.message}</div>',
            unsafe_allow_html=True,
        )

        if result.batch_number:
            st.markdown(
                f'<div class="result-label">Batch Number (partial)</div>'
                f'<div class="result-value">{result.batch_number}</div>',
                unsafe_allow_html=True,
            )

        ts_display = (
            result.timestamp.strftime("%d-%b-%Y %H:%M:%S")
            if result.timestamp else "N/A"
        )
        st.markdown(
            f'<div class="result-label">Timestamp</div>'
            f'<div class="result-value">{ts_display}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.info(
            "The batch was NOT created. Review the message above and verify "
            "the data before retrying."
        )


def render_already_submitted_warning() -> bool:
    """
    Warn the user that the current dataset has already been submitted.

    Returns True if the user explicitly chooses to resubmit.
    """
    st.markdown(
        '<div class="banner-warning">'
        "⚠️ <strong>This dataset has already been submitted.</strong>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.warning(
        "Submitting the same dataset again may create a duplicate batch. "
        "Only proceed if this is intentionally permitted."
    )

    return st.button(
        "🔄  Resubmit Anyway",
        key="resubmit_confirm",
    )
