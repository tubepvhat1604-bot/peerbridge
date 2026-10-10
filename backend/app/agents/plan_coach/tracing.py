"""Allowlisted metadata only. Plan tracing is isolated from automatic LangGraph traces."""

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from langsmith import tracing_context


def safe_usage(value):
    if not isinstance(value, dict):
        return None
    allowed = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
    return {k: v for k, v in value.items() if k in allowed and type(v) is int and v >= 0}


def identifier(value):
    return isinstance(value, str) and "://" not in value and bool(re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}", value))


def valid_endpoint(value):
    try:
        url = urlsplit(value)
        return bool(
            url.scheme == "https" and url.hostname and not (url.username or url.password or url.query or url.fragment)
        )
    except ValueError:
        return False


def metadata(body, links):
    clean = {}
    for key in ("prompt_version", "model", "provider_mode", "mode"):
        if identifier(body.get(key)):
            clean[key] = body[key]
    for key in ("repairs", "request_count"):
        if type(body.get(key)) is int and body[key] >= 0:
            clean[key] = body[key]
    if isinstance(body.get("latency_ms"), (int, float)) and 0 <= body["latency_ms"] < 1e8:
        clean["latency_ms"] = body["latency_ms"]
    if body.get("action") in ("reminder", "replan", "pair_replan", "offer_support", "no_action"):
        clean["action"] = body["action"]
    clean["fallback"] = body.get("mode") == "v1_fallback"
    clean["usage"] = safe_usage(body.get("usage"))
    clean["attempts"] = []
    for attempt in body.get("attempts", [])[:3]:
        if not isinstance(attempt, dict):
            continue
        clean["attempts"].append(
            {
                "attempt": attempt.get("attempt") if type(attempt.get("attempt")) is int else None,
                "latency_ms": attempt.get("latency_ms")
                if isinstance(attempt.get("latency_ms"), (int, float))
                else None,
                "usage": safe_usage(attempt.get("usage")),
                "error_codes": [
                    e["code"]
                    for e in attempt.get("errors", [])
                    if isinstance(e, dict) and re.fullmatch(r"[A-Z_]{1,80}", str(e.get("code", "")))
                ],
            }
        )
    clean["validator_error_codes"] = [
        e["code"]
        for e in body.get("validation_errors", [])
        if isinstance(e, dict) and re.fullmatch(r"[A-Z_]{1,80}", str(e.get("code", "")))
    ]
    error = body.get("error")
    if error in (
        "INVALID_ACTION",
        "INVALID_MESSAGE",
        "TimeoutError",
        "ValueError",
        "ValidationError",
        "BudgetExhaustedError",
        "selector_unavailable",
    ):
        clean["error_code"] = error
    for key in ("plan_id", "plan_version", "proposal_id", "intervention_id", "db_trace_id"):
        value = links.get(key)
        if type(value) is int and value > 0:
            clean[key] = value
        elif isinstance(value, str):
            try:
                clean[key] = str(UUID(value))
            except ValueError:
                pass
    if isinstance(links.get("plan_ids"), list):
        clean["plan_ids"] = [v for v in links["plan_ids"][:2] if type(v) is int and v > 0]
    return clean


class NoopTrace:
    def emit(self, kind, body, links=None):
        return {"provider": "none", "status": "NOT_CONFIGURED", "external_confirmed": False, "request_count": 0}


class LangSmithTrace:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    def emit(self, kind, body, links=None):
        run_id, end = str(uuid4()), datetime.now(UTC)
        clean = metadata(body, links or {})
        secrets = [
            s.get_secret_value()
            for s in (self.settings.trace_api_key, self.settings.llm_api_key, self.settings.vision_adapter_key)
            if s.get_secret_value()
        ]
        clean = {k: v for k, v in clean.items() if not any(secret in str(v) for secret in secrets)}
        payload = {
            "id": run_id,
            "name": "peerbridge-plan" if kind.startswith("planner") else "peerbridge-coach",
            "run_type": "chain",
            "inputs": {},
            "outputs": {},
            "session_name": self.settings.trace_project
            if not any(secret in self.settings.trace_project for secret in secrets)
            else "peerbridge-plan-coach",
            "start_time": (end - timedelta(milliseconds=clean.get("latency_ms", 0))).isoformat(),
            "extra": {"metadata": clean},
        }
        result = {
            "provider": "langsmith",
            "run_id": run_id,
            "status": "FAILED",
            "external_confirmed": False,
            "request_count": 0,
        }
        if not valid_endpoint(self.settings.trace_endpoint) or not self.settings.trace_api_key.get_secret_value():
            return {**result, "status": "NOT_CONFIGURED"}
        try:
            with httpx.Client(
                timeout=self.settings.trace_timeout_seconds, transport=self.transport, follow_redirects=False
            ) as client:
                headers = {"x-api-key": self.settings.trace_api_key.get_secret_value()}
                if self.settings.trace_workspace_id:
                    headers["x-tenant-id"] = self.settings.trace_workspace_id
                base = self.settings.trace_endpoint.rstrip("/")
                result["request_count"] += 1
                response = client.post(base + "/runs", json=payload, headers=headers)
                response.raise_for_status()
                result["request_count"] += 1
                response = client.patch(
                    base + "/runs/" + run_id, json={"end_time": end.isoformat(), "outputs": {}}, headers=headers
                )
                response.raise_for_status()
                result["status"] = "ACCEPTED_UNVERIFIED"
                if self.settings.trace_verify:
                    result["request_count"] += 1
                    response = client.get(base + "/runs/" + run_id, headers=headers)
                    response.raise_for_status()
                    if str(response.json().get("id")) == run_id:
                        result.update(status="CONFIRMED", external_confirmed=True)
        except Exception as error:
            result["error_code"] = (
                f"HTTP_{error.response.status_code}"
                if isinstance(error, httpx.HTTPStatusError)
                else type(error).__name__
            )
        return result


def make_trace(settings):
    key = settings.trace_api_key.get_secret_value().strip()
    placeholder = not key or any(x in key.lower() for x in ("xxxxx", "your-", "your_", "placeholder"))
    if settings.trace_provider == "none" or placeholder:
        return NoopTrace()
    return LangSmithTrace(settings)


def emit_trace(settings, kind, body, links=None):
    # Tracing never prevents saving a valid plan/decision, even with malformed metadata.
    try:
        return make_trace(settings).emit(kind, body, links)
    except Exception:
        return {"provider": "langsmith", "status": "FAILED", "external_confirmed": False}


def private_graph_context():
    return tracing_context(enabled=False)


def export_db_trace(settings, kind, body, trace_id, links=None):
    from ...db import database

    status = emit_trace(settings, kind, body, {**(links or {}), "db_trace_id": trace_id})
    try:
        import json

        with database() as db:
            row = db.execute("SELECT body FROM pb_traces WHERE id=?", (trace_id,)).fetchone()
            if row:
                stored = json.loads(row[0])
                stored["external_trace"] = status
                db.execute("UPDATE pb_traces SET body=? WHERE id=?", (json.dumps(stored, ensure_ascii=False), trace_id))
    except Exception:
        pass
    return status
