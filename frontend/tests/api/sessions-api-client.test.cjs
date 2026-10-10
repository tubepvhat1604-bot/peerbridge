const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const source = readFileSync(path.join(__dirname, "../../lib/api.ts"), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
});

function loadClient(fetch) {
  const exports = {};
  vm.runInNewContext(outputText, {
    exports, fetch, JSON, process: { env: { NEXT_PUBLIC_API_URL: "http://backend.test" } },
  });
  return exports;
}

// Contract fixtures only; application functions always call the backend.
const session = {
  id: 17, peer_match_id: 9, learner_id: 2, helper_id: 1, topic: "Limits",
  scheduled_start: null, scheduled_end: null, created_at: null, updated_at: null,
};
const connection = {
  peer_match_id: 9, connection_request_id: 12, requester_id: 1, recipient_id: 2,
  connected_at: "2026-10-03T00:00:00Z",
  peer: { user_id: 2, display_name: "Peer", school: "", major: "" },
};

test("list and detail use real session routes and retain the Bearer token", async () => {
  const { api } = loadClient(async (url, options) => {
    assert.equal(options.headers.Authorization, "Bearer session-token");
    assert.equal(options.method ?? "GET", "GET");
    if (url === "http://backend.test/api/v1/sessions") {
      return new Response(JSON.stringify({ items: [session], count: 1 }));
    }
    assert.equal(url, "http://backend.test/api/v1/sessions/17");
    return new Response(JSON.stringify({ ...session, chat_messages: [] }));
  });
  assert.deepEqual(await api.listSessions("session-token"), { items: [session], count: 1 });
  assert.equal((await api.session("session-token", 17)).id, 17);
  assert.equal((await api.session("session-token", "17")).id, 17);
});

test("create from a connected peer derives both participant orientations without extra fields", async () => {
  let sent;
  const { api } = loadClient(async (url, options) => {
    assert.equal(url, "http://backend.test/api/v1/sessions");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.Authorization, "Bearer session-token");
    sent = JSON.parse(options.body);
    return new Response(JSON.stringify({ ...session, ...sent, chat_messages: [] }), { status: 201 });
  });
  await api.createSessionFromConnection("session-token", connection, { learner_id: 2, topic: "Limits" });
  assert.deepEqual(sent, { peer_match_id: 9, learner_id: 2, helper_id: 1, topic: "Limits" });
  await api.createSessionFromConnection("session-token", connection, {
    learner_id: 1, topic: "Limits", scheduled_start: null, scheduled_end: null,
  });
  assert.deepEqual(sent, {
    peer_match_id: 9, learner_id: 1, helper_id: 2, topic: "Limits",
    scheduled_start: null, scheduled_end: null,
  });
});

test("invalid connection participants are rejected before sending a request", async () => {
  let calls = 0;
  const { api } = loadClient(async () => { calls++; });
  const details = { learner_id: 1, topic: "Limits" };
  for (const invalid of [
    { ...connection, peer_match_id: 0 },
    { ...connection, requester_id: 1.5 },
    { ...connection, recipient_id: 1 },
  ]) {
    await assert.rejects(api.createSessionFromConnection("token", invalid, details), /valid connected peer/);
  }
  await assert.rejects(
    api.createSessionFromConnection("token", connection, { ...details, learner_id: 3 }), /learner must be a member/,
  );
  assert.equal(calls, 0);
});

test("join eligibility requires a saved session and actual learner/helper membership", () => {
  const { canJoinStudySession } = loadClient(() => {});
  assert.equal(canJoinStudySession(session, 1), true);
  assert.equal(canJoinStudySession(session, 2), true);
  assert.equal(canJoinStudySession(session, 3), false);
  assert.equal(canJoinStudySession(session, 0), false);
  assert.equal(canJoinStudySession({ ...session, id: null }, 1), false);
  assert.equal(canJoinStudySession({ ...session, id: 0 }, 1), false);
});

test("sessions retain ApiError and only notify unauthorized listeners for 401", async () => {
  for (const status of [401, 403, 404, 422]) {
    const { api, ApiError, subscribeToUnauthorized } = loadClient(async () =>
      new Response(JSON.stringify({ detail: "Denied" }), { status }),
    );
    const expired = [];
    subscribeToUnauthorized((token) => expired.push(token));
    const operations = [
      () => api.listSessions("token"),
      () => api.session("token", 17),
      () => api.createSessionFromConnection("token", connection, { learner_id: 1, topic: "Limits" }),
    ];
    for (const operation of operations) {
      await assert.rejects(operation(), (error) => error instanceof ApiError && error.status === status);
    }
    assert.deepEqual(expired, status === 401 ? ["token", "token", "token"] : []);
  }
});
