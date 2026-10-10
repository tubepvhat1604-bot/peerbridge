"""Run from backend: streamlit run measurement_dashboard.py --server.address 127.0.0.1"""

import os
from pathlib import Path

import streamlit as st
from app.metrics.dashboard import render_dashboard

database_path = os.environ.get("METRICS_DASHBOARD_DB")
if not database_path:
    st.error("Set METRICS_DASHBOARD_DB to an existing SQLite database path.")
else:
    render_dashboard(st, Path(database_path))
