"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const STORAGE = { selected: "white-tower-mobile:selected:v1", pending: "white-tower-mobile:pending:v1", gm: "white-tower-mobile:gm:v1" };
  let csrfToken = null;
  let playerId = null;
  let current = null;
  let campaigns = [];
  let busy = false;
  let pending = null;
  let recoveryCode = null;
  let toastTimer;
  let dialogChoice = null;
  let dialogContext = null;
  let gmRequest = null;
  let gmPollTimer = null;
  let gmPollCount = 0;
  let storageAvailable = true;

  class ApiError extends Error {
    constructor(message, status, detail) { super(message); this.status = status; this.detail = detail; }
  }

  function stored(key) { try { return localStorage.getItem(key); } catch (_) { storageAvailable = false; return null; } }
  function persist(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); return true; } catch (_) { storageAvailable = false; return false; } }
  try { pending = JSON.parse(stored(STORAGE.pending) || "null"); } catch (_) { pending = null; }
  if (pending && (!pending.request || !["action", "create"].includes(pending.kind))) {
    pending = null;
    persist(STORAGE.pending, null);
  }
  try { gmRequest = JSON.parse(stored(STORAGE.gm) || "null"); } catch (_) { gmRequest = null; }
  if (gmRequest && (!gmRequest.request || !gmRequest.campaign_id || !gmRequest.request.request_id)) {
    gmRequest = null; persist(STORAGE.gm, null);
  }
  const gmUnresolved = () => !!gmRequest && !["completed", "failed", "unknown", "rejected"].includes(gmRequest.status);
  const gmEnabled = () => current?.capabilities?.gm_assistant === true;

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c => (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16));
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (csrfToken && options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrfToken;
    try {
      const response = await fetch(path, { ...options, headers, credentials: "same-origin", cache: "no-store", signal: controller.signal, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
      let data = null;
      try { data = await response.json(); } catch (_) { /* A non-JSON error still has an HTTP status. */ }
      if (!response.ok) {
        const detail = data && (data.message || data.detail || data.error);
        throw new ApiError(typeof detail === "string" ? detail : "The request could not be completed.", response.status, data);
      }
      if (!data) throw new ApiError("The reply was incomplete. Your save may still have succeeded.", 0);
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(error.name === "AbortError" ? "The connection is taking longer than expected." : "Your connection was interrupted.", 0);
    } finally { clearTimeout(timeout); }
  }

  function notice(message, error = false, retry = null) {
    const element = $("notice");
    element.replaceChildren(document.createTextNode(message));
    element.classList.toggle("error", error);
    element.hidden = false;
    if (retry) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "text-button"; button.textContent = "Try again";
      button.addEventListener("click", retry); element.append(button);
    }
  }
  function clearNotice() { $("notice").hidden = true; }
  function toast(message) { clearTimeout(toastTimer); $("toast").textContent = message; $("toast").hidden = false; toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3500); }
  function connection(message, kind = "") {
    const dot = document.createElement("span"); dot.className = `status-dot ${kind}`;
    $("connection-status").replaceChildren(dot, document.createTextNode(message));
  }
  function setBusy(value) {
    busy = value;
    ["start-campaign", "new-campaign", "export-campaign"].forEach(id => { $(id).disabled = value || !!pending || gmUnresolved(); });
    $("refresh-campaign").disabled = value || !!pending;
    $("restore-button").disabled = value;
    $("new-recovery-code").disabled = value || !!pending || gmUnresolved() || !csrfToken;
    $("confirm-recovery-code").disabled = value || !!pending || gmUnresolved() || !csrfToken;
    document.querySelectorAll(".choice").forEach(button => { button.disabled = value || !!pending || gmUnresolved(); });
    document.querySelectorAll(".campaign-item").forEach(button => { button.disabled = value; });
    $("retry-action").disabled = value || !navigator.onLine;
    $("retry-action").textContent = value ? "Checking your save…" : "Check and retry safely";
    $("restore-details").hidden = false;
    renderPending();
    renderGM();
  }

  function prose(container, text) {
    container.replaceChildren();
    const parts = Array.isArray(text) ? text : String(text || "").split(/\n\s*\n/);
    parts.filter(Boolean).forEach(part => { const p = document.createElement("p"); p.textContent = typeof part === "string" ? part : part.text || part.narration || ""; container.append(p); });
  }
  function characterName(state) {
    if (typeof state.character === "string") return state.character;
    return state.character?.name || state.identity?.name || state.name || "Your sample character";
  }
  function displayTime(state) {
    if (typeof state.time === "string") return state.time;
    if (typeof state.fictional_seconds !== "number") return "";
    const t = state.fictional_seconds;
    const hours = Math.floor(t / 3600) % 24;
    const minutes = Math.floor(t / 60) % 60;
    return `Day ${Math.floor(t / 86400) + 1} · ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  }
  function renderResources(state) {
    const root = $("resources"); root.replaceChildren();
    const resources = state.resources || {};
    const known = [["vitality", "Vitality"], ["strain", "Strain"], ["supply", "Supply"], ["silver", "Silver"]];
    for (const [key, label] of known) {
      if (resources[key] === undefined || resources[key] === null) continue;
      let value = resources[key];
      if (typeof value === "object") value = value.current !== undefined ? `${value.current}${value.max !== undefined ? ` / ${value.max}` : ""}` : "—";
      else if (key === "vitality" && (resources.max_vitality ?? resources.vitality_max) !== undefined) value = `${value} / ${resources.max_vitality ?? resources.vitality_max}`;
      const cell = document.createElement("div"); cell.className = "resource";
      const name = document.createElement("span"); name.className = "resource-label"; name.textContent = label;
      const number = document.createElement("span"); number.className = "resource-value"; number.textContent = String(value);
      cell.append(name, number); root.append(cell);
    }
    root.hidden = !root.children.length;
  }
  function describeRoll(roll) {
    if (!roll || roll.method === "none" || roll === "none") return "";
    if (typeof roll === "string") return roll;
    if (roll.summary) return roll.summary;
    const die = roll.die ?? roll.raw ?? roll.value ?? (Array.isArray(roll.dice) ? roll.dice.join(" + ") : Array.isArray(roll.values) ? roll.values.join(" + ") : null);
    const modifier = roll.attribute_rating !== undefined && roll.skill_rating !== undefined ? roll.attribute_rating + roll.skill_rating + (roll.modifier || 0) : roll.modifier ?? roll.bonus;
    const total = roll.total;
    const result = roll.outcome ?? roll.result;
    const parts = [];
    if (die !== undefined && die !== null) parts.push(`Roll ${die}${modifier !== undefined ? ` ${modifier < 0 ? "−" : "+"} ${Math.abs(modifier)}` : ""}${total !== undefined ? ` = ${total}` : ""}`);
    else if (total !== undefined) parts.push(`Roll total ${total}`);
    if (roll.difficulty !== undefined || roll.dc !== undefined) parts.push(`difficulty ${roll.difficulty ?? roll.dc}`);
    if (result) parts.push(String(result).replaceAll("_", " "));
    return parts.join(" · ");
  }
  function renderCampaign(data) {
    current = data.campaign || data;
    if (!current || !current.id || !current.state) throw new Error("The saved story reply is incomplete.");
    persist(STORAGE.selected, current.id);
    const state = current.state;
    $("welcome").hidden = true; $("game").hidden = false;
    $("story-title").textContent = state.title || current.name || "An afternoon at the Tower";
    $("character-line").textContent = [characterName(state), state.location].filter(Boolean).join(" · ");
    const completed = !!(state.completed || state.complete || state.status === "complete" || state.status === "completed");
    $("chapter-status").textContent = completed ? "Complete" : "In progress";
    $("story-time").textContent = displayTime(state);
    renderResources(state);
    const events = current.events || [];
    const latest = events.length ? events[events.length - 1] : null;
    prose($("story"), latest?.narration || state.story || "Your story is ready.");
    $("save-status").textContent = `Saved online · turn ${current.revision}`;
    const rollText = describeRoll(latest?.roll);
    $("last-roll").textContent = rollText; $("last-roll").hidden = !rollText;
    const choices = $("choices"); choices.replaceChildren();
    for (const choice of state.choices || []) {
      const button = document.createElement("button"); button.type = "button"; button.className = "choice"; button.disabled = busy || !!pending || gmUnresolved();
      const title = document.createElement("span"); title.className = "choice-title"; title.textContent = choice.label || choice.id;
      button.append(title);
      if (choice.description) { const description = document.createElement("span"); description.className = "choice-description"; description.textContent = choice.description; button.append(description); }
      if (choice.stakes) { const stakes = document.createElement("span"); stakes.className = "choice-stakes"; stakes.textContent = choice.requires_roll ? "Uncertain · Review the roll and possible consequences before committing." : choice.stakes; button.append(stakes); }
      button.addEventListener("click", () => choose(choice)); choices.append(button);
    }
    $("choices-heading").textContent = completed ? "What comes next?" : "What do you do?";
    $("choices-section").hidden = !choices.children.length || !!pending;
    $("ending").hidden = !completed;
    const journal = $("events"); journal.replaceChildren();
    for (const event of events) {
      const entry = document.createElement("article"); entry.className = "journal-entry";
      const label = document.createElement("p"); label.className = "journal-entry-label"; label.textContent = `Turn ${event.revision ?? "—"}`;
      const body = document.createElement("div"); body.className = "story-prose"; prose(body, event.narration);
      entry.append(label, body);
      const roll = describeRoll(event.roll); if (roll) { const receipt = document.createElement("p"); receipt.className = "roll-receipt"; receipt.textContent = roll; entry.append(receipt); }
      journal.append(entry);
    }
    $("journal-count").textContent = `${events.length} ${events.length === 1 ? "entry" : "entries"}`;
    $("journal").hidden = !events.length;
    const existing = campaigns.findIndex(c => c.id === current.id);
    const info = { id: current.id, name: current.name || state.title || characterName(state), revision: current.revision, updated_at: current.updated_at };
    if (existing < 0) campaigns.unshift(info); else campaigns[existing] = info;
    renderLibrary(); renderPending(); renderGM();
    if (window.dispatchEvent) window.dispatchEvent(new CustomEvent("white-tower:state", { detail: current }));
    connection(navigator.onLine ? "Connected · your progress is saved online" : "Offline · reconnect to continue", navigator.onLine ? "" : "offline");
  }
  function renderLibrary() {
    const root = $("campaign-list"); root.replaceChildren();
    $("campaign-library").hidden = !campaigns.length;
    campaigns.forEach(campaign => {
      const button = document.createElement("button"); button.type = "button"; button.className = "campaign-item"; button.disabled = busy;
      const copy = document.createElement("span"); const title = document.createElement("span"); title.className = "campaign-item-title"; title.textContent = campaign.name || "Sample story";
      const meta = document.createElement("span"); meta.className = "campaign-item-meta"; meta.textContent = `${campaign.chapter ? campaign.chapter + " · " : ""}Saved turn ${campaign.revision ?? 0}`;
      copy.append(title, meta); const status = document.createElement("span"); status.className = "campaign-item-current"; status.textContent = current?.id === campaign.id ? "Open" : "Continue →";
      button.append(copy, status); button.addEventListener("click", () => loadCampaign(campaign.id)); root.append(button);
    });
  }
  function renderPending() {
    $("pending-card").hidden = !pending;
    if (!pending) return;
    // Keep recovery available even if the first sample creation never returned a page.
    if (!current) { $("game").hidden = false; $("welcome").hidden = true; $("story-title").textContent = "Keeping your place"; $("story").textContent = "Your request is safely kept in this browser while we confirm the saved result."; $("save-status").textContent = "Waiting for save confirmation"; $("journal").hidden = true; $("ending").hidden = true; }
    $("pending-heading").textContent = busy ? "Checking your save" : "Let’s confirm what happened";
    $("pending-description").textContent = pending.kind === "create" ? "Your sample story may already have been created. We’ll check the original request before starting anything else." : `Your choice${pending.label ? `, “${pending.label},”` : ""} may already be saved. Check it before making another choice.`;
    $("choices-section").hidden = true;
  }

  async function loadCampaign(id) {
    if (busy) return;
    setBusy(true); clearNotice();
    try {
      renderCampaign(await api(`/api/campaigns/${encodeURIComponent(id)}`));
      if (pending) notice("You can inspect this saved story. Your pending request is still kept; no new action is available until its original connection and result are confirmed.");
      else if (gmUnresolved()) notice("You can inspect this saved story. The assistant request is still being checked; finish checking it before taking an action.");
    }
    catch (error) { notice(error.status === 404 ? "That story isn’t available in this connection. Restore your original recovery code to open it." : error.message, true, () => loadCampaign(id)); }
    finally { setBusy(false); }
  }
  function keepPending(item) {
    // Do not send a mutation if this browser cannot retain its exact retry request.
    if (!persist(STORAGE.pending, JSON.stringify(item))) {
      notice("This browser isn’t allowing saved site data. Enable it before choosing an action, so an interrupted save can be recovered safely.", true); return false;
    }
    pending = item; return true;
  }
  function clearPending() { pending = null; persist(STORAGE.pending, null); }
  function adoptSession(session) {
    if (typeof session.player_id !== "string" || !session.player_id || !session.csrf_token) {
      throw new ApiError("The private connection could not be established.", 0);
    }
    csrfToken = session.csrf_token; playerId = session.player_id;
  }
  function requirePendingOwner() {
    if (pending && (!pending.player_id || pending.player_id !== playerId)) {
      $("restore-details").open = true;
      throw new ApiError(pending.player_id
        ? "This saved request belongs to another connection. Recover the original account before retrying it."
        : "This older saved request has no verified owner and will not replay automatically. Recover the original connection, inspect its saved stories below, and ask for help reconciling the retained request.", 403);
    }
  }
  function requireGMOwner() {
    if (gmUnresolved() && (!gmRequest.player_id || gmRequest.player_id !== playerId)) {
      $("restore-details").open = true;
      throw new ApiError("This assistant request belongs to another connection. Recover the original account before checking it.", 403);
    }
  }
  async function createCampaign() {
    if (busy || pending || gmUnresolved()) return;
    if (!navigator.onLine) { notice("Reconnect to the internet before starting a story.", true); return; }
    if (!playerId) { notice("Reconnect before starting a story.", true, initialize); return; }
    const episode = $("episode-select")?.value;
    const request = { request_id: uuid(), ...(episode ? { episode_id: episode } : {}) };
    if (keepPending({ kind: "create", player_id: playerId, request, created_at: new Date().toISOString() })) await sendPending();
  }
  function choose(choice) {
    if (busy || pending || gmUnresolved() || !current) return;
    if (!navigator.onLine) { notice("Reconnect to the internet before taking your next action.", true); return; }
    if (choice.requires_roll) {
      dialogChoice = choice; dialogContext = { campaign_id: current.id, revision: current.revision }; $("risk-title").textContent = choice.label; $("risk-description").textContent = choice.description || ""; $("risk-stakes").textContent = choice.stakes || "This outcome is uncertain."; $("risk-dialog").showModal();
    } else submitChoice(choice);
  }
  async function submitChoice(choice) {
    if (busy || pending || gmUnresolved() || !current) return;
    if (!playerId) { notice("Reconnect before choosing an action.", true, initialize); return; }
    const item = { kind: "action", player_id: playerId, campaign_id: current.id, label: choice.label, request: { action_id: uuid(), expected_revision: current.revision, choice_id: choice.id, choice_hash: choice.choice_hash }, created_at: new Date().toISOString() };
    if (keepPending(item)) await sendPending();
  }
  async function sendPending() {
    if (busy || !pending || gmUnresolved()) return;
    if (!navigator.onLine) { setBusy(false); notice("Your choice is kept. Reconnect, then check your save.", true); return; }
    const request = pending;
    setBusy(true); clearNotice(); connection("Checking your saved choice…", "connecting");
    try {
      // Recheck the cookie's current owner, including changes in another tab.
      // GET never creates an identity when a cookie has expired or disappeared.
      adoptSession(await api("/api/session"));
      requirePendingOwner();
      const path = request.kind === "create" ? "/api/campaigns" : `/api/campaigns/${encodeURIComponent(request.campaign_id)}/actions`;
      const result = await api(path, { method: "POST", body: request.request });
      const candidate = result.campaign || result;
      if (!candidate.id || !candidate.state || !Number.isInteger(candidate.revision)) throw new ApiError("The save reply was incomplete. Your choice is still kept for checking.", 0);
      clearPending();
      if (result.replayed) {
        try { renderCampaign(await api(`/api/campaigns/${encodeURIComponent(candidate.id)}`)); }
        catch (_) {
          renderCampaign(result);
          $("choices-section").hidden = true;
          notice("Your original choice is confirmed and shown below. We couldn’t check whether another window has played further. Refresh the saved story before making another choice.", false);
        }
      } else renderCampaign(result);
      toast(result.replayed ? "Your saved result has been recovered." : "Your story is saved.");
      if (window.dispatchEvent) window.dispatchEvent(new CustomEvent("white-tower:committed", {detail: request}));
    } catch (error) {
      if (error.status === 409 || error.status === 422) {
        clearPending();
        let refreshed = false;
        if (request.campaign_id) {
          try { renderCampaign(await api(`/api/campaigns/${encodeURIComponent(request.campaign_id)}`)); refreshed = true; } catch (_) { /* Leave the last known state visible and request an explicit refresh. */ }
        }
        notice(error.status === 409 ? `This story changed in another window or the available choice was updated. Your new choice was not applied. ${refreshed ? "The latest saved story is shown; choose again from here." : "Refresh the saved story before choosing again."}` : `That choice wasn’t available, so the story did not advance. ${refreshed ? "Review the saved story and choose again." : "Refresh the saved story before choosing again."}`, false);
      } else {
        if (error.status === 401 || error.status === 403) { csrfToken = null; playerId = null; $("restore-details").open = true; }
        if (error.status === 404) {
          $("restore-details").open = true;
          notice("This browser no longer has access to that story. Enter your original recovery code below, then we’ll check the choice you already made. The original choice is still kept.", true);
        } else notice(`${error.status === 401 || error.status === 403 ? "Your connection needs to be checked. " : ""}${error.message} Your original choice is kept; use “Check and retry safely” to recover its result.`, true);
        connection("Save not yet confirmed · your choice is kept", "connecting");
      }
    } finally { setBusy(false); }
  }

  function saveGM(value) {
    if (!persist(STORAGE.gm, value ? JSON.stringify(value) : null)) {
      notice("This browser cannot keep the assistant request safely. Enable saved site data before asking again.", true);
      return false;
    }
    gmRequest = value; return true;
  }
  function stopGMPoll() { clearTimeout(gmPollTimer); gmPollTimer = null; }
  function scheduleGMPoll() {
    stopGMPoll();
    if (!["prepared", "checking"].includes(gmRequest?.status) || gmPollCount >= 20 || !navigator.onLine) return;
    gmPollTimer = setTimeout(() => { gmPollCount += 1; checkGM(); }, 2500);
  }
  function gmChoice() {
    if (!gmRequest || gmRequest.status !== "completed" || gmRequest.response?.result?.kind !== "proposal") return null;
    if (gmRequest.player_id !== playerId || gmRequest.campaign_id !== current?.id || gmRequest.request.expected_revision !== current?.revision) return null;
    const result = gmRequest.response.result;
    return current.state.choices?.find(choice => choice.id === result.choice_id && choice.choice_hash === result.choice_hash) || null;
  }
  function renderGM() {
    const enabled = gmEnabled();
    const unresolved = gmUnresolved();
    const owned = gmRequest?.player_id === playerId && !!playerId;
    const matches = owned && gmRequest?.campaign_id === current?.id;
    $("gm-section").hidden = !enabled && !unresolved;
    if (!enabled && !unresolved) return;
    if (unresolved && !current) {
      $("game").hidden = false; $("welcome").hidden = true;
      $("story-title").textContent = "Checking your saved request";
      $("story").textContent = "Your assistant request is kept. Recover its original connection to check the response; no game action has been taken.";
      $("save-status").textContent = "Waiting to load the saved story";
      $("choices-section").hidden = true; $("journal").hidden = true; $("ending").hidden = true;
    }
    $("gm-form").hidden = !enabled || !!gmRequest && (matches || unresolved);
    $("gm-prompt").disabled = busy || !!pending || unresolved;
    $("gm-submit").disabled = busy || !!pending || unresolved || !playerId;
    $("gm-response").hidden = !gmRequest || !matches && !unresolved;
    $("gm-proposal").hidden = true;
    $("gm-retry").hidden = !unresolved;
    $("gm-retry").disabled = busy || !!pending || !navigator.onLine;
    $("gm-retry").textContent = gmRequest?.status === "not_found" ? "Send the saved request" : "Check this request";
    $("gm-new").hidden = !matches || unresolved || !enabled;
    $("gm-dismiss").hidden = !matches || unresolved;
    $("gm-new").disabled = busy || !!pending;
    $("gm-dismiss").disabled = busy;
    if (!gmRequest) return;
    if (!matches) {
      $("gm-status").textContent = "Original connection required";
      prose($("gm-message"), owned ? "This request belongs to another sample story. Check it to reopen that story and recover the response." : "Recover the original connection before checking this retained request.");
      $("gm-response-note").textContent = "No new request or game action will be sent under another account.";
      return;
    }
    const status = gmRequest.status;
    if (status === "completed") {
      const result = gmRequest.response.result;
      $("gm-status").textContent = result.kind === "proposal" ? "A suggested approach" : result.kind === "clarify" ? "A little more detail is needed" : "About this scene";
      prose($("gm-message"), result.message);
      const choice = gmChoice();
      if (result.kind === "proposal" && choice && enabled) {
        $("gm-proposal").textContent = choice.requires_roll ? `Review: ${choice.label}` : `Choose: ${choice.label}`;
        $("gm-proposal").hidden = false; $("gm-proposal").disabled = busy || !!pending;
        $("gm-response-note").textContent = "This is a suggestion. The story will change only if you choose the action.";
      } else $("gm-response-note").textContent = result.kind === "proposal" ? "The story or available choice has changed since this suggestion. Review the current choices, or ask again." : "Your story has not advanced.";
    } else if (status === "failed" || status === "unknown" || status === "rejected") {
      $("gm-status").textContent = status === "unknown" ? "Response could not be confirmed" : "Request ended without a suggestion";
      prose($("gm-message"), gmRequest.response?.error?.message || gmRequest.error || "The assistant could not complete this request.");
      $("gm-response-note").textContent = "No game action was taken. You can use the listed choices or explicitly ask a new question.";
    } else {
      $("gm-status").textContent = status === "prepared" ? "Considering your approach" : status === "not_found" ? "Request not yet received" : "Checking your request";
      prose($("gm-message"), status === "prepared" ? "The request is saved and awaiting its response. You can leave this page and return to check it." : status === "not_found" ? "The server has no record of this request. Send the saved request to try it with the same identifier." : "The connection was interrupted or the reply is still being checked. Your original request is kept.");
      $("gm-response-note").textContent = "Checking retrieves this request; it does not start another one. No fictional time has passed.";
    }
  }
  function acceptGMResponse(response) {
    if (!gmRequest || response.request_id !== gmRequest.request.request_id || response.expected_revision !== gmRequest.request.expected_revision || !["prepared", "completed", "failed", "unknown"].includes(response.status)) {
      throw new ApiError("The assistant reply did not match the saved request.", 0);
    }
    const result = response.result;
    if (response.status === "completed" && (!result || !["proposal", "answer", "clarify"].includes(result.kind) || typeof result.message !== "string" || result.kind === "proposal" && (typeof result.choice_id !== "string" || typeof result.choice_hash !== "string"))) {
      throw new ApiError("The assistant reply was incomplete.", 0);
    }
    saveGM({ ...gmRequest, status: response.status, response, error: null });
  }
  function handleGMError(error) {
    if (!gmRequest) return;
    const budgetExhausted = error.status === 429 && error.detail?.error === "GM_BUDGET_EXHAUSTED";
    if ([409, 422].includes(error.status) || budgetExhausted || error.status === 503 && error.detail?.error === "GM_DISABLED") {
      saveGM({ ...gmRequest, status: "rejected", error: error.message });
    } else {
      // A throttle may run before lookup while the original request is still
      // finishing. Only the specific budget rejection proves no reservation;
      // every other 429 keeps the exact request and checks it with GET.
      saveGM({ ...gmRequest, status: error.status === 429 ? "checking" : "unconfirmed", error: error.message });
      if (error.status === 401 || error.status === 403) { csrfToken = null; playerId = null; $("restore-details").open = true; }
      notice(`${error.message} The original assistant request is kept for checking.`, true);
    }
  }
  async function askGM(event) {
    event.preventDefault();
    if (busy || pending || gmUnresolved() || !current || !gmEnabled()) return;
    const prompt = $("gm-prompt").value.trim();
    if (!prompt || prompt.length > 2000) { notice("Describe your approach in 2,000 characters or fewer."); return; }
    if (!navigator.onLine || !playerId) { notice("Reconnect before asking about this scene.", true); return; }
    const item = { player_id: playerId, campaign_id: current.id, request: { request_id: uuid(), expected_revision: current.revision, prompt }, status: "saved", created_at: new Date().toISOString() };
    if (!saveGM(item)) return;
    gmPollCount = 0; stopGMPoll(); setBusy(true); clearNotice();
    try {
      adoptSession(await api("/api/session")); requireGMOwner();
      acceptGMResponse(await api(`/api/campaigns/${encodeURIComponent(item.campaign_id)}/gm-requests`, { method: "POST", body: item.request }));
    } catch (error) { handleGMError(error); }
    finally { setBusy(false); scheduleGMPoll(); }
  }
  async function checkGM(allowPost = false) {
    if (busy || !gmUnresolved() || pending && allowPost) return;
    stopGMPoll();
    if (!navigator.onLine) { notice("Reconnect to check the original assistant request.", true); return; }
    setBusy(true); clearNotice();
    try {
      adoptSession(await api("/api/session")); requireGMOwner();
      const item = gmRequest;
      if (current?.id !== item.campaign_id) renderCampaign(await api(`/api/campaigns/${encodeURIComponent(item.campaign_id)}`));
      let response;
      try { response = await api(`/api/campaigns/${encodeURIComponent(item.campaign_id)}/gm-requests/${encodeURIComponent(item.request.request_id)}`); }
      catch (error) {
        if (error.status !== 404) throw error;
        if (!allowPost) { saveGM({ ...gmRequest, status: "not_found" }); return; }
        const latest = await api(`/api/campaigns/${encodeURIComponent(item.campaign_id)}`); renderCampaign(latest);
        if (!gmEnabled() || latest.revision !== item.request.expected_revision) {
          saveGM({ ...gmRequest, status: "rejected", error: "The story or assistant availability has changed. Review the current scene before asking a new question." }); return;
        }
        response = await api(`/api/campaigns/${encodeURIComponent(item.campaign_id)}/gm-requests`, { method: "POST", body: item.request });
      }
      acceptGMResponse(response);
    } catch (error) { handleGMError(error); }
    finally { setBusy(false); scheduleGMPoll(); }
    if (csrfToken && pending && !gmUnresolved()) await sendPending();
  }
  async function useGMProposal() {
    if (busy || pending || gmUnresolved() || !gmChoice()) return;
    const item = gmRequest; let choice = null;
    setBusy(true); clearNotice();
    try {
      adoptSession(await api("/api/session"));
      if (playerId !== item.player_id) throw new ApiError("Recover the original connection before using this suggestion.", 403);
      renderCampaign(await api(`/api/campaigns/${encodeURIComponent(item.campaign_id)}`));
      choice = gmChoice();
      if (!choice) notice("The story or available choice changed after this suggestion. Review the current choices or ask again; no action was taken.");
    } catch (error) { notice(`${error.message} No action was taken.`, true); }
    finally { setBusy(false); }
    if (choice) choose(choice);
  }
  function clearGMResponse(focus = false) {
    if (busy || gmUnresolved()) return;
    stopGMPoll(); saveGM(null); $("gm-prompt").value = ""; renderGM();
    if (focus) $("gm-prompt").focus();
  }

  function showRecovery(code) {
    if (!code || typeof code !== "string") return;
    recoveryCode = code; $("recovery-code").textContent = code; $("recovery-card").hidden = false;
  }
  function recoveryConfirmation(show) {
    $("replace-recovery-confirmation").hidden = !show;
    $("new-recovery-code").setAttribute("aria-expanded", String(show));
  }
  async function replaceRecoveryCode() {
    if (busy || pending || gmUnresolved() || !csrfToken) return;
    setBusy(true); clearNotice();
    try {
      const result = await api("/api/session/recovery-code", { method: "POST", body: {} });
      if (typeof result.recovery_code !== "string" || !result.recovery_code) throw new ApiError("The new code wasn’t received.", 0);
      recoveryConfirmation(false); showRecovery(result.recovery_code);
      $("recovery-card").scrollIntoView({ block: "start", behavior: "smooth" });
      $("copy-recovery").focus({ preventScroll: true });
      toast("New recovery code ready. Keep this one.");
    } catch (error) {
      if (error.status === 401 || error.status === 403) notice("Your connection needs to be checked before replacing the code. Reload this page, or restore your original recovery code.", true);
      else notice("The new code couldn’t be confirmed. If this browser is still connected, try replacing it again and keep the code that is shown.", true);
    } finally { setBusy(false); }
  }
  function download(text, filename, type = "text/plain") {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  async function exportCampaign() {
    if (!current || pending || gmUnresolved() || busy) return;
    const button = $("export-campaign"); button.disabled = true;
    try {
      const response = await fetch(`/api/campaigns/${encodeURIComponent(current.id)}/export`, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("The save copy couldn’t be downloaded. Try again when connected.");
      const text = await response.text(); JSON.parse(text);
      download(text, `white-tower-sample-turn-${current.revision}.json`, "application/json"); toast("Save copy downloaded.");
    } catch (error) { notice(error.message, true); }
    finally { button.disabled = busy || !!pending || gmUnresolved(); }
  }
  async function loadLibrary() {
    const data = await api("/api/campaigns"); campaigns = data.campaigns || []; renderLibrary();
    if (pending) return;
    const selected = gmUnresolved() && gmRequest.player_id === playerId ? gmRequest.campaign_id : stored(STORAGE.selected);
    const next = campaigns.find(c => c.id === selected) || campaigns[0];
    if (next) renderCampaign(await api(`/api/campaigns/${encodeURIComponent(next.id)}`));
    else { current = null; $("game").hidden = true; $("welcome").hidden = false; }
  }
  async function initialize() {
    if (busy) return;
    setBusy(true); clearNotice(); connection("Connecting to your saved stories…", "connecting");
    try {
      const session = await api("/api/session", pending || gmUnresolved() ? {} : { method: "POST", body: {} });
      adoptSession(session);
      showRecovery(session.recovery_code);
      await loadLibrary();
      requirePendingOwner();
      requireGMOwner();
      connection("Connected · your progress is saved online");
      if (!storageAvailable) notice("Saved site data is disabled in this browser. Enable it before playing so interrupted saves can be recovered.", true);
    } catch (error) {
      if (error.status === 401 || error.status === 403) { csrfToken = null; playerId = null; if (pending || gmUnresolved()) $("restore-details").open = true; }
      connection("Could not connect · your saved stories are unchanged", "offline"); notice(error.message || "Could not connect to your saved stories.", true, initialize);
    }
    finally { setBusy(false); }
    if (csrfToken && gmUnresolved()) await checkGM();
    else if (csrfToken && pending) await sendPending();
  }
  async function restore(event) {
    event.preventDefault(); if (busy) return;
    const code = $("restore-code").value.trim(); if (!code) return;
    setBusy(true); clearNotice(); let restored = false;
    try {
      const session = await api("/api/session/recover", { method: "POST", body: { recovery_code: code } });
      adoptSession(session);
      $("restore-code").value = ""; $("restore-details").open = false;
      $("recovery-card").hidden = true; recoveryCode = null;
      showRecovery(session.recovery_code); persist(STORAGE.selected, null); current = null; await loadLibrary();
      requirePendingOwner();
      requireGMOwner();
      restored = true;
      connection("Connected · your saved stories are restored"); toast("Your stories are restored.");
    } catch (error) {
      if (error.status === 401 || error.status === 403) { csrfToken = null; playerId = null; }
      notice(error.status === 401 || error.status === 404 ? "That recovery code wasn’t recognised. Check the complete code from your original browser." : error.message, true);
    }
    finally { setBusy(false); }
    if (restored && gmUnresolved()) await checkGM();
    else if (restored && pending) await sendPending();
  }

  // Narrow interface for the reading/character companion. All mutations still
  // pass through the existing owner-bound pending request and action resolver.
  window.whiteTowerPlay = {
    context: () => ({ current, playerId, blocked: busy || !!pending || gmUnresolved() }),
    notes: async (id, update) => {
      if (!current || current.id !== id) throw new Error("Open the original story first.");
      return api(`/api/campaigns/${encodeURIComponent(id)}/notes`, update ? {method:"POST",body:update} : {});
    },
    journal: async (q, before) => {
      if (!current) throw new Error("Open a story first.");
      return api(`/api/campaigns/${encodeURIComponent(current.id)}/journal?q=${encodeURIComponent(q)}&before=${before || Number.MAX_SAFE_INTEGER}`);
    },
    intent: async (prompt) => {
      if (busy || pending || gmUnresolved() || !current) return {kind:"clarify", message:"Finish checking your saved action before choosing another."};
      const original = {id:current.id, revision:current.revision, player:playerId};
      setBusy(true);
      try {
        adoptSession(await api("/api/session"));
        if (playerId !== original.player) throw new ApiError("Recover the original connection before continuing.",403);
        const reply = await api(`/api/campaigns/${encodeURIComponent(original.id)}/intent`, {method:"POST",body:{expected_revision:original.revision,prompt}});
        if (current.id !== original.id || current.revision !== original.revision) throw new ApiError("The scene changed. Review your approach again.",409);
        if (reply.choice && !current.state.choices.some(c => c.id === reply.choice.id && c.choice_hash === reply.choice.choice_hash)) throw new ApiError("The available approach changed. Refresh first.",409);
        return reply;
      } catch (error) {
        if (error.status === 409) { try { renderCampaign(await api(`/api/campaigns/${encodeURIComponent(original.id)}`)); } catch (_) {} }
        return {kind:"clarify",message:error.message};
      } finally {setBusy(false);}
    },
    choose: (choice) => {
      const actual = current?.state.choices.find(c => c.id === choice.id && c.choice_hash === choice.choice_hash);
      if (actual) choose(actual);
    }
  };

  $("start-campaign").addEventListener("click", createCampaign);
  $("new-campaign").addEventListener("click", createCampaign);
  $("retry-action").addEventListener("click", () => csrfToken ? sendPending() : initialize());
  $("refresh-campaign").addEventListener("click", () => current && loadCampaign(current.id));
  $("export-campaign").addEventListener("click", exportCampaign);
  $("gm-form").addEventListener("submit", askGM);
  $("gm-proposal").addEventListener("click", useGMProposal);
  $("gm-retry").addEventListener("click", () => { gmPollCount = 0; return csrfToken ? checkGM(gmRequest?.status === "not_found") : initialize(); });
  $("gm-new").addEventListener("click", () => clearGMResponse(true));
  $("gm-dismiss").addEventListener("click", () => clearGMResponse());
  $("restore-form").addEventListener("submit", restore);
  $("new-recovery-code").addEventListener("click", () => recoveryConfirmation(true));
  $("cancel-recovery-code").addEventListener("click", () => { recoveryConfirmation(false); $("new-recovery-code").focus(); });
  $("confirm-recovery-code").addEventListener("click", replaceRecoveryCode);
  $("risk-dialog").addEventListener("close", () => {
    const choice = dialogChoice; const context = dialogContext; dialogChoice = null; dialogContext = null;
    if ($("risk-dialog").returnValue !== "confirm" || !choice) return;
    if (context?.campaign_id !== current?.id || context?.revision !== current?.revision || !current.state.choices?.some(c => c.id === choice.id && c.choice_hash === choice.choice_hash)) {
      notice("The story changed while you reviewed this approach. Review the current choices before acting; no action was taken."); return;
    }
    submitChoice(choice);
  });
  $("copy-recovery").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(recoveryCode); toast("Recovery code copied."); }
    catch (_) { const selection = window.getSelection(); const range = document.createRange(); range.selectNodeContents($("recovery-code")); selection.removeAllRanges(); selection.addRange(range); toast("Select and copy the highlighted code."); }
  });
  $("download-recovery").addEventListener("click", () => {
    if (recoveryCode) download(`White Tower — private recovery code\n\nWebsite: ${location.origin}\nRecovery code: ${recoveryCode}\n\nOpen the website on your phone, choose “Recovery and another browser”, and enter this code. Anyone with this code can access your sample stories. Keep it private.\n`, "white-tower-recovery-code.txt");
  });
  $("dismiss-recovery").addEventListener("click", () => { $("recovery-card").hidden = true; $("recovery-code").textContent = ""; recoveryCode = null; });
  window.addEventListener("offline", () => { stopGMPoll(); connection("Offline · reconnect to continue", "offline"); setBusy(busy); });
  window.addEventListener("online", () => { connection(pending ? "Connected · check your saved choice" : "Connected · your progress is saved online"); setBusy(busy); });
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE.gm && !busy) {
      try { gmRequest = JSON.parse(event.newValue || "null"); } catch (_) { return; }
      stopGMPoll(); setBusy(false);
    }
    if (event.key === STORAGE.pending && !busy) {
      try { pending = JSON.parse(event.newValue || "null"); } catch (_) { return; }
      if (!pending && current) { notice("Another window may have updated your story. Refresh before choosing your next action."); loadCampaign(current.id); }
      else setBusy(false);
    }
  });
  initialize();
})();
