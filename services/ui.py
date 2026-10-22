"""Shared dark fuel-market theme and authenticated sidebar."""

from html import escape

import plotly.io as pio
import streamlit as st

from services.auth_service import current_user


FUEL_THEME = """
<style>
    :root {
        --fuel-bg: #0b1420;
        --fuel-panel: #111e2d;
        --fuel-panel-raised: #172638;
        --fuel-ink: #edf4f8;
        --fuel-muted: #9aabba;
        --fuel-teal: #1ba6a6;
        --fuel-amber: #f1b844;
        --fuel-border: #293b4e;
    }
    .stApp { background: var(--fuel-bg); color: var(--fuel-ink); }
    [data-testid="stHeader"] { background: rgba(11,20,32,.94); }
    [data-testid="stAppViewContainer"] { background: var(--fuel-bg); }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1320px; }
    h1, h2, h3, h4 { color: var(--fuel-ink); letter-spacing: -.02em; }
    p, li, label, [data-testid="stWidgetLabel"] { color: #d5e0e8; }
    a { color: #52cfcb !important; }
    [data-testid="stMetric"] {
        background: var(--fuel-panel);
        border: 1px solid var(--fuel-border);
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: 0 4px 18px rgba(0,0,0,.12);
    }
    [data-testid="stMetricLabel"] { color: #aab9c6; }
    [data-testid="stMetricValue"] { color: #f5f8fb; }
    [data-testid="stMetricDelta"] { color: #60d4b4; }
    [data-testid="stForm"] {
        background: var(--fuel-panel);
        border: 1px solid var(--fuel-border);
        border-radius: 16px;
        padding: 1.25rem;
    }
    [data-testid="stTextInput"] input {
        border-radius: 9px;
        background: #0d1927;
        color: var(--fuel-ink);
        border-color: #3a4e62;
    }
    [data-testid="stTextInput"] input::placeholder { color: #8294a4; }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        background: var(--fuel-panel);
        border: 1px solid var(--fuel-border);
        border-radius: 12px;
    }
    [data-testid="stPlotlyChart"] {
        background: var(--fuel-panel);
        border: 1px solid var(--fuel-border);
        border-radius: 14px;
        padding: 5px;
    }
    [data-testid="stAlert"] {
        background: #172638;
        border: 1px solid #38546c;
        border-radius: 12px;
        color: #e4edf4;
    }
    [data-testid="stAlert"] p { color: #e4edf4; }
    .stButton > button, [data-testid="stFormSubmitButton"] button {
        border-radius: 9px;
        font-weight: 650;
        border-color: #38546c;
    }
    .stButton > button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"] {
        background: var(--fuel-teal) !important;
        border-color: var(--fuel-teal) !important;
        color: #06181d !important;
    }
    [data-baseweb="tab"] { color: #aebdca; }
    [data-baseweb="tab"][aria-selected="true"] { color: var(--fuel-amber) !important; }
    [data-baseweb="tab-highlight"] { background: var(--fuel-amber) !important; }
    [data-testid="stSidebar"] {
        background: #08121e;
        border-right: 1px solid #203347;
    }
    [data-testid="stSidebar"] * { color: #e5edf3; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #b7c5d0; }
    [data-testid="stSidebar"] button { border-color: #36516a; }
    .fuel-sidebar-brand {
        display: flex; align-items: center; gap: 11px;
        padding: 16px 4px; margin: 8px 0 12px;
        border-bottom: 1px solid #253b50;
    }
    .fuel-sidebar-mark {
        display: grid; place-items: center; width: 39px; height: 39px;
        border-radius: 11px; background: var(--fuel-amber); color: #102235 !important;
        font: 800 14px/1 system-ui, sans-serif; letter-spacing: .04em;
    }
    .fuel-sidebar-title { color: white; font: 700 15px/1.15 system-ui, sans-serif; }
    .fuel-sidebar-subtitle { color: #9fb2c2; font: 500 10px/1.4 system-ui, sans-serif; letter-spacing: .13em; margin-top: 4px; }
    .fuel-sidebar-status {
        background: #142638; border: 1px solid #29475e; border-radius: 10px;
        padding: 11px 12px; margin: 8px 0 15px; color: #c8d6e1;
        font: 500 12px/1.5 system-ui, sans-serif;
    }
    .fuel-eyebrow {
        color: #51ceca; font-size: .75rem; font-weight: 750;
        letter-spacing: .16em; text-transform: uppercase; margin-bottom: .8rem;
    }
    .fuel-auth-hero {
        min-height: 420px; box-sizing: border-box; padding: 38px;
        border: 1px solid #29445a; border-bottom: 5px solid var(--fuel-amber);
        border-radius: 20px; background: #101f30; color: #eef5fa;
        display: flex; flex-direction: column; justify-content: center;
    }
    .fuel-auth-hero * { color: inherit; }
    .fuel-auth-hero .hero-mark {
        display: grid; place-items: center; width: 50px; height: 50px;
        border-radius: 14px; background: var(--fuel-amber); color: #102235;
        font: 800 16px/1 system-ui, sans-serif; margin-bottom: 23px;
    }
    .fuel-auth-hero .hero-kicker { color: #72d1cd; font-size: .78rem; font-weight: 750; letter-spacing: .16em; text-transform: uppercase; }
    .fuel-auth-hero h1 { color: #fff; font-size: clamp(2rem, 4vw, 3.2rem); line-height: 1.08; margin: .55rem 0 1rem; }
    .fuel-auth-hero p { color: #c5d2dc; line-height: 1.7; max-width: 37rem; }
    .fuel-auth-points { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 20px; }
    .fuel-auth-points span { border: 1px solid #36536b; background: #172f44; border-radius: 999px; padding: 7px 11px; color: #dce8f0; font-size: .78rem; }
    @media (max-width: 760px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; }
        .fuel-auth-hero { min-height: 0; padding: 25px; }
    }
</style>
"""

HIDE_SIDEBAR = """
<style>
    section[data-testid="stSidebar"],
    button[data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }
</style>
"""


def apply_fuel_theme() -> None:
    """Apply dark styling and show the branded sidebar for signed-in users."""
    pio.templates.default = "plotly_dark"
    st.markdown(FUEL_THEME, unsafe_allow_html=True)
    user = current_user()
    if not user:
        st.markdown(HIDE_SIDEBAR, unsafe_allow_html=True)
        return
    safe_email = escape(user["email"])
    st.sidebar.markdown(
        "<div class='fuel-sidebar-brand'>"
        "<div class='fuel-sidebar-mark'>FP</div>"
        "<div><div class='fuel-sidebar-title'>Fuel Insights</div>"
        "<div class='fuel-sidebar-subtitle'>INDIA · PRICE ANALYTICS</div></div></div>"
        f"<div class='fuel-sidebar-status'>SIGNED IN<br><strong>{safe_email}</strong></div>",
        unsafe_allow_html=True,
    )
