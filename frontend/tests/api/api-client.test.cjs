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
    exports,
    fetch,
    JSON,
    process: { env: { NEXT_PUBLIC_API_URL: "http://backend.test" } },
  });
  return exports;
}

const matchResult = { request_id: 7, candidates: [] };
const connections = { incoming: [], sent: [], connected: [] };
const connection = {
  id: 12,
  requester_id: 1,
  recipient_id: 2,
  status: "PENDING",
  created_at: "2026-10-03T00:00:00+00:00",
  responded_at: null,
  peer_match_id: null,
};

const cases = [
  { method: "searchMatches", args: [], route: "/matches/search", verb: "POST", response: matchResult, status: 201 },
  { method: "matchResult", args: [7], route: "/matches/7", verb: "GET", response: matchResult },
  { method: "listConnections", args: [], route: "/connections", verb: "GET", response: connections },
  { method: "requestConnection", args: [{ recipient_id: 2 }], route: "/connections", verb: "POST", body: { recipient_id: 2 }, response: connection, status: 201 },
  { method: "acceptConnection", args: [12], route: "/connections/12/accept", verb: "POST", response: { ...connection, status: "MATCHED", peer_match_id: 9 } },
  { method: "rejectConnection", args: [12], route: "/connections/12/reject", verb: "POST", response: { ...connection, status: "REJECTED" } },
];

for (const scenario of cases) {
  test(`${scenario.method}: REST contract, Bearer token and response`, async () => {
    const { api } = loadClient(async (url, options) => {
      assert.equal(url, `http://backend.test/api/v1${scenario.route}`);
      assert.equal(options.method ?? "GET", scenario.verb);
      assert.equal(options.headers.Authorization, "Bearer session-token");
      if (scenario.body) {
        assert.deepEqual(JSON.parse(options.body), scenario.body);
      } else {
        assert.equal(options.body, undefined);
      }
      return new Response(JSON.stringify(scenario.response), { status: scenario.status ?? 200 });
    });
    const result = await api[scenario.method]("session-token", ...scenario.args);
    assert.deepEqual(result, scenario.response);
  });
}

for (const status of [401, 403, 404, 409, 422, 500]) {
  test(`HTTP ${status}: preserves ApiError and only notifies session expiry for 401`, async () => {
    const detail = status === 422 ? [{ msg: "recipient_id must be positive" }] : "Request failed";
    const { api, ApiError, subscribeToUnauthorized } = loadClient(async () =>
      new Response(JSON.stringify({ detail }), { status }),
    );
    const expiredTokens = [];
    const unsubscribe = subscribeToUnauthorized((token) => expiredTokens.push(token));
    await assert.rejects(api.listConnections("session-token"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.equal(error.message, status === 422 ? detail[0].msg : detail);
      return true;
    });
    assert.deepEqual(expiredTokens, status === 401 ? ["session-token"] : []);
    unsubscribe();
    await assert.rejects(api.listConnections("session-token"), ApiError);
    assert.deepEqual(expiredTokens, status === 401 ? ["session-token"] : []);
  });
}

test("failed login does not expire an existing authenticated session", async () => {
  const { api, ApiError, subscribeToUnauthorized } = loadClient(async () =>
    new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 }),
  );
  let notified = false;
  subscribeToUnauthorized(() => { notified = true; });
  await assert.rejects(api.login({ email: "test@example.edu", password: "incorrect" }), ApiError);
  assert.equal(notified, false);
});

test("non-JSON HTTP error retains server message and status", async () => {
  const { api, ApiError } = loadClient(async () => new Response("Service unavailable", { status: 503 }));
  await assert.rejects(api.searchMatches("session-token"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.equal(error.message, "Service unavailable");
    return true;
  });
});

test("network failures reject the request without expiring the session", async () => {
  const networkError = new TypeError("Failed to fetch");
  const { api, subscribeToUnauthorized } = loadClient(async () => { throw networkError; });
  let notified = false;
  subscribeToUnauthorized(() => { notified = true; });
  await assert.rejects(api.searchMatches("session-token"), (error) => error === networkError);
  assert.equal(notified, false);
});
