"""
Refinance Records Table — renders the interactive data table in Streamlit.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd


def render_table(df: pd.DataFrame) -> None:
    """
    Render the refinance records in a searchable, scrollable data table.

    Streamlit's st.dataframe provides built-in column sorting, searching,
    and scrolling.
    """
    if df is None or df.empty:
        st.info("No records to display. Please load refinance data first.")
        return

    # Search / filter bar
    search_query = st.text_input(
        "🔍 Search records",
        placeholder="Type to filter across all columns…",
        key="table_search",
    )

    display_df = df.copy()

    if search_query:
        mask = display_df.astype(str).apply(
            lambda col: col.str.contains(search_query, case=False, na=False)
        ).any(axis=1)
        display_df = display_df[mask]
        st.caption(f"Showing {len(display_df)} of {len(df)} records matching '{search_query}'")
    else:
        st.caption(f"Showing all {len(df)} records")

    # Display the interactive dataframe
    st.dataframe(
        display_df,
        use_container_width=True,
        height=500,
        hide_index=True,
        column_config=_build_column_config(display_df),
    )


def _build_column_config(df: pd.DataFrame) -> dict:
    """
    Build Streamlit column_config for known column types.

    Since cursor column names are discovered at runtime, this applies
    formatting heuristics based on column name patterns.
    """
    config: dict = {}

    for col in df.columns:
        upper = col.upper()

        # Date columns
        if any(kw in upper for kw in ("DATE", "EXPIRY", "REPAY")):
            config[col] = st.column_config.DateColumn(
                col,
                format="DD-MMM-YYYY",
            )
        # Monetary / numeric columns
        elif any(kw in upper for kw in (
            "AMOUNT", "CAPITAL", "WORTH", "ASSET", "SALES",
            "PROFIT", "LOAN_AMOUNT", "OUTSTANDING", "PRINCIPAL",
            "INTEREST_AMOUNT", "INSTALLMENT",
        )):
            config[col] = st.column_config.NumberColumn(
                col,
                format="%.2f",
            )
        # Rate columns
        elif "RATE" in upper:
            config[col] = st.column_config.NumberColumn(
                col,
                format="%.2f%%",
            )

    return config
