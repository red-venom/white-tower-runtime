// Execute the real browser script with an in-memory DOM, storage and HTTP peer.
// No server, browser credentials, campaign files or external network are used.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const { webcrypto } = require("node:crypto");
const source = fs.readFileSync(path.join(__dirname, "../mobile_game/static/app.js"), "utf8");
const PENDING = "white-tower-mobile:pending:v1";
const OWNER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const CAMPAIGN = "33333333-3333-4333-8333-333333333333";
const ID = "44444444-4444-4444-8444-444444444444";
const choice = { id: "move_inside", label: "Move inside", choice_hash: "a".repeat(64), requires_roll: false };
const packet = { id: CAMPAIGN, revision: 0, events: [], state: { choices: [choice], resources: {}, story: "Synthetic sample." } };

class Element {
  constructor() { this.children = []; this.listeners = {}; this.hidden = false; this.value = ""; this.classList = { toggle() {} }; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute() {}
  scrollIntoView() {}
  focus() {}
  remove() {}
}

async function browser(initialPending, initialOwner, options = {}) {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const values = new Map(initialPending ? [[PENDING, JSON.stringify(initialPending)]] : []);
  const calls = [];
  let owner = initialOwner;
  let lostReply = options.lostReply;
  const session = () => ({ player_id: owner, csrf_token: "csrf-" + owner, recovery_code: null });
  const reply = (status, data) => ({ ok: status < 400, status, json: async () => data });
  async function fetch(url, init = {}) {
    const method = init.method || "GET";
    const body = init.body === undefined ? undefined : JSON.parse(init.body);
    calls.push({ url, method, body });
    if (url === "/api/session") {
      if (method === "POST" && !owner) owner = OWNER;
      return owner ? reply(200, session()) : reply(401, { message: "Recover the original connection." });
    }
    if (url === "/api/session/recover") { owner = body.recovery_code === "original-code" ? OWNER : OTHER; return reply(200, session()); }
    if (url === "/api/campaigns" && method === "GET") return reply(200, { campaigns: options.showCampaign ? [{ id: CAMPAIGN }] : [] });
    if (url === "/api/campaigns/" + CAMPAIGN && method === "GET") return reply(200, packet);
    if (method === "POST" && (url === "/api/campaigns" || url.endsWith("/actions"))) {
      if (lostReply) { lostReply = false; throw new Error("lost response"); }
      return reply(200, { ...packet, revision: url.endsWith("/actions") ? 1 : 0, replayed: true });
    }
    throw new Error("Unexpected request " + method + " " + url);
  }
  const context = {
    document: { getElementById: get, createElement: () => new Element(), createTextNode: value => value, querySelectorAll: () => [], body: new Element() },
    window: { addEventListener() {} }, navigator: { onLine: true },
    localStorage: { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) },
    crypto: webcrypto, AbortController, fetch, console,
    setTimeout: () => 1, clearTimeout() {}, location: { origin: "https://fixture.invalid" },
  };
  vm.runInNewContext(source, context);
  const flush = async () => { for (let i = 0; i < 12; i++) await new Promise(setImmediate); };
  await flush();
  return { calls, values, get, flush, setOwner: value => { owner = value; },
    async click(id) { await get(id).listeners.click({}); await flush(); },
    async restore(code) { get("restore-code").value = code; await get("restore-form").listeners.submit({ preventDefault() {} }); await flush(); } };
}

const pending = kind => ({ kind, player_id: OWNER, ...(kind === "action" ? { campaign_id: CAMPAIGN } : {}),
  request: kind === "create" ? { request_id: ID } : { action_id: ID, expected_revision: 0, choice_id: choice.id, choice_hash: choice.choice_hash } });
const mutations = b => b.calls.filter(c => c.method === "POST" && (c.url === "/api/campaigns" || c.url.endsWith("/actions")));

(async () => {
  for (const kind of ["create", "action"]) {
    const saved = pending(kind);
    for (const owner of [null, OTHER]) {
      const b = await browser(saved, owner);
      assert.equal(mutations(b).length, 0, kind + " must not replay under a missing or foreign owner");
      assert.equal(b.calls.filter(c => c.url === "/api/session" && c.method === "POST").length, 0);
      assert.deepEqual(JSON.parse(b.values.get(PENDING)), saved);
      assert.equal(b.get("restore-details").open, true);
      await b.restore("other-code");
      assert.equal(mutations(b).length, 0);
      assert.deepEqual(JSON.parse(b.values.get(PENDING)), saved);
      await b.restore("original-code");
      assert.equal(mutations(b).length, 1);
      assert.deepEqual(mutations(b)[0].body, saved.request);
      assert.equal(b.values.has(PENDING), false);
    }
    const b = await browser(saved, OWNER, { lostReply: true });
    assert.equal(mutations(b).length, 1);
    assert.deepEqual(JSON.parse(b.values.get(PENDING)), saved);
    b.setOwner(OTHER);
    await b.click("retry-action");
    assert.equal(mutations(b).length, 1, "cookie changes must be checked before retry");
    assert.deepEqual(JSON.parse(b.values.get(PENDING)), saved);
    await b.restore("original-code");
    assert.equal(mutations(b).length, 2);
    assert.deepEqual(mutations(b)[0].body, mutations(b)[1].body);
    assert.equal(b.values.has(PENDING), false);
  }
  const legacy = pending("create"); delete legacy.player_id;
  const old = await browser(legacy, OWNER, { showCampaign: true });
  assert.equal(mutations(old).length, 0);
  assert.deepEqual(JSON.parse(old.values.get(PENDING)), legacy);
  await old.get("campaign-list").children[0].listeners.click({}); await old.flush();
  assert.equal(old.calls.filter(c => c.url === "/api/campaigns/" + CAMPAIGN && c.method === "GET").length, 1);
  assert.equal(old.get("choices-section").hidden, true);
  assert.equal(mutations(old).length, 0);
  assert.deepEqual(JSON.parse(old.values.get(PENDING)), legacy);
  const signup = await browser(null, null, { lostReply: true });
  assert.equal(signup.calls.filter(c => c.url === "/api/session" && c.method === "POST").length, 1);
  await signup.click("start-campaign");
  assert.equal(JSON.parse(signup.values.get(PENDING)).player_id, OWNER);
  assert.equal(mutations(signup).length, 1);
  const action = await browser(null, OWNER, { showCampaign: true, lostReply: true });
  const button = action.get("choices").children[0];
  await button.listeners.click({}); await action.flush();
  assert.equal(JSON.parse(action.values.get(PENDING)).player_id, OWNER);
  assert.equal(mutations(action).length, 1);
  console.log("Owner-bound frontend retry scenarios passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
