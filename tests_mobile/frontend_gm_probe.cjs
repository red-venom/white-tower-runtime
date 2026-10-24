// Offline execution of the shipped script. All data, DOM and HTTP are synthetic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { webcrypto } = require("node:crypto");
const source = fs.readFileSync(path.join(__dirname, "../mobile_game/static/app.js"), "utf8");
const GM = "white-tower-mobile:gm:v1";
const PENDING = "white-tower-mobile:pending:v1";
const OWNER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const CAMPAIGN = "33333333-3333-4333-8333-333333333333";
const REQUEST = "44444444-4444-4444-8444-444444444444";
const CHOICE = { id: "move_inside", label: "Move inside", description: "Move the sample books.", stakes: "No roll; one minute.", choice_hash: "a".repeat(64), requires_roll: false };
const packet = () => ({ id: CAMPAIGN, revision: 0, events: [], capabilities: { gm_assistant: true }, state: { choices: [{ ...CHOICE }], resources: {}, story: "Synthetic sample." } });
const record = (status = "unconfirmed") => ({ player_id: OWNER, campaign_id: CAMPAIGN, request: { request_id: REQUEST, expected_revision: 0, prompt: "Can I move the sample books inside?" }, status });
const result = (saved, status = "completed", kind = "proposal") => ({ request_id: saved.request.request_id, expected_revision: saved.request.expected_revision, status,
  result: status === "completed" ? { kind, message: "A synthetic suggestion, not a committed action.", choice_id: kind === "proposal" ? CHOICE.id : null, choice_hash: kind === "proposal" ? CHOICE.choice_hash : null } : null,
  error: ["failed", "unknown"].includes(status) ? { code: "SYNTHETIC", message: "The response could not complete. No action was taken." } : null });

class Element {
  constructor(tag = "div") { this.tag = tag; this.children = []; this.listeners = {}; this.hidden = false; this.value = ""; this.className = ""; this.classList = { toggle() {} }; this.attributes = {}; this.textContent = ""; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  scrollIntoView() {}
  focus() {}
  remove() {}
  showModal() { this.open = true; }
}

async function browser(options = {}) {
  const elements = new Map(); const created = [];
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const values = new Map(options.storage || []);
  if (options.gm) values.set(GM, JSON.stringify(options.gm));
  if (options.pending) values.set(PENDING, JSON.stringify(options.pending));
  let owner = options.owner === undefined ? OWNER : options.owner;
  let campaign = options.packet || packet();
  let remote = options.remote || null;
  let loseReply = options.loseReply || false;
  let rejectPost = options.rejectPost || null;
  let rejectGetOnce = options.rejectGetOnce || null;
  let loseBeforeReceive = options.loseBeforeReceive || false;
  const calls = []; const timers = new Map(); let nextTimer = 1;
  const reply = (status, body) => ({ ok: status < 400, status, json: async () => structuredClone(body) });
  const session = () => ({ player_id: owner, csrf_token: "csrf-" + owner, recovery_code: null });
  async function fetch(url, init = {}) {
    const method = init.method || "GET";
    const body = init.body === undefined ? undefined : JSON.parse(init.body);
    calls.push({ url, method, body, headers: init.headers });
    if (url === "/api/session") {
      if (method === "POST" && !owner) owner = OWNER;
      return owner ? reply(200, session()) : reply(401, { error: "SESSION_REQUIRED", message: "Recover the original connection." });
    }
    if (url === "/api/session/recover") { owner = body.recovery_code === "original-code" ? OWNER : OTHER; return reply(200, session()); }
    if (url === "/api/campaigns" && method === "GET") return reply(200, { campaigns: [{ id: CAMPAIGN, name: "Synthetic sample", revision: campaign.revision }] });
    if (url === "/api/campaigns/" + CAMPAIGN && method === "GET") return reply(200, campaign);
    if (url.endsWith("/gm-requests") && method === "POST") {
      assert.ok(values.has(GM), "The exact request must be durable before sending");
      assert.deepEqual(JSON.parse(values.get(GM)).request, body);
      assert.equal(init.headers["X-CSRF-Token"], "csrf-" + owner);
      if (rejectPost) {
        if (options.commitOnRejectedPost) remote = result({ request: body });
        return reply(rejectPost.status, rejectPost.body);
      }
      if (loseBeforeReceive) { loseBeforeReceive = false; throw new Error("synthetic request dropped"); }
      const saved = { request: body };
      remote = options.makeResult ? options.makeResult(saved) : result(saved, options.postStatus || "completed");
      if (loseReply) { loseReply = false; throw new Error("synthetic reply dropped"); }
      return reply(remote.status === "prepared" ? 202 : 200, remote);
    }
    if (url.includes("/gm-requests/") && method === "GET") {
      if (rejectGetOnce) { const rejected = rejectGetOnce; rejectGetOnce = null; return reply(rejected.status, rejected.body); }
      return remote ? reply(remote.status === "prepared" ? 202 : 200, remote) : reply(404, { error: "GM_REQUEST_NOT_FOUND", message: "No request received." });
    }
    if (url.endsWith("/actions") && method === "POST") {
      campaign = { ...campaign, revision: campaign.revision + 1, events: [{ revision: campaign.revision + 1, narration: "The approved synthetic action completed.", roll: null }] };
      return reply(200, campaign);
    }
    if (url === "/api/campaigns" && method === "POST") return reply(200, campaign);
    throw new Error("Unexpected synthetic request " + method + " " + url);
  }
  const windowListeners = {};
  const context = {
    document: { getElementById: get, createElement: tag => { const e = new Element(tag); created.push(e); return e; }, createTextNode: value => value,
      querySelectorAll: selector => created.filter(e => e.className === selector.slice(1)), body: new Element() },
    window: { addEventListener: (name, handler) => { windowListeners[name] = handler; } }, navigator: { onLine: true },
    localStorage: { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) },
    crypto: webcrypto, AbortController, fetch, console,
    setTimeout: (fn, ms) => { const id = nextTimer++; timers.set(id, { fn, ms }); return id; }, clearTimeout: id => timers.delete(id), location: { origin: "https://fixture.invalid" },
  };
  vm.runInNewContext(source, context);
  const flush = async () => { for (let i = 0; i < 14; i++) await new Promise(setImmediate); };
  await flush();
  return { calls, values, get, flush, setOwner: value => { owner = value; }, setPacket: value => { campaign = value; }, setRemote: value => { remote = value; },
    async click(id) { await get(id).listeners.click({}); await flush(); },
    async ask(prompt = "Can I move the sample books inside?") { get("gm-prompt").value = prompt; await get("gm-form").listeners.submit({ preventDefault() {} }); await flush(); },
    async restore(code) { get("restore-code").value = code; await get("restore-form").listeners.submit({ preventDefault() {} }); await flush(); },
    async confirmRisk() { get("risk-dialog").returnValue = "confirm"; await get("risk-dialog").listeners.close({}); await flush(); },
    async poll() { const match = [...timers.entries()].find(([, v]) => v.ms === 2500); assert.ok(match, "A bounded read-only poll must be scheduled"); timers.delete(match[0]); await match[1].fn(); await flush(); },
    async clickChoice(index = 0) { await get("choices").children[index].listeners.click({}); await flush(); },
  };
}
const posts = b => b.calls.filter(c => c.method === "POST" && c.url.endsWith("/gm-requests"));
const actions = b => b.calls.filter(c => c.method === "POST" && c.url.endsWith("/actions"));
const queries = b => b.calls.filter(c => c.method === "GET" && c.url.includes("/gm-requests/"));

(async () => {
  const disabled = packet(); disabled.capabilities = {};
  const off = await browser({ packet: disabled });
  assert.equal(off.get("gm-section").hidden, true);
  await off.ask(); assert.equal(posts(off).length, 0, "Default-off must prevent submission");

  const regular = await browser();
  assert.equal(regular.get("gm-section").hidden, false);
  await regular.ask();
  assert.equal(posts(regular).length, 1); assert.equal(actions(regular).length, 0, "A model proposal is never an action");
  assert.equal(regular.get("gm-proposal").hidden, false);
  await regular.click("gm-proposal");
  assert.equal(actions(regular).length, 1, "Only the explicit proposal choice advances state");
  assert.deepEqual(Object.keys(actions(regular)[0].body).sort(), ["action_id", "choice_hash", "choice_id", "expected_revision"].sort());
  assert.equal(actions(regular)[0].body.expected_revision, 0);
  assert.equal(actions(regular)[0].body.choice_hash, CHOICE.choice_hash);

  const risky = packet(); risky.state.choices[0].requires_roll = true;
  const risk = await browser({ packet: risky }); await risk.ask(); await risk.click("gm-proposal");
  assert.equal(risk.get("risk-dialog").open, true); assert.equal(actions(risk).length, 0);
  await risk.confirmRisk(); assert.equal(actions(risk).length, 1);
  const dialogChanged = await browser({ packet: risky }); await dialogChanged.ask(); await dialogChanged.click("gm-proposal");
  const afterDialog = packet(); afterDialog.revision = 1; dialogChanged.setPacket(afterDialog);
  await dialogChanged.click("refresh-campaign"); await dialogChanged.confirmRisk();
  assert.equal(actions(dialogChanged).length, 0, "A changed revision while confirming must require a fresh choice");

  for (const change of ["revision", "hash"]) {
    const b = await browser(); await b.ask();
    const changed = packet(); if (change === "revision") changed.revision = 1; else changed.state.choices[0].choice_hash = "b".repeat(64);
    b.setPacket(changed); await b.click("gm-proposal");
    assert.equal(actions(b).length, 0, "Stale " + change + " cannot commit a proposal");
    assert.equal(b.get("gm-proposal").hidden, true);
  }

  const changedOwner = await browser(); await changedOwner.ask(); changedOwner.setOwner(OTHER); await changedOwner.click("gm-proposal");
  assert.equal(actions(changedOwner).length, 0, "A proposal cannot cross accounts");

  const lost = await browser({ loseReply: true }); await lost.ask();
  const original = JSON.parse(lost.values.get(GM));
  assert.equal(original.status, "unconfirmed"); assert.equal(lost.get("gm-submit").disabled, true);
  await lost.clickChoice(); assert.equal(actions(lost).length, 0, "Unresolved GM requests exclude normal actions");
  await lost.click("gm-retry");
  assert.equal(posts(lost).length, 1, "A lost reply is recovered with GET, not another provider request");
  assert.equal(JSON.parse(lost.values.get(GM)).request.request_id, original.request.request_id);
  assert.equal(JSON.parse(lost.values.get(GM)).status, "completed");

  // Rate limiting can reject before the original request lookup. A timed-out
  // original may still commit, so generic 429s cannot permit a fresh request.
  for (const errorCode of ["PLEASE_WAIT", "RATE_LIMITED", undefined]) {
    const throttle = { status: 429, body: { ...(errorCode ? { error: errorCode } : {}), message: "Please wait before checking." } };
    const delayed = await browser({ loseReply: true, rejectGetOnce: throttle }); await delayed.ask();
    const retained = JSON.parse(delayed.values.get(GM)).request;
    await delayed.click("gm-retry");
    assert.equal(JSON.parse(delayed.values.get(GM)).status, "checking");
    assert.deepEqual(JSON.parse(delayed.values.get(GM)).request, retained);
    assert.equal(delayed.get("gm-new").hidden, true); assert.equal(delayed.get("gm-submit").disabled, true);
    await delayed.poll();
    assert.equal(posts(delayed).length, 1, "429 recovery may only read the original request");
    assert.equal(JSON.parse(delayed.values.get(GM)).status, "completed");
    assert.deepEqual(JSON.parse(delayed.values.get(GM)).request, retained);
  }
  const throttledPost = await browser({ rejectPost: { status: 429, body: { error: "PLEASE_WAIT", message: "Please wait." } }, commitOnRejectedPost: true });
  await throttledPost.ask(); const throttledRequest = JSON.parse(throttledPost.values.get(GM)).request;
  assert.equal(JSON.parse(throttledPost.values.get(GM)).status, "checking"); await throttledPost.poll();
  assert.equal(posts(throttledPost).length, 1); assert.equal(queries(throttledPost).length, 1);
  assert.equal(JSON.parse(throttledPost.values.get(GM)).status, "completed");
  assert.deepEqual(JSON.parse(throttledPost.values.get(GM)).request, throttledRequest);
  const exhausted = await browser({ rejectPost: { status: 429, body: { error: "GM_BUDGET_EXHAUSTED", message: "Sample allowance used." } } });
  await exhausted.ask(); assert.equal(JSON.parse(exhausted.values.get(GM)).status, "rejected");
  assert.equal(exhausted.get("gm-retry").hidden, true);
  await exhausted.clickChoice(); assert.equal(actions(exhausted).length, 1);

  const saved = record();
  const resumed = await browser({ gm: saved, remote: result(saved) });
  assert.equal(posts(resumed).length, 0); assert.equal(queries(resumed).length, 1);
  assert.equal(resumed.calls.filter(c => c.url === "/api/session" && c.method === "POST").length, 0);
  for (const owner of [null, OTHER]) {
    const b = await browser({ gm: saved, owner, remote: result(saved) });
    assert.equal(posts(b).length, 0); assert.equal(queries(b).length, 0);
    assert.equal(b.calls.filter(c => c.url === "/api/session" && c.method === "POST").length, 0, "Owner loss must not create an identity");
    assert.deepEqual(JSON.parse(b.values.get(GM)), saved);
    await b.restore("other-code"); assert.equal(queries(b).length, 0);
    await b.restore("original-code"); assert.equal(queries(b).length, 1); assert.equal(posts(b).length, 0);
  }

  const dropped = await browser({ loseBeforeReceive: true }); await dropped.ask();
  const dropRequest = JSON.parse(dropped.values.get(GM)).request;
  await dropped.click("gm-retry"); assert.equal(posts(dropped).length, 1); assert.equal(JSON.parse(dropped.values.get(GM)).status, "not_found");
  await dropped.click("gm-retry"); assert.equal(posts(dropped).length, 2); assert.deepEqual(posts(dropped)[1].body, dropRequest);
  assert.deepEqual(posts(dropped)[0].body, posts(dropped)[1].body, "Explicit retry must retain every request field");

  const polling = await browser({ postStatus: "prepared" }); await polling.ask();
  const prepared = JSON.parse(polling.values.get(GM)); polling.setRemote(result(prepared)); await polling.poll();
  assert.equal(posts(polling).length, 1); assert.equal(queries(polling).length, 1);
  assert.equal(JSON.parse(polling.values.get(GM)).status, "completed");
  const retainedAction = { kind: "action", player_id: OWNER, campaign_id: CAMPAIGN,
    request: { action_id: "55555555-5555-4555-8555-555555555555", expected_revision: 0, choice_id: CHOICE.id, choice_hash: CHOICE.choice_hash } };
  const twoPending = await browser({ gm: saved, pending: retainedAction, remote: result(saved) });
  assert.equal(posts(twoPending).length, 0); assert.equal(queries(twoPending).length, 1);
  assert.equal(actions(twoPending).length, 1, "Read-only GM recovery must not deadlock an existing authorised action");
  assert.ok(twoPending.calls.findIndex(c => c.url.includes("/gm-requests/")) < twoPending.calls.findIndex(c => c.url.endsWith("/actions")));

  for (const status of ["failed", "unknown"]) {
    const b = await browser({ postStatus: status }); await b.ask();
    assert.equal(JSON.parse(b.values.get(GM)).status, status); assert.equal(b.get("gm-retry").hidden, true);
    await b.click("gm-retry"); assert.equal(posts(b).length, 1, "Terminal requests must not be reissued");
    assert.equal(actions(b).length, 0); await b.click("gm-new"); await b.ask("A different explicit question.");
    assert.equal(posts(b).length, 2); assert.notEqual(posts(b)[0].body.request_id, posts(b)[1].body.request_id);
  }
  const unavailable = await browser({ rejectPost: { status: 503, body: { error: "GM_DISABLED", message: "The assistant is disabled; listed choices remain available." } } });
  await unavailable.ask(); assert.equal(JSON.parse(unavailable.values.get(GM)).status, "rejected");
  await unavailable.clickChoice(); assert.equal(actions(unavailable).length, 1, "Definite unavailable responses must not lock ordinary play");

  const literal = "<script>do not execute</script>";
  const text = await browser({ makeResult: saved => ({ ...result(saved, "completed", "answer"), result: { kind: "answer", message: literal, choice_id: null, choice_hash: null } }) });
  await text.ask(); assert.equal(text.get("gm-message").children[0].textContent, literal); assert.equal(actions(text).length, 0);
  const limit = await browser(); await limit.ask("x".repeat(2001)); assert.equal(posts(limit).length, 0);

  console.log("Bounded GM frontend scenarios passed: capability, owner, retry, polling, stale proposal, confirmation, terminal status and safe text.");
})().catch(error => { console.error(error); process.exitCode = 1; });
