"""
Layout module — global page configuration and custom CSS for the
professional banking-style interface.
"""

from __future__ import annotations

import streamlit as st


def configure_page() -> None:
    """Set the Streamlit page config (must be the first Streamlit call)."""
    st.set_page_config(
        page_title="Refinance Management",
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )


def inject_custom_css() -> None:
    """Inject the banking-style CSS overrides."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Custom CSS — navy-blue / white / light-grey palette
# ---------------------------------------------------------------------------

_CSS = """
<style>
    /* ---------- Google Font ---------- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ---------- Global ---------- */
    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }

    /* ---------- Header bar ---------- */
    .app-header {
        background: linear-gradient(135deg, #0a1628 0%, #1b3a5c 50%, #234b73 100%);
        color: #ffffff;
        padding: 1.2rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(10, 22, 40, 0.25);
    }
    .app-header h1 {
        margin: 0;
        font-size: 1.65rem;
        font-weight: 700;
        letter-spacing: 0.3px;
    }
    .app-header p {
        margin: 0.25rem 0 0 0;
        font-size: 0.88rem;
        opacity: 0.8;
    }

    /* ---------- Metric cards ---------- */
    .metric-card {
        background: #ffffff;
        border-left: 4px solid #1b3a5c;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        margin-bottom: 0.75rem;
    }
    .metric-card .label {
        font-size: 0.78rem;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-weight: 600;
    }
    .metric-card .value {
        font-size: 1.35rem;
        color: #1b3a5c;
        font-weight: 700;
        margin-top: 0.2rem;
    }

    /* ---------- Section headers ---------- */
    .section-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #1b3a5c;
        border-bottom: 2px solid #e5e7eb;
        padding-bottom: 0.5rem;
        margin: 1.25rem 0 1rem 0;
    }

    /* ---------- Info / success / error banners ---------- */
    .banner-success {
        background: linear-gradient(90deg, #059669 0%, #10b981 100%);
        color: #ffffff;
        padding: 1rem 1.25rem;
        border-radius: 8px;
        margin: 0.75rem 0;
        font-weight: 500;
        box-shadow: 0 2px 8px rgba(5, 150, 105, 0.2);
    }
    .banner-error {
        background: linear-gradient(90deg, #dc2626 0%, #ef4444 100%);
        color: #ffffff;
        padding: 1rem 1.25rem;
        border-radius: 8px;
        margin: 0.75rem 0;
        font-weight: 500;
        box-shadow: 0 2px 8px rgba(220, 38, 38, 0.2);
    }
    .banner-warning {
        background: linear-gradient(90deg, #d97706 0%, #f59e0b 100%);
        color: #ffffff;
        padding: 1rem 1.25rem;
        border-radius: 8px;
        margin: 0.75rem 0;
        font-weight: 500;
    }
    .banner-info {
        background: linear-gradient(90deg, #1b3a5c 0%, #2563eb 100%);
        color: #ffffff;
        padding: 1rem 1.25rem;
        border-radius: 8px;
        margin: 0.75rem 0;
        font-weight: 500;
    }

    /* ---------- Submission result ---------- */
    .result-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }
    .result-card .batch-number {
        font-size: 1.8rem;
        font-weight: 700;
        color: #059669;
    }
    .result-card .result-label {
        font-size: 0.82rem;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.4px;
    }
    .result-card .result-value {
        font-size: 1rem;
        color: #1e293b;
        font-weight: 500;
    }

    /* ---------- Buttons ---------- */
    div.stButton > button {
        border-radius: 6px;
        font-weight: 600;
        font-family: 'Inter', sans-serif;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }

    /* Primary action button */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #1b3a5c, #2563eb);
        color: #ffffff;
    }

    /* ---------- Dataframe / table ---------- */
    .stDataFrame {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        overflow: hidden;
    }

    /* ---------- Footer ---------- */
    .app-footer {
        text-align: center;
        color: #9ca3af;
        font-size: 0.78rem;
        padding: 2rem 0 1rem 0;
        border-top: 1px solid #e5e7eb;
        margin-top: 2rem;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
"""


def render_header(branch_id: str = "", user: str = "") -> None:
    """Render the top header bar."""
    branch_display = f"Branch: {branch_id}" if branch_id else ""
    user_display = f"User: {user}" if user else ""
    meta = " | ".join(filter(None, [branch_display, user_display]))

    st.markdown(
        f"""
        <div class="app-header">
            <h1>🏦 Refinance Management</h1>
            <p>{meta}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    """Render the page footer."""
    st.markdown(
        """
        <div class="app-footer">
            Refinance Management Module — Phase 1 &nbsp;|&nbsp; Internal Use Only
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str) -> str:
    """Return HTML for a single metric card."""
    return f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
    </div>
    """


def section_header(title: str) -> None:
    """Render a styled section header."""
    st.markdown(f'<div class="section-header">{title}</div>', unsafe_allow_html=True)
