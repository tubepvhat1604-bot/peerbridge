import sqlite3

import pytest
from app.metrics.adapters import FixtureMeasurementSource
from app.metrics.dashboard import load_dashboard_rows, render_dashboard
from app.metrics.repository import MetricsRepository
from app.metrics.service import MeasurementService
from test_data1_measurement import NOW, facts
from test_data1_measurement_storage import initialize, seed_pair


class LocalUI:
    def __init__(self):
        self.tables = []
        self.charts = []
        self.errors = []

    def title(self, _): pass
    def caption(self, _): pass
    def subheader(self, _): pass
    def info(self, _): pass
    def error(self, message): self.errors.append(message)
    def checkbox(self, _, value): return value
    def selectbox(self, _, options): return options[0]
    def dataframe(self, rows, **kwargs): self.tables.append(rows)
    def bar_chart(self, values, **kwargs): self.charts.append(values)
    def line_chart(self, rows, **kwargs): self.charts.append(rows)


def test_dashboard_reads_existing_stored_metrics_and_renders_without_private_fields(tmp_path):
    path = tmp_path / "dashboard.db"
    with sqlite3.connect(path) as conn:
        initialize(conn)
        seed_pair(conn)
        MeasurementService(MetricsRepository(conn), FixtureMeasurementSource({1: facts()}), clock=lambda: NOW).recompute(1)
    rows = load_dashboard_rows(path)
    assert rows[0]["pair_score"] == 0 and rows[0]["needs_attention"] is True
    assert "components" not in str(rows) and "reminder" not in str(rows) and "theta" not in str(rows)
    assert "note" not in rows[0] and "image_path" not in rows[0]
    ui = LocalUI()
    render_dashboard(ui, path)
    assert len(ui.tables) == 2 and len(ui.charts) == 2 and not ui.errors
    assert load_dashboard_rows(path, since=NOW.date().replace(day=7)) == []


def test_dashboard_missing_db_never_creates_file_and_empty_state_supported(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(ValueError, match="existing"):
        load_dashboard_rows(path)
    assert not path.exists()
    with sqlite3.connect(path) as conn:
        initialize(conn)
    ui = LocalUI()
    render_dashboard(ui, path)
    assert not ui.tables and not ui.charts and not ui.errors
    with pytest.raises(ValueError, match="limit"):
        load_dashboard_rows(path, limit=10001)
