import streamlit as st

from services.auth_service import render_account_page
from services.ui import apply_fuel_theme


st.set_page_config(page_title="Account", layout="wide", initial_sidebar_state="expanded")
apply_fuel_theme()
render_account_page()
