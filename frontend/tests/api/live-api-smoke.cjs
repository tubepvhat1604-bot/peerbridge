// Run against an isolated local FastAPI server; all data is created through REST.
const assert = require("node:assert/strict");
const { createHmac, randomUUID } = require("node:crypto");
const { mkdirSync, readFileSync, writeFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const apiUrl = process.env.PEERBRIDGE_SMOKE_API_URL;
const testJwtSecret = process.env.PEERBRIDGE_SMOKE_JWT_SECRET;
if (!apiUrl || new URL(apiUrl).hostname !== "127.0.0.1") {
  throw new Error("Set PEERBRIDGE_SMOKE_API_URL to the isolated local test server.");
}
if (!testJwtSecret) throw new Error("Set PEERBRIDGE_SMOKE_JWT_SECRET to the isolated server's test-only JWT secret.");

const calls = [];
const exportsObject = {};
const { outputText } = ts.transpileModule(readFileSync(path.join(__dirname, "../../lib/api.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
});
vm.runInNewContext(outputText, {
  exports: exportsObject, JSON,
  process: { env: { NEXT_PUBLIC_API_URL: apiUrl } },
  fetch: async (url, options) => {
    const response = await fetch(url, options);
    calls.push({ method: options.method ?? "GET", path: new URL(url).pathname, status: response.status });
    return response;
  },
});
const { api, ApiError, subscribeToUnauthorized } = exportsObject;

async function run() {
  const id = randomUUID();
  const topic = `smoke REST ${id}`;
  const email = (name) => `${name.toLowerCase().replace(/ /g, "-")}-${id}@example.edu`;
  const register = (name) => api.register({
    email: email(name), password: "isolated-demo-password",
    display_name: name, age: 22, city: "Ha Noi", intent: "conversation",
  });
  const registeredLearner = await register("REST Learner");
  const registeredHelper = await register("REST Helper");
  const registeredOther = await register("REST Other");
  const learner = await api.login({ email: email("REST Learner"), password: "isolated-demo-password" });
  const helper = await api.login({ email: email("REST Helper"), password: "isolated-demo-password" });
  const other = await api.login({ email: email("REST Other"), password: "isolated-demo-password" });
  assert.equal(learner.user_id, registeredLearner.user_id);
  assert.equal(helper.user_id, registeredHelper.user_id);
  assert.equal(other.user_id, registeredOther.user_id);
  const update = (session, name, needs, offers) => api.updateProfile(session.access_token, {
    profile: { display_name: name, school: "REST test school", major: "Computer Science", bio: "Isolated REST test", subjects: [], learning_goals: [] },
    needs_help_with: needs.map((topic) => ({ topic, description: "", current_level: "", target_outcome: "" })),
    can_help_with: offers.map((topic) => ({ topic, description: "", proficiency_level: "", max_sessions_per_week: 3 })),
    availability: [],
  });
  await update(learner, "REST Learner", [topic], []);
  await update(helper, "REST Helper", [], [topic]);
  await update(other, "REST Other", [], [topic]);

  const profile = await api.profile(learner.access_token);
  assert.equal(profile.profile.user_id, learner.user_id);
  assert.equal(profile.profile.display_name, "REST Learner");
  assert.equal(profile.needs_help_with[0].topic, topic);
  assert.deepEqual((await api.searchMatches(other.access_token)).candidates, []);

  const matches = await api.searchMatches(learner.access_token);
  assert.ok(matches.candidates.some((candidate) => candidate.candidate_id === helper.user_id));
  assert.ok(matches.candidates.every((candidate) => candidate.total_score >= 0 && candidate.total_score <= 100));
  assert.deepEqual(await api.matchResult(learner.access_token, matches.request_id), matches);

  const pending = await api.requestConnection(learner.access_token, { recipient_id: helper.user_id });
  assert.equal(pending.status, "PENDING");
  assert.equal(pending.peer_match_id, null);
  assert.ok((await api.listConnections(learner.access_token)).sent.some((item) => item.id === pending.id));
  assert.ok((await api.listConnections(helper.access_token)).incoming.some((item) => item.id === pending.id));

  const hasStatus = (status) => (error) => error instanceof ApiError && error.status === status;
  await assert.rejects(api.searchMatches("invalid-token"), hasStatus(401));
  await assert.rejects(api.requestConnection(learner.access_token, { recipient_id: helper.user_id }), hasStatus(409));
  await assert.rejects(api.acceptConnection(learner.access_token, pending.id), hasStatus(403));
  await assert.rejects(api.rejectConnection(learner.access_token, pending.id), hasStatus(403));
  await assert.rejects(api.acceptConnection(other.access_token, pending.id), hasStatus(403));
  await assert.rejects(api.rejectConnection(other.access_token, pending.id), hasStatus(403));
  const accepted = await api.acceptConnection(helper.access_token, pending.id);
  assert.equal(accepted.status, "MATCHED");
  assert.ok(accepted.peer_match_id > 0);
  assert.ok((await api.listConnections(learner.access_token)).connected.some((item) => item.peer_match_id === accepted.peer_match_id));
  assert.ok((await api.listConnections(helper.access_token)).connected.some((item) => item.peer_match_id === accepted.peer_match_id));
  const restoredLogin = await api.login({ email: email("REST Learner"), password: "isolated-demo-password" });
  assert.ok((await api.listConnections(restoredLogin.access_token)).connected.some((item) => item.peer_match_id === accepted.peer_match_id));
  await assert.rejects(api.acceptConnection(helper.access_token, pending.id), hasStatus(409));

  const invitation = await api.requestConnection(learner.access_token, { recipient_id: other.user_id });
  const rejected = await api.rejectConnection(other.access_token, invitation.id);
  assert.equal(rejected.status, "REJECTED");
  assert.equal(rejected.peer_match_id, null);
  assert.ok(!(await api.listConnections(learner.access_token)).sent.some((item) => item.id === invitation.id));
  await assert.rejects(api.acceptConnection(other.access_token, invitation.id), hasStatus(409));
  await assert.rejects(api.listConnections("invalid-token"), hasStatus(401));

  // Signed test fixture: a valid signature with exp=0 exercises actual token expiry.
  // This secret is supplied only for the disposable test server, never the app client.
  const header = learner.access_token.split(".")[0];
  const payload = Buffer.from(JSON.stringify({ sub: String(learner.user_id), exp: 0 })).toString("base64url");
  const body = `${header}.${payload}`;
  const expiredToken = `${body}.${createHmac("sha256", testJwtSecret).update(body).digest("base64url")}`;
  let expiryNotifications = 0;
  const unsubscribe = subscribeToUnauthorized((token) => {
    if (token === expiredToken) expiryNotifications++;
  });
  await assert.rejects(api.listConnections(expiredToken), hasStatus(401));
  unsubscribe();
  assert.equal(expiryNotifications, 1);

  const evidence = JSON.stringify({
    result: "PASS", transport: "real HTTP to an isolated FastAPI server", requests: calls.length,
    checks: ["student login", "profile loading", "matching score", "empty matching", "matching HTTP error", "send invitation", "duplicate rejected", "incoming invitation", "accept MATCHED", "reject REJECTED", "non-recipient accept/reject denied", "fresh login reloads connection", "signed expired token returns 401 and notifies client"],
    unavailable: ["candidate reasons are absent from the backend response", "browser console and mobile visual verification"],
    calls,
  }, null, 2) + "\n";
  mkdirSync(path.join(__dirname, "evidence"), { recursive: true });
  writeFileSync(path.join(__dirname, "evidence/live-rest-result.json"), evidence);
  process.stdout.write(evidence);
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
