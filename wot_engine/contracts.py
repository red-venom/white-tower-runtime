"""Canonical data, deterministic dice, and strict event contracts for the game."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import hmac
import json
import re
import unicodedata

MAX_INT = 2**53 - 1
MAX_ENVELOPE_BYTES = 32 * 1024


class ContractError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def normalize(value):
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        require(-MAX_INT <= value <= MAX_INT, "integer range")
        return value
    if type(value) is str:
        value = unicodedata.normalize("NFC", value)
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ContractError("invalid Unicode") from exc
        return value
    if type(value) is list:
        return [normalize(item) for item in value]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            require(type(key) is str, "non-string key")
            key = normalize(key)
            require(key not in result, "normalized key collision")
            result[key] = normalize(item)
        return result
    raise ContractError("unsupported JSON type")


def canonical(value):
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def parse_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate input key")
            result[key] = value
        return result
    def invalid_number(_):
        raise ContractError("float or nonfinite number")
    try:
        return normalize(json.loads(text, object_pairs_hook=pairs,
                                    parse_float=invalid_number,
                                    parse_constant=invalid_number))
    except json.JSONDecodeError as exc:
        raise ContractError("invalid JSON") from exc


def digest(value):
    return sha256(canonical(value)).hexdigest()


def hashed_record(value, field):
    return digest({key: item for key, item in value.items() if key != field})


def accept_draw(x, sides, bits=256):
    require(type(sides) is int and 2 <= sides <= 1000, "die sides")
    require(type(x) is int and 0 <= x < 2**bits, "draw range")
    limit = 2**bits - (2**bits % sides)
    return None if x >= limit else 1 + x % sides


def die(seed, campaign_id, action_id, roll_key, sides, digest_fn=None):
    require(type(seed) is bytes and len(seed) == 32, "seed length")
    require(sides in (3, 10), "unsupported v1 die")
    for counter in range(1024):
        message = canonical({"campaign_id": campaign_id, "action_id": action_id,
                             "roll_key": roll_key, "rejection_counter": counter})
        raw = (digest_fn(counter) if digest_fn else
               hmac.new(seed, message, "sha256").digest())
        require(type(raw) is bytes and len(raw) == 32, "digest length")
        value = accept_draw(int.from_bytes(raw, "big"), sides)
        if value is not None:
            return value, counter, raw.hex()
    raise ContractError("bounded rejection work exhausted; retry same die")


ID = ("str", r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
KEY = ("str", r"[A-Za-z0-9][A-Za-z0-9_/:.-]{0,127}")
TEXT = ("str", r"[\s\S]{1,4000}")
NARRATION = ("str", r"[\s\S]{1,12000}")
HASH = ("str", r"[0-9a-f]{64}")
NAT = ("int", 0, MAX_INT)
BOOL = ("bool",)
JSON = ("json",)


def enum(*values):
    return ("enum", values)


def array(item, maximum=256):
    return ("array", item, maximum)


def nullable(item):
    return ("nullable", item)


CHANGE = {"record_id": ID, "field_id": ID, "before": JSON, "after": JSON}
ROLL_REQUEST = {"key": KEY, "sides": enum(3, 10)}
ROLL_RESULT = {**ROLL_REQUEST, "value": ("int", 1, 10), "rejection_counter": NAT}
BAND = {"summary": TEXT, "changes": array(CHANGE), "permanent_loss": BOOL}
CHECK = {"difficulty": ("int", 0, 99),
         "attribute": enum("body", "grace", "wits", "will", "presence"),
         "attribute_rating": ("int", 0, 3), "skill_id": ID,
         "skill_rating": ("int", 0, 4), "modifier": enum(-2, 0, 2)}
RISK = {"specific_loss": TEXT, "alternative": TEXT, "consent_ref": ID}
STAKES = {"goal": TEXT, "method": TEXT, "check": nullable(CHECK),
          "time_seconds": NAT, "upfront_changes": array(CHANGE),
          "bands": {"clean": BAND, "costly": BAND, "setback": BAND},
          "rolls": array(ROLL_REQUEST, 32), "irreversible_risk": nullable(RISK)}
ACTION = {"schema": enum("action-v1"), "campaign_id": ID, "action_id": ID,
          "actor_id": ID, "expected_head_hash": HASH, "rules_version": ID,
          "content_version": ID, "engine_version": ID,
          "intent_text": TEXT, "stakes": STAKES, "stakes_hash": HASH,
          "auxiliary_changes": array(CHANGE), "npc_proposal_hashes": array(HASH),
          "acceptance_ref": ID}
EVENT = {"schema": enum("event-v1"), "campaign_id": ID, "action_id": ID,
         "sequence": ("int", 1, MAX_INT), "origin_epoch": ("int", 1, MAX_INT),
         "parent_hash": HASH, "rules_version": ID, "accepted_action_hash": HASH,
         "content_version": ID, "engine_version": ID,
         "stakes_hash": HASH, "before_state_hash": HASH, "after_state_hash": HASH,
         "dice": array(ROLL_RESULT, 32), "outcome": enum("clean", "costly", "setback", "routine"),
         "changes": array(CHANGE), "npc_proposal_hashes": array(HASH),
         "public_narration": NARRATION, "revealed_fact_ids": array(ID), "event_hash": HASH}
ENVELOPE = {"schema": enum("remote-envelope-v1"), "accepted_action": ACTION,
            "event": EVENT, "envelope_hash": HASH}
FACT = {"fact_id": ID, "statement": TEXT, "basis": enum("observation", "message", "inference", "gm"),
        "source_ids": array(ID), "visibility": enum("public", "npc", "gm"), "audience_ids": array(ID)}
PACKET = {"schema": enum("packet-v1"), "campaign_id": ID,
          "recipient_role": enum("player", "npc", "steward"), "recipient_id": ID,
          "head_hash": HASH, "facts": array(FACT), "packet_hash": HASH}
PROPOSAL = {"schema": enum("npc-proposal-v1"), "campaign_id": ID, "proposal_id": ID,
            "npc_id": ID, "head_hash": HASH, "packet_hash": HASH, "decision": TEXT,
            "evidence_ids": array(ID), "proposed_changes": array(CHANGE),
            "rule_ids": array(ID), "valid_until_second": NAT}
PHASE_NAMES = ("OFFERED", "ACCEPTED", "RESOLVED", "PREPARED", "SELECTED",
               "COMMIT_UNCERTAIN", "COMMITTED", "PROJECTING", "READY", "DELIVERED", "CANCELLED")
ERROR_CODES = ("INVALID_SCHEMA", "HASH_MISMATCH", "STALE_HEAD", "ACTION_CONFLICT",
               "STAKES_CHANGED", "PRECONDITION_FAILED", "KNOWLEDGE_VIOLATION",
               "WRITER_FENCED", "UNSUPPORTED_VERSION", "AUTH_REQUIRED", "PERMISSION_DENIED",
               "REMOTE_UNCERTAIN", "RATE_LIMITED", "PROJECTION_PENDING", "FORK_DETECTED",
               "RECOVERY_REQUIRED", "RETRY_BUDGET", "MANUAL_REVIEW_REQUIRED")
PHASE = {"schema": enum("phase-v1"), "campaign_id": ID, "action_id": ID,
         "phase": enum(*PHASE_NAMES), "selected_page_id": nullable(ID),
         "event_hash": nullable(HASH), "envelope_hash": nullable(HASH), "retry_at_ms": nullable(NAT),
         "error_code": nullable(enum(*ERROR_CODES))}
ERROR = {"code": enum(*ERROR_CODES), "public_message": TEXT, "retryable": BOOL,
         "retry_at_ms": nullable(NAT)}
RESPONSE = {"schema": enum("response-v1"), "status": enum("OK", "PENDING", "BLOCKED", "ERROR"),
            "campaign_id": ID, "action_id": nullable(ID), "phase": nullable(enum(*PHASE_NAMES)),
            "event_hash": nullable(HASH), "narration": nullable(NARRATION),
            "receipt_id": nullable(ID), "error": nullable(ERROR)}
WEAVE = {"weave_id": ID, "load": ("int", 1, 10)}
STATE = {"potential": ("int", 8, 10), "capacity": ("int", 3, 10), "control": ("int", 1, 4),
         "held": array(WEAVE, 4), "tied": array(WEAVE, 4), "strain": ("int", 0, 20),
         "vitality": NAT, "max_vitality": ("int", 1, 12), "wounds": ("int", 0, 3),
         "supply": ("int", 0, 6), "silver": NAT}
CONTRACTS = {"action": ACTION, "event": EVENT, "remote_envelope": ENVELOPE,
             "packet": PACKET, "npc_proposal": PROPOSAL,
             "phase": PHASE, "response": RESPONSE, "natural_channeling_state": STATE}


def shape(value, spec):
    normalize(value)
    if type(spec) is dict:
        require(type(value) is dict and set(value) == set(spec), "closed record fields")
        for key in spec:
            shape(value[key], spec[key])
    elif spec[0] == "nullable":
        if value is not None:
            shape(value, spec[1])
    elif spec[0] == "int":
        require(type(value) is int and spec[1] <= value <= spec[2], "integer bounds")
    elif spec[0] == "str":
        require(type(value) is str and re.fullmatch(spec[1], value) is not None, "string type or bounds")
    elif spec[0] == "bool":
        require(type(value) is bool, "boolean required")
    elif spec[0] == "enum":
        require(any(type(value) is type(v) and value == v for v in spec[1]), "enum value")
    elif spec[0] == "array":
        require(type(value) is list and len(value) <= spec[2], "array bounds")
        for item in value:
            shape(item, spec[1])
    elif spec[0] != "json":
        raise AssertionError("bad specification")


def action_valid(action):
    action = normalize(action)
    shape(action, ACTION)
    require(action["stakes_hash"] == digest(action["stakes"]), "stakes hash mismatch")
    stakes = action["stakes"]
    keys = [r["key"] for r in stakes["rolls"]]
    require(len(keys) == len(set(keys)), "duplicate roll key")
    require((stakes["check"] is None) == (not stakes["rolls"]), "routine/check roll mismatch")
    if stakes["check"] is not None:
        require(len(stakes["rolls"]) == 2 and all(r["sides"] == 10 for r in stakes["rolls"]),
                "core check requires 2d10")
    if any(b["permanent_loss"] for b in stakes["bands"].values()):
        require(stakes["irreversible_risk"] is not None, "missing specific risk consent")
    require(all(c["record_id"] != action["actor_id"] for c in action["auxiliary_changes"]),
            "private auxiliary effect on acting character")


def apply_changes(before, changes):
    after = normalize(deepcopy(before))
    for change in normalize(changes):
        record, field = change["record_id"], change["field_id"]
        require(record in after and field in after[record], "unknown transition target")
        require(canonical(after[record][field]) == canonical(change["before"]), "state precondition mismatch")
        after[record][field] = deepcopy(change["after"])
    return after


def event_valid(event, frozen_action, context):
    event, frozen_action = normalize(event), normalize(frozen_action)
    shape(event, EVENT)
    action_valid(frozen_action)
    for key in ("campaign_id", "rules_version", "content_version", "engine_version", "origin_epoch"):
        require(event[key] == context[key], "trusted context mismatch")
    require(event["sequence"] == context["sequence"] + 1, "wrong successor sequence")
    require(event["parent_hash"] == context["head_hash"], "stale trusted head")
    for change in frozen_action["auxiliary_changes"]:
        require((change["record_id"], change["field_id"]) in context["private_npc_fields"],
                "auxiliary effect outside trusted private NPC fields")
    require(event["accepted_action_hash"] == digest(frozen_action), "accepted action changed")
    for event_key, action_key in (("campaign_id", "campaign_id"), ("action_id", "action_id"),
                                  ("parent_hash", "expected_head_hash"), ("rules_version", "rules_version"),
                                  ("content_version", "content_version"), ("engine_version", "engine_version"),
                                  ("stakes_hash", "stakes_hash")):
        require(event[event_key] == frozen_action[action_key], "action binding mismatch")
    requested = {(r["key"], r["sides"]) for r in frozen_action["stakes"]["rolls"]}
    actual = {(r["key"], r["sides"]) for r in event["dice"]}
    require(actual == requested and len(actual) == len(event["dice"]), "dice manifest mismatch")
    require(all(r["value"] <= r["sides"] for r in event["dice"]), "die out of range")
    for result in event["dice"]:
        expected_value, expected_counter, _ = die(context["seed"], event["campaign_id"],
                                                  event["action_id"], result["key"], result["sides"])
        require((result["value"], result["rejection_counter"]) == (expected_value, expected_counter),
                "dice do not replay from trusted seed")
    check = frozen_action["stakes"]["check"]
    outcome = "routine"
    if check:
        total = sum(r["value"] for r in event["dice"]) + check["attribute_rating"] + check["skill_rating"] + check["modifier"]
        gap = check["difficulty"] - total
        outcome = "clean" if gap <= 0 else "costly" if gap <= 3 else "setback"
    require(event["outcome"] == outcome, "wrong outcome band")
    band = frozen_action["stakes"]["bands"]["clean" if outcome == "routine" else outcome]
    expected_changes = compose_changes(frozen_action["stakes"]["upfront_changes"],
                                       band["changes"], frozen_action["auxiliary_changes"])
    require(canonical(event["changes"]) == canonical(expected_changes), "undeclared or changed effects")
    require(event["npc_proposal_hashes"] == frozen_action["npc_proposal_hashes"], "NPC commitments changed")
    require(event["event_hash"] == hashed_record(event, "event_hash"), "event hash mismatch")
    fields = [(c["record_id"], c["field_id"]) for c in event["changes"]]
    require(len(fields) == len(set(fields)), "duplicate state field mutation")
    before = context["state"]
    require(event["before_state_hash"] == digest(before), "wrong before state hash")
    after = apply_changes(before, event["changes"])
    require(event["after_state_hash"] == digest(after), "wrong after state hash")
    shape(after["world"]["time_seconds"], NAT)
    require(after["world"]["time_seconds"] - before["world"]["time_seconds"] == frozen_action["stakes"]["time_seconds"],
            "elapsed time differs from accepted stakes")
    return after


def envelope_valid(envelope, trusted_context):
    """Validate publication contents; no marker, storage, or trust-loader behavior."""
    envelope = normalize(envelope)
    shape(envelope, ENVELOPE)
    require(len(canonical(envelope)) <= MAX_ENVELOPE_BYTES, "remote envelope byte limit")
    require(envelope["envelope_hash"] == hashed_record(envelope, "envelope_hash"),
            "envelope hash mismatch")
    return event_valid(envelope["event"], envelope["accepted_action"], trusted_context)


def restore_remote_envelope(payload, trusted_context):
    """Reconstruct one ordinary action without a local reservation or chat history."""
    require(type(payload) is bytes and len(payload) <= MAX_ENVELOPE_BYTES,
            "remote envelope byte limit")
    try:
        envelope = parse_json(payload.decode("utf-8", errors="strict"))
    except UnicodeDecodeError as exc:
        raise ContractError("invalid envelope UTF-8") from exc
    require(canonical(envelope) == payload, "noncanonical remote envelope bytes")
    after = envelope_valid(envelope, trusted_context)
    return {"accepted_action": deepcopy(envelope["accepted_action"]),
            "event": deepcopy(envelope["event"]), "state": after,
            "envelope_hash": envelope["envelope_hash"]}


def precommit_envelope_valid(envelope, reserved_action, trusted_context):
    """Normal publication must also match the independently frozen local action."""
    after = envelope_valid(envelope, trusted_context)
    action_valid(reserved_action)
    require(canonical(envelope["accepted_action"]) == canonical(reserved_action),
            "remote action differs from immutable local reservation")
    return after


def compose_changes(*groups):
    merged = {}
    for group in groups:
        group = normalize(group)
        fields = [(c["record_id"], c["field_id"]) for c in group]
        require(len(fields) == len(set(fields)), "duplicate effect within one phase")
        for change in group:
            key = (change["record_id"], change["field_id"])
            if key in merged:
                require(canonical(merged[key]["after"]) == canonical(change["before"]), "effect composition mismatch")
                merged[key]["after"] = deepcopy(change["after"])
            else:
                merged[key] = deepcopy(change)
    return [merged[key] for key in sorted(merged)]


def phase_transition(before, after):
    successors = {"OFFERED": {"ACCEPTED", "CANCELLED"}, "ACCEPTED": {"RESOLVED"},
                  "RESOLVED": {"PREPARED"}, "PREPARED": {"SELECTED"},
                  "SELECTED": {"COMMIT_UNCERTAIN", "COMMITTED"},
                  "COMMIT_UNCERTAIN": {"COMMITTED"}, "COMMITTED": {"PROJECTING"},
                  "PROJECTING": {"READY"}, "READY": {"DELIVERED"}, "DELIVERED": set(),
                  "CANCELLED": set()}
    require(before in successors and after in successors, "unknown phase")
    require(after == before or after in successors[before], "illegal phase transition")


def packet_valid(packet):
    shape(packet, PACKET)
    require(packet["packet_hash"] == hashed_record(packet, "packet_hash"), "packet hash")
    ids = [fact["fact_id"] for fact in packet["facts"]]
    require(len(ids) == len(set(ids)), "duplicate fact identifier")
    for fact in packet["facts"]:
        if packet["recipient_role"] == "player":
            require(fact["visibility"] == "public", "private fact in player packet")
        elif packet["recipient_role"] == "npc":
            require(fact["visibility"] == "public" or
                    (fact["visibility"] == "npc" and packet["recipient_id"] in fact["audience_ids"]),
                    "NPC cannot know fact")


def proposal_valid(proposal, packet, now_seconds):
    shape(proposal, PROPOSAL)
    packet_valid(packet)
    require(packet["recipient_role"] == "npc" and proposal["npc_id"] == packet["recipient_id"], "NPC recipient mismatch")
    require(all(proposal[k] == packet[k] for k in ("campaign_id", "head_hash", "packet_hash")), "proposal packet binding")
    require(set(proposal["evidence_ids"]) <= {f["fact_id"] for f in packet["facts"]}, "unavailable evidence")
    shape(now_seconds, NAT)
    require(proposal["valid_until_second"] >= now_seconds, "expired NPC proposal")


def response_valid(response):
    shape(response, RESPONSE)
    if response["narration"] is not None:
        require(response["status"] == "OK" and response["phase"] in ("READY", "DELIVERED"), "early narration")
        require(response["receipt_id"] is not None and response["event_hash"] is not None, "missing save receipt")
    if response["status"] != "OK":
        require(response["error"] is not None, "missing error details")


def state_valid(state):
    shape(state, STATE)
    require(state["capacity"] <= state["potential"], "capacity exceeds potential")
    require(state["strain"] <= 2 * state["capacity"], "strain limit")
    require(state["vitality"] <= state["max_vitality"], "vitality limit")
    require(len(state["held"]) <= state["control"] and len(state["tied"]) <= state["control"], "weave slots")
    require(sum(w["load"] for w in state["held"] + state["tied"]) <= state["capacity"], "committed load")


def cast_projection(state, load, sustained):
    state_valid(state)
    require(type(load) is int and load >= 1, "positive integer load")
    require(type(sustained) is bool, "sustained boolean")
    require(sum(w["load"] for w in state["held"] + state["tied"]) + load <= state["capacity"], "cast load limit")
    require(state["strain"] + load <= 2 * state["capacity"], "cast strain limit")
    require(not sustained or len(state["held"]) < state["control"], "held slot unavailable")
    new_strain = state["strain"] + load
    return new_strain, 2 if new_strain > state["capacity"] else 0

