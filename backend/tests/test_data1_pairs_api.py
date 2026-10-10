import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.config import get_settings
from app.db import connect, database
from app.main import app
from app.matching.repository import PairRepository, code_hash
from app.matching.service import PairError, PairService, get_reranker
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "phase2a.db"))
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    monkeypatch.setenv("JWT_SECRET", "data1-phase2a-test")
    get_settings.cache_clear()
    with TestClient(app, client=(f"phase2a-{uuid4().hex}", 50000)) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_reranker, None)
    get_settings.cache_clear()


def register(client):
    response = client.post("/api/v1/auth/register", json={
        "email": f"phase2a-{uuid4().hex}@example.edu", "password": "password123",
        "display_name": "Phase 2 learner", "age": 22, "city": "Hà Nội", "intent": "conversation"})
    assert response.status_code == 201, response.text
    data = response.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user_id"]


def confirm(client, headers, *, reverse=False, **fields):
    need, offer = ("py.functions", "sql.join") if reverse else ("sql.join", "py.functions")
    payload = {"learning_goal": f"Learn {need}", "committed_weekly_hours": 5,
               "conscientiousness": .8, "procrastination": .3, "communication_style": "PRIVATE style",
               "topics": [{"text": need, "domain": "python" if reverse else "sql", "role": "need"},
                          {"text": offer, "domain": "sql" if reverse else "python", "role": "offer", "self_level": "strong"}],
               "availability": [{"day_of_week": d, "start_time": "19:00", "end_time": "20:00"} for d in (1, 3)],
               **fields}
    draft_response = client.post("/api/v1/profile", headers=headers, json=payload)
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    response = client.post("/api/v1/profile/confirm", headers=headers,
                           json={"revision": draft["revision"], "selections": [
                               {"topic_index": 0, "concept_id": need}, {"topic_index": 1, "concept_id": offer}]})
    assert response.status_code == 200, response.text
    return response.json()


def members(client):
    a, a_id = register(client)
    b, b_id = register(client)
    confirm(client, a)
    confirm(client, b, reverse=True)
    return a, a_id, b, b_id


def create_invite(client, headers, **fields):
    response = client.post("/api/v1/pairs/invite", headers=headers, json=fields)
    assert response.status_code == 201, response.text
    return response.json()


def test_matching_uses_confirmed_profiles_and_requires_both_queue_opt_ins(client):
    a, a_id, b, b_id = members(client)
    first = client.post("/api/v1/pairs/match", headers=a)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["status"] == "waiting" and data["pair"] is None
    assert [c["candidate_user_id"] for c in data["candidates"]] == [b_id]
    assert data["candidates"][0]["component_scores"]["reciprocal_complementarity"] == 1
    assert data["candidates"][0]["total_score"] == pytest.approx(.75)
    assert "PRIVATE" not in first.text and "procrastination" not in first.text
    second = client.post("/api/v1/pairs/match", headers=b)
    assert second.status_code == 200, second.text
    pair = second.json()["pair"]
    assert pair["id"] == pair["peer_match_id"] and {pair["user_a"], pair["user_b"]} == {a_id, b_id}
    assert pair["source"] == "automatic"
    repeat = client.post("/api/v1/pairs/match", headers=a).json()
    assert repeat["pair"] == pair
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pair_memberships").fetchone()[0] == 2


def test_greedy_selects_highest_waiting_candidate_without_pairing_nonconsenting_peers(client):
    a, a_id = register(client)
    b, b_id = register(client)
    c, c_id = register(client)
    confirm(client, a)
    confirm(client, b, reverse=True, committed_weekly_hours=10)
    confirm(client, c, reverse=True)
    # Seed explicit opt-ins without triggering an earlier pair; this models waiting requests.
    with database() as conn:
        repo = PairRepository(conn)
        repo.enqueue(b_id, datetime.now(UTC))
        repo.enqueue(c_id, datetime.now(UTC))
    result = client.post("/api/v1/pairs/match", headers=a).json()
    assert result["candidates"][0]["candidate_user_id"] == c_id
    assert {result["pair"]["user_a"], result["pair"]["user_b"]} == {a_id, c_id}


def test_drafts_legacy_only_seed_admin_and_blocked_candidates_excluded(client):
    a, _, b, b_id = members(client)
    legacy, _ = register(client)
    assert client.post("/api/v1/pairs/match", headers=legacy).status_code == 409
    with database() as conn:
        conn.execute("UPDATE onboarding_profiles SET status='draft' WHERE user_id=?", (b_id,))
    assert client.post("/api/v1/pairs/match", headers=a).json()["candidates"] == []
    with database() as conn:
        conn.execute("UPDATE onboarding_profiles SET status='confirmed' WHERE user_id=?", (b_id,))
        conn.execute("UPDATE users SET is_seed=1 WHERE id=?", (b_id,))
    assert client.post("/api/v1/pairs/match", headers=a).json()["candidates"] == []
    with database() as conn:
        conn.execute("UPDATE users SET is_seed=0,role='INSTRUCTOR' WHERE id=?", (b_id,))
    assert client.post("/api/v1/pairs/match", headers=a).json()["candidates"] == []
    assert client.post("/api/v1/pairs/match", headers=b).status_code == 403


def test_blocks_are_respected_by_matching_and_friend_links(client):
    a, a_id, b, b_id = members(client)
    invite = create_invite(client, a)
    with database() as conn:
        conn.execute("INSERT INTO blocks(blocker_id,blocked_id,created_at) VALUES(?,?,?)",
                     (b_id, a_id, datetime.now(UTC).isoformat()))
    assert client.post("/api/v1/pairs/match", headers=a).json()["candidates"] == []
    assert client.post(invite["join_path"], headers=b).status_code == 403


def test_invitation_join_retry_ownership_pair_reads_and_legacy_sessions(client):
    a, a_id, b, b_id = members(client)
    outsider, _ = register(client)
    invite = create_invite(client, a, target_user_id=b_id)
    assert invite["owner_user_id"] == a_id and len(invite["code"]) >= 40
    assert client.post(invite["join_path"]).status_code == 401
    assert client.post(invite["join_path"], headers=a).status_code == 403
    assert client.post(invite["join_path"], headers=outsider).status_code == 403
    response = client.post(invite["join_path"], headers=b)
    assert response.status_code == 200, response.text
    pair = response.json()
    assert client.post(invite["join_path"], headers=b).json() == pair
    assert pair["source"] == "invitation" and pair["match_level"] == "complementary"
    assert client.get(f"/api/v1/pairs/{pair['id']}", headers=outsider).status_code == 403
    assert client.get(f"/api/v1/pairs/{pair['id']}", headers=a).json() == pair
    assert client.get(f"/api/v1/pairs/{pair['id']}/concept-profiles", headers=b).status_code == 200
    connections = client.get("/api/v1/connections", headers=a).json()
    assert connections["connected"][0]["peer_match_id"] == pair["id"]
    session = client.post("/api/v1/sessions", headers=a, json={
        "peer_match_id": pair["id"], "learner_id": a_id, "helper_id": b_id, "topic": "SQL JOIN"})
    assert session.status_code == 201, session.text
    assert client.get(f"/api/v1/sessions/{session.json()['id']}", headers=b).status_code == 200
    with database() as conn:
        row = conn.execute("SELECT * FROM pair_invitations").fetchone()
        assert row["code_hash"] == code_hash(invite["code"]) and invite["code"] not in str(dict(row))


def test_invitation_expiry_invalid_reuse_and_lifecycle(client):
    a, _, b, _ = members(client)
    c, _ = register(client)
    confirm(client, c)
    invite = create_invite(client, a)
    with database() as conn:
        conn.execute("UPDATE pair_invitations SET expires_at=?", ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),))
    assert client.post(invite["join_path"], headers=b).status_code == 410
    assert client.post("/api/v1/pairs/join/" + "x" * 43, headers=b).status_code == 404
    fresh = create_invite(client, a)
    pair = client.post(fresh["join_path"], headers=b).json()
    assert client.post(fresh["join_path"], headers=c).status_code == 409
    assert client.post("/api/v1/pairs/invite", headers=a, json={}).status_code == 409
    assert client.post(f"/api/v1/pairs/{pair['id']}/leave", headers=c).status_code == 403
    ended = client.post(f"/api/v1/pairs/{pair['id']}/leave", headers=b)
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    assert client.post(f"/api/v1/pairs/{pair['id']}/leave", headers=b).json() == ended.json()
    assert client.post(fresh["join_path"], headers=b).status_code == 409
    assert create_invite(client, a)["owner_user_id"] == pair["user_a"]


def test_invitation_revocation_requires_owner_and_self_target_rejected(client):
    a, a_id, b, _ = members(client)
    assert client.post("/api/v1/pairs/invite", headers=a, json={"target_user_id": a_id}).status_code == 422
    invite = create_invite(client, a)
    path = f"/api/v1/pairs/invitations/{invite['invitation_id']}"
    assert client.delete(path, headers=b).status_code == 403
    assert client.delete(path, headers=a).status_code == 204
    assert client.post(invite["join_path"], headers=b).status_code == 409


def test_existing_peer_identity_and_pending_connection_are_reused(client):
    a, a_id, b, b_id = members(client)
    pending = client.post("/api/v1/connections", headers=a, json={"recipient_id": b_id}).json()
    invite = create_invite(client, a)
    pair = client.post(invite["join_path"], headers=b).json()
    with database() as conn:
        assert conn.execute("SELECT connection_request_id FROM peer_matches WHERE id=?", (pair["id"],)).fetchone()[0] == pending["id"]
    assert client.post(f"/api/v1/connections/{pending['id']}/accept", headers=b).status_code == 409
    client.post(f"/api/v1/pairs/{pair['id']}/leave", headers=a)
    new_invite = create_invite(client, a)
    assert client.post(new_invite["join_path"], headers=b).json()["id"] == pair["id"]
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM peer_matches WHERE user_a_id=? AND user_b_id=?", (a_id, b_id)).fetchone()[0] == 1


def test_legacy_accepted_pair_can_gain_a_data1_extension(client):
    a, _, b, b_id = members(client)
    pending = client.post("/api/v1/connections", headers=a, json={"recipient_id": b_id}).json()
    legacy = client.post(f"/api/v1/connections/{pending['id']}/accept", headers=b).json()
    invite = create_invite(client, a)
    assert client.post(invite["join_path"], headers=b).json()["id"] == legacy["peer_match_id"]


def test_friend_invitation_is_not_automatic_eligibility_or_fabricated_schedule(client):
    a, _, b, _ = members(client)
    confirm(client, b, availability=[], committed_weekly_hours=20)
    assert client.post("/api/v1/pairs/match", headers=a).json()["candidates"] == []
    pair = client.post(create_invite(client, a)["join_path"], headers=b).json()
    assert pair["match_result"]["facts"]["common_slots"] == []
    assert "0 weekly study slots" in pair["match_reason"]
    assert pair["match_result"]["facts"]["weekly_hours_ratio"] == 4


def test_confirmation_required_at_join_and_new_profile_revision_during_rerank(client):
    a, _, b, b_id = members(client)
    invite = create_invite(client, a)
    with database() as conn:
        conn.execute("UPDATE onboarding_profiles SET status='draft' WHERE user_id=?", (b_id,))
    assert client.post(invite["join_path"], headers=b).status_code == 409
    with database() as conn:
        conn.execute("UPDATE onboarding_profiles SET status='confirmed' WHERE user_id=?", (b_id,))
    assert client.post("/api/v1/pairs/match", headers=b).json()["status"] == "waiting"

    class ChangingProvider:
        backend = "test_local"

        async def rerank(self, candidates):
            with database() as conn:
                conn.execute("UPDATE onboarding_profiles SET revision=revision+1 WHERE user_id=?", (b_id,))
            return {"candidates": [{"candidate_user_id": b_id, "rating": 5, "match_level": "complementary"}]}
    app.dependency_overrides[get_reranker] = lambda: ChangingProvider()
    assert client.post("/api/v1/pairs/match", headers=a).status_code == 409
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 0


def test_time_based_fallback_preserves_first_wait_and_cancellation(client):
    a, a_id = register(client)
    confirm(client, a)
    now = datetime(2026, 10, 6, 8, tzinfo=UTC)
    with database() as conn:
        service = PairService(PairRepository(conn), clock=lambda: now)
        first = asyncio.run(service.match(a_id))
        service.clock = lambda: now + timedelta(hours=23, minutes=59)
        assert asyncio.run(service.match(a_id)).status == "waiting"
        service.clock = lambda: now + timedelta(hours=24)
        result = asyncio.run(service.match(a_id))
        assert result.status == "invite_suggested" and result.waiting_since == first.waiting_since
        assert result.fallback_actions == ["invite_friend", "manual_concierge"]
        service.cancel_matching(a_id)
        assert not service.repository.waiting(a_id)
        assert asyncio.run(service.match(a_id)).status == "waiting"
    assert client.delete("/api/v1/pairs/match", headers=a).status_code == 204


def test_qualified_candidate_prevents_fallback_and_below_threshold_never_auto_pairs(client):
    a, a_id, b, b_id = members(client)
    now = datetime(2026, 10, 6, 8, tzinfo=UTC)
    with database() as conn:
        service = PairService(PairRepository(conn), clock=lambda: now)
        asyncio.run(service.match(a_id))
        service.clock = lambda: now + timedelta(hours=24)
        assert asyncio.run(service.match(a_id)).status == "waiting"
        # Remove mutual offers; different learning concepts leave only schedule+commitment = .4.
        conn.execute("DELETE FROM user_concepts WHERE role='offer'")
        assert asyncio.run(service.match(b_id)).status == "waiting"
        assert asyncio.run(service.match(a_id)).status == "invite_suggested"
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 0


def test_invalid_llm_candidate_cannot_bypass_api_hard_filters(client):
    a, _, b, b_id = members(client)
    confirm(client, b, availability=[])

    class InvalidProvider:
        backend = "test_local"

        async def rerank(self, candidates):
            raise AssertionError("No eligible candidates means no provider call")
    app.dependency_overrides[get_reranker] = lambda: InvalidProvider()
    response = client.post("/api/v1/pairs/match", headers=a)
    assert response.status_code == 200 and response.json()["candidates"] == []
    assert response.json()["reranking"]["status"] == "disabled"
    assert b_id not in [c["candidate_user_id"] for c in response.json()["candidates"]]


@pytest.mark.parametrize("mutation", ["draft", "theta"])
def test_all_candidate_facts_are_rechecked_after_provider_even_without_partner_queue(client, mutation):
    a, _, _, b_id = members(client)

    class MutatingProvider:
        backend = "test_local"

        async def rerank(self, candidates):
            with database() as conn:
                if mutation == "draft":
                    conn.execute("UPDATE onboarding_profiles SET status='draft' WHERE user_id=?", (b_id,))
                else:
                    # Simulates a future measured-theta write; does not implement Elo or measurement.
                    conn.execute("UPDATE user_concepts SET theta=-1 WHERE user_id=? AND role='offer'", (b_id,))
            return {"candidates": [{"candidate_user_id": b_id, "rating": 5, "match_level": "complementary"}]}
    app.dependency_overrides[get_reranker] = lambda: MutatingProvider()
    response = client.post("/api/v1/pairs/match", headers=a)
    assert response.status_code == 409
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM pair_match_queue").fetchone()[0] == 0


def test_transaction_rolls_back_pair_bridge_and_invitation_use_failure(client, monkeypatch):
    a, _, b, _ = members(client)
    invite = create_invite(client, a)

    def fail(*args):
        raise RuntimeError("injected failure")
    monkeypatch.setattr(PairRepository, "use_invitation", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        client.post(invite["join_path"], headers=b)
    with database() as conn:
        for table in ("pairs", "pair_memberships", "peer_matches", "connection_requests"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM pair_invitations").fetchone()[0] == "pending"


def test_simultaneous_invitation_join_cannot_create_duplicate_active_pairs(client):
    a, _, b, b_id = members(client)
    c, c_id = register(client)
    confirm(client, c)
    invite = create_invite(client, a)
    path = get_settings().database_file

    def join(user_id):
        conn = connect(path)
        try:
            result = PairService(PairRepository(conn)).join(user_id, invite["code"])
            conn.commit()
            return result.id
        except PairError:
            conn.rollback()
            return None
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(join, (b_id, c_id)))
    assert len([i for i in ids if i is not None]) == 1
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM pairs").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pair_memberships").fetchone()[0] == 2


def test_no_raw_profile_edits_or_match_requests_from_new_matching(client):
    a, _, b, _ = members(client)
    before = client.get("/api/v1/profiles/me", headers=a).json()
    client.post("/api/v1/pairs/match", headers=a)
    assert client.get("/api/v1/profiles/me", headers=a).json() == before
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM match_requests").fetchone()[0] == 0
        # SQLite uniqueness enforces one active Data 1 pair per account at the persistence boundary.
        assert "user_id" in [r[1] for r in conn.execute("PRAGMA table_info(pair_memberships)") if r[5] == 1]
