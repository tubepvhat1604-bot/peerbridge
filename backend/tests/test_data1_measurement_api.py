from uuid import uuid4

import pytest
from app.config import get_settings
from app.db import database
from app.main import app
from app.metrics.adapters import FixtureMeasurementSource
from app.metrics.contracts import RiskObservation
from app.metrics.repository import MetricsRepository
from app.metrics.service import MeasurementService, get_measurement_service
from app.security import create_token
from fastapi.testclient import TestClient
from test_data1_measurement import NOW
from test_data1_measurement_storage import pair_input, seed_pair


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "measurement-api.db"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    monkeypatch.setenv("JWT_SECRET", "measurement-api-test")
    monkeypatch.setenv("DAILY_METRICS_JOB_SECRET", "local-job-test")
    get_settings.cache_clear()
    inputs = {}
    source = FixtureMeasurementSource(inputs)

    def service():
        with database() as connection:
            yield MeasurementService(MetricsRepository(connection), source, clock=lambda: NOW)

    app.dependency_overrides[get_measurement_service] = service
    with TestClient(app, client=(f"measurement-{uuid4().hex}", 50000)) as client:
        with database() as conn:
            seed_pair(conn, 100, 101, 102)
            seed_pair(conn, 200, 103, 104)
            inputs[100] = pair_input(MetricsRepository(conn), 100)
            inputs[200] = pair_input(MetricsRepository(conn), 200)
        yield client, source
    app.dependency_overrides.pop(get_measurement_service, None)
    get_settings.cache_clear()


def member(user_id=101):
    return {"Authorization": "Bearer " + create_token(user_id)}


def test_member_read_refresh_history_and_no_private_risk_fields(api):
    client, source = api
    assert client.get("/api/v1/pairs/100/metrics", headers=member()).status_code == 404
    source.inputs[100].risk_observations = [RiskObservation(user_id=101, observed_at=NOW,
                                                          latest_reminder_responded=False, theta_stagnant=True)]
    response = client.post("/api/v1/pairs/100/metrics/refresh", headers=member())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pair_score"] == 1 and data["gap"] == 0 and data["streak"] == 1
    assert "components" not in data["risk_a"] and "reasons" not in data["risk_a"]
    assert "reminder" not in response.text and "theta" not in response.text
    assert client.get("/api/v1/pairs/100/metrics", headers=member(102)).json() == data
    history = client.get("/api/v1/pairs/100/metrics/history", headers=member()).json()
    assert history["items"] == [data]
    assert client.get("/api/v1/pairs/100/metrics/history?limit=91", headers=member()).status_code == 422


@pytest.mark.parametrize("suffix,method", [("metrics", "get"), ("metrics/history", "get"), ("metrics/refresh", "post")])
def test_unrelated_users_and_anonymous_cannot_read_or_refresh_pair(api, suffix, method):
    client, _ = api
    call = getattr(client, method)
    assert call(f"/api/v1/pairs/100/{suffix}", headers=member(103)).status_code == 403
    assert call(f"/api/v1/pairs/100/{suffix}").status_code == 401
    assert call(f"/api/v1/pairs/999/{suffix}", headers=member()).status_code == 404


def test_job_secret_enforced_and_summary_no_private_data(api):
    client, _ = api
    path = "/jobs/daily-metrics"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=member()).status_code == 401
    assert client.post(path, headers={"X-Job-Secret": "wrong"}).status_code == 401
    response = client.post(path, headers={"X-Job-Secret": "local-job-test"})
    assert response.status_code == 200, response.text
    assert response.json()["snapshots_created"] == 2 and response.json()["pairs_processed"] == 2
    assert "risk_a" not in response.text and "local-job-test" not in response.text
    assert client.post(path, headers={"X-Job-Secret": "local-job-test"}).json()["snapshots_unchanged"] == 2


def test_job_fails_closed_without_config_and_rejects_future_and_oversized_batch(api, monkeypatch):
    client, _ = api
    header = {"X-Job-Secret": "local-job-test"}
    assert client.post("/jobs/daily-metrics", headers=header, json={"study_date": "2026-10-07"}).status_code == 422
    assert client.post("/jobs/daily-metrics", headers=header, json={"limit": 501}).status_code == 422
    monkeypatch.setenv("DAILY_METRICS_JOB_SECRET", "")
    get_settings.cache_clear()
    assert client.post("/jobs/daily-metrics", headers=header).status_code == 503


def test_input_unavailable_and_invalid_input_are_explicit_and_never_write(api):
    client, source = api
    source.inputs.pop(100)
    assert client.post("/api/v1/pairs/100/metrics/refresh", headers=member()).status_code == 503
    source.inputs[200].plan_items[0].concept_id = "unknown.id"
    assert client.post("/api/v1/pairs/200/metrics/refresh", headers=member(103)).status_code == 422
    summary = client.post("/jobs/daily-metrics", headers={"X-Job-Secret": "local-job-test"}).json()
    assert summary["skip_reasons"] == {"input_unavailable": 1, "invalid_input": 1}
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 0


def test_request_transaction_rolls_back_on_unexpected_storage_failure(api, monkeypatch):
    client, _ = api

    def broken(self, context):
        raise RuntimeError("test write failure")

    monkeypatch.setattr(MetricsRepository, "sync_streak", broken)
    with pytest.raises(RuntimeError, match="write failure"):
        client.post("/api/v1/pairs/100/metrics/refresh", headers=member())
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM pair_metrics_daily").fetchone()[0] == 0
        assert conn.execute("SELECT streak FROM pairs WHERE id=100").fetchone()[0] == 0


def test_ended_pair_remains_readable_for_members_but_cannot_refresh(api):
    client, _ = api
    assert client.post("/api/v1/pairs/100/metrics/refresh", headers=member()).status_code == 200
    with database() as conn:
        conn.execute("UPDATE pairs SET status='ended' WHERE id=100")
        conn.execute("DELETE FROM pair_memberships WHERE pair_id=100")
    assert client.get("/api/v1/pairs/100/metrics", headers=member()).status_code == 200
    assert client.post("/api/v1/pairs/100/metrics/refresh", headers=member()).status_code == 409
