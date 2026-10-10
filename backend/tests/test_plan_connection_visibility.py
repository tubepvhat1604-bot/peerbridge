"""Connection writes must be readable when their success response is sent."""

import asyncio
import json

import httpx
import pytest
from app.db import database
from app.main import app
from test_plans_api import flow as plan_flow_fixture
from test_plans_api import headers

flow = plan_flow_fixture


@pytest.mark.parametrize("action,status", [("accept", "MATCHED"), ("reject", "REJECTED")])
def test_connection_success_is_committed_before_response_body(flow, action, status):
    visible_statuses = []

    async def observed_app(scope, receive, send):
        async def observe_send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                body = json.loads(message["body"])
                with database() as db:
                    row = db.execute("SELECT status FROM connection_requests WHERE id=?", (body["id"],)).fetchone()
                visible_statuses.append(row["status"] if row else None)
            await send(message)

        await app(scope, receive, observe_send)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=observed_app), base_url="http://test") as client:
            created = await client.post("/api/v1/connections", headers=headers(), json={"recipient_id": 103})
            assert created.status_code == 201
            response = await client.post(f"/api/v1/connections/{created.json()['id']}/{action}", headers=headers(103))
            assert response.status_code == 200

    asyncio.run(exercise())
    assert visible_statuses == ["PENDING", status]
