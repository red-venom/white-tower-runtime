"""Deterministic initial-six rules. No model, network, or campaign writes.

Intents are closed JSON records. ``intent_text`` stores their canonical JSON,
so execute-time validation can rebuild the entire accepted offer.
This bounded module supports safe institutional practice and published foes.
It does not implement promotion, chapter rewards, travel, or later weaves.
"""
from __future__ import annotations

from copy import deepcopy

from .contracts import (
    ContractError, action_valid, canonical, die, digest, normalize, parse_json,
)

RULES_VERSION = "rules-v1"
CONTENT_VERSION = "content-initial-six-v1"
ENGINE_VERSION = "engine-v1"
ATTRIBUTES = ("body", "grace", "wits", "will", "presence")
SKILLS = ("athletics", "melee", "marksmanship", "stealth", "survival", "notice",
          "scholarship", "medicine", "persuasion", "insight", "leadership", "composure")
FLOWS = ("air", "earth", "fire", "water", "spirit")
WEAVES = {
    "W01": {"name": "Spark", "control": 1, "flows": {"fire": 1}, "load": 1, "range": 10, "held": False},
    "W02": {"name": "Air Hand", "control": 1, "flows": {"air": 1}, "load": 1, "range": 10, "held": True},
    "W03": {"name": "Air Binding", "control": 2, "flows": {"air": 2, "spirit": 1}, "load": 2, "range": 10, "held": True},
    "W04": {"name": "Warning Ward", "control": 2, "flows": {"spirit": 2, "air": 1}, "load": 2, "range": 10, "held": True},
    "W05": {"name": "Elemental Guard", "control": 2, "flows": {"air": 2, "earth": 1, "fire": 1, "water": 1}, "load": 2, "range": 5, "held": True},
    "W06": {"name": "Healing", "control": 3, "flows": {"water": 2, "spirit": 2, "air": 1}, "load": 3, "range": 0, "held": False},
}
PUBLIC_PC_FIELDS = (
    "name", "rank", "level", "attributes", "skills", "vitality", "max_vitality",
    "wounds", "supply", "silver", "control", "flows", "capacity", "known_weaves",
    "held", "tied", "strain", "embraced", "study_progress", "learning_opportunities",
    "pending_work_seconds", "support_pending", "firstaid_used", "healing_used",
    "warning_ready",
)
PUBLIC_WORLD_FIELDS = (
    "time_seconds", "location", "scene_id", "scene_description", "choices",
    "active_conflict", "safe", "supplied", "completed_checks", "defeat_pending",
    "episode", "event_queue", "last_event", "last_oath_result",
)
PUBLIC_NPC_FIELDS = (
    "name", "role", "location", "motive", "competences", "boundary", "bond",
    "support_remaining", "willing", "vitality", "max_vitality", "wounds",
    "oaths_active",
)
PRIVATE_NPC_FIELDS = (("npc-mentor", "private_oath_ruling"),)


class RuleError(ContractError):
    """A rejected intent never changes the supplied state."""

    def __init__(self, message, code="ILLEGAL_ACTION"):
        super().__init__(message)
        self.code = code


def _require(condition, message, code="ILLEGAL_ACTION"):
    if not condition:
        raise RuleError(message, code)


def _integer(value, minimum=0, maximum=2**53 - 1):
    return type(value) is int and minimum <= value <= maximum


def _closed(intent, required, optional=()):
    _require(type(intent) is dict, "Intent must be an object.")
    _require(set(intent) <= {"verb", *required, *optional}, "Unknown intent field.", "UNSUPPORTED_INTENT")
    _require(set(required) <= set(intent), "Missing intent field.")
    strings = {"weave_id", "target_id", "mode", "cost", "concentration", "held_id", "tied_id",
               "operation", "kind", "course_id", "source", "ally_id", "skill_id", "task_id"}
    for key in strings & set(intent):
        _require(type(intent[key]) is str and 1 <= len(intent[key]) <= 128, "Invalid text field: " + key)
    for key in {"seconds", "area_metres", "distance_metres"} & set(intent):
        _require(_integer(intent[key]), "Invalid integer field: " + key)
    if "difficulty" in intent:
        _require(intent["difficulty"] is None or _integer(intent["difficulty"]), "Invalid difficulty.")
    if "companions" in intent:
        _require(type(intent["companions"]) is list and all(type(x) is str for x in intent["companions"]), "Invalid companions.")


def initial_state(name="Test novice", *, seed: bytes, campaign_id: str, episode=True) -> dict:
    """Create the fixed example novice. Potential uses one stable genesis die."""
    _require(type(name) is str and 1 <= len(name) <= 120, "Name must contain 1–120 characters.")
    value, counter, _ = die(seed, campaign_id, "genesis", "potential/die-0", 3)
    skills = dict.fromkeys(SKILLS, 0)
    skills.update(scholarship=2, composure=2, melee=1, notice=1, medicine=1, persuasion=1)
    pc = {
        "name": name, "rank": "novice", "level": 1,
        "attributes": dict(zip(ATTRIBUTES, (1, 1, 2, 2, 0))), "skills": skills,
        "vitality": 8, "max_vitality": 8, "wounds": 0, "supply": 4, "silver": 6,
        "control": 1, "flows": {f: (2 if f == "air" else 1) for f in FLOWS},
        "capacity": 3, "potential": value + 7,
        "potential_die": {"value": value, "rejection_counter": counter},
        "known_weaves": ["W01", "W02"], "held": [], "tied": [], "strain": 0,
        "embraced": False, "firstaid_used": False, "healing_used": False,
        "last_break_end": None, "study_progress": {}, "learning_opportunities": 0,
        "pending_work_seconds": 0, "support_pending": None,
        "attempted_checks": [], "prepared_checks": [], "oaths_active": False,
    }
    state = {"pc": pc, "world": {
        "time_seconds": 0, "location": "Tower practice room", "scene_id": "practice-room",
        "scene_description": "A tutor, a peer and a steward offer safe practice and ordinary help.",
        "choices": ["Embrace and light the prepared tinder.", "Inspect the practice latch.",
                    "Study a novice foundation block.", "Ask an ally for help."],
        "safe": True, "supplied": True, "active_conflict": False,
        "next_event_second": None, "main_activity": {}, "completed_checks": [],
        "defeat_pending": False, "library_available": True,
    }}
    allies = (
        ("npc-mentor", "Maerin", "appointed tutor", ["channeling", "scholarship"],
         "Teach safe technique.", "Will not permit unconsented experiments."),
        ("npc-peer", "Lysa", "fellow novice", ["composure", "notice"],
         "Build confidence through shared work.", "Will not take blame for another person's choices."),
        ("npc-steward", "Toman", "Tower steward", ["persuasion", "medicine"],
         "Keep daily work reliable.", "Will not conceal missing supplies."),
    )
    for record_id, ally_name, role, competences, motive, boundary in allies:
        state[record_id] = {
            "kind": "person", "name": ally_name, "role": role,
            "location": state["world"]["location"], "motive": motive,
            "competences": competences, "boundary": boundary, "bond": 1,
            "support_remaining": 2, "willing": True, "consenting": True,
            "alive": True, "ordinary_target": True, "distance_m": 0, "visible": True,
            "vitality": 8, "max_vitality": 8, "wounds": 0,
            "firstaid_used": False, "healing_used": False,
            "restrained": False, "private_intent": "observe",
        }
    state["obj-tinder"] = {
        "kind": "object", "name": "prepared hearth tinder", "distance_m": 2,
        "visible": True, "mass_grams": 20, "dry_tinder": True, "lit": False,
        "simple_latch": False, "open": False, "inspected": False,
    }
    state["obj-latch"] = {
        "kind": "object", "name": "practice latch", "distance_m": 2,
        "visible": True, "mass_grams": 100, "dry_tinder": False, "lit": False,
        "simple_latch": True, "open": False, "inspected": False,
    }
    _require(type(episode) is bool, "Episode flag must be boolean.")
    if episode:
        from .story import initialize
        initialize(state)
    state = normalize(state)
    validate_state(state)
    return state


def validate_state(state):
    """Validate the resource boundaries used by this rules module."""
    normalize(state)
    _require(type(state) is dict and "pc" in state and "world" in state, "Missing state records.")
    p, w = state["pc"], state["world"]
    for field, low, high in (("potential", 8, 10), ("capacity", 3, 10), ("control", 1, 4),
                             ("vitality", 0, 12), ("max_vitality", 6, 12), ("wounds", 0, 3),
                             ("supply", 0, 6), ("silver", 0, 2**53-1), ("strain", 0, 20),
                             ("pending_work_seconds", 0, 2**53-1), ("learning_opportunities", 0, 256)):
        _require(_integer(p.get(field), low, high), "Invalid resource: " + field)
    _require(set(p["attributes"]) == set(ATTRIBUTES), "Invalid Attributes.")
    _require(all(_integer(v, 0, 3) for v in p["attributes"].values()), "Invalid Attribute rating.")
    _require(set(p["skills"]) == set(SKILLS), "Invalid Skills.")
    _require(all(_integer(v, 0, 4) for v in p["skills"].values()), "Invalid Skill rating.")
    _require(set(p["flows"]) == set(FLOWS), "Invalid Flows.")
    _require(all(_integer(v, 1, 3) for v in p["flows"].values()), "Invalid Flow rating.")
    _require(p["max_vitality"] == 6 + 2 * p["attributes"]["body"], "Maximum Vitality differs from Body.")
    _require(p["vitality"] <= p["max_vitality"], "Vitality exceeds maximum.")
    _require(p["capacity"] <= p["potential"] and p["strain"] <= 2*p["capacity"], "Channeling limit exceeded.")
    _require(type(p["held"]) is list and type(p["tied"]) is list, "Invalid committed weaves.")
    for collection in ("held", "tied"):
        for entry in p[collection]:
            _require(type(entry) is dict and set(entry) == {"id", "weave_id", "load", "target_id", "binding_contribution", "expires_at", "area_metres"}, "Invalid weave instance.")
            _require(entry["weave_id"] in WEAVES and WEAVES[entry["weave_id"]]["held"], "Invalid sustained form.")
            _require(_integer(entry["load"], 1, 3) and entry["load"] == WEAVES[entry["weave_id"]]["load"], "Invalid committed Load.")
            _require(entry["target_id"] in state and type(entry["id"]) is str, "Invalid weave target or ID.")
            _require(_integer(entry["binding_contribution"]) and _integer(entry["area_metres"], 0, 10), "Invalid weave effect bounds.")
            _require(entry["expires_at"] is None if collection == "held" else _integer(entry["expires_at"]), "Invalid weave expiry.")
            _require(collection != "tied" or entry["weave_id"] in ("W04", "W05"), "This form cannot be tied.")
    _require(len(p["held"]) <= p["control"] and len(p["tied"]) <= p["control"], "Weave slots exceeded.")
    _require(sum(x["load"] for x in p["held"] + p["tied"]) <= p["capacity"], "Committed Load exceeded.")
    keys = [(x["weave_id"], x["target_id"]) for x in p["held"] + p["tied"]]
    _require(len(keys) == len(set(keys)), "A weave cannot stack on one target.")
    _require(type(p["embraced"]) is bool and (not p["held"] or p["embraced"]), "Held weave without the Source.")
    _require(_integer(w["time_seconds"]), "Invalid world clock.")
    for record in state.values():
        if record.get("kind") == "person":
            _require(_integer(record.get("vitality"), 0, record.get("max_vitality", 0)), "Invalid patient Vitality.")
            _require(_integer(record.get("wounds"), 0, 3), "Invalid patient Wounds.")
            if "support_remaining" in record:
                _require(_integer(record["support_remaining"], 0, 2), "Invalid support uses.")
            if "resistance" in record:
                _require(_integer(record["resistance"], 0, record["max_resistance"]), "Invalid Resistance.")


def _changes(before, after):
    result = []
    _require(set(before) == set(after), "Rules cannot create or delete records.")
    for record_id in sorted(before):
        _require(set(before[record_id]) == set(after[record_id]), "Rules cannot create or delete fields.")
        for field_id in sorted(before[record_id]):
            a, b = before[record_id][field_id], after[record_id][field_id]
            if canonical(a) != canonical(b):
                result.append({"record_id": record_id, "field_id": field_id,
                               "before": deepcopy(a), "after": deepcopy(b)})
    return result


def _release_entry(state, entry):
    if entry["weave_id"] != "W03":
        return
    target = state[entry["target_id"]]
    contribution = entry.get("binding_contribution", 0)
    if "resistance" in target and not target.get("defeated", False):
        target["resistance"] = min(target["max_resistance"], target["resistance"] + contribution)
    target["restrained"] = False


def _drop(state, weave_id=None):
    kept = []
    for entry in state["pc"]["held"]:
        if weave_id is None or entry["id"] == weave_id:
            _release_entry(state, entry)
        else:
            kept.append(entry)
    state["pc"]["held"] = kept


def _safe(state):
    _require(state["world"]["safe"] and not state["world"]["active_conflict"], "Establish a safe interval first.")
    _require(state["world"]["supplied"], "Exposed-day Supply handling is outside this initial module.", "UNSUPPORTED_SCENE")


def _advance(state, seconds, *, allow_boundary=False):
    _require(_integer(seconds, 0, 28800), "Action duration outside supported interval.")
    start = state["world"]["time_seconds"]
    deadline = state["world"].get("next_event_second")
    _require(deadline is None or start + seconds < deadline or (allow_boundary and start + seconds == deadline),
             "A world event requires a decision before this action can finish.", "WORLD_EVENT_DUE")
    state["world"]["time_seconds"] += seconds
    kept = []
    for entry in state["pc"]["tied"]:
        if entry["expires_at"] <= state["world"]["time_seconds"]:
            _release_entry(state, entry)
        else:
            kept.append(entry)
    state["pc"]["tied"] = kept


def _target(state, target_id, range_m):
    _require(type(target_id) is str and target_id in state, "Unknown target.")
    if target_id == "pc":
        return state["pc"]
    target = state[target_id]
    _require(target.get("visible") is True, "Target must be visible.")
    _require(_integer(target.get("distance_m"), 0, range_m), "Target is outside range.")
    if "location" in target:
        _require(target["location"] == state["world"]["location"], "Target is elsewhere.")
    return target


def _weave_prerequisites(pc, weave_id, require_known=True):
    _require(weave_id in WEAVES, "Only W01–W06 are active.", "UNSUPPORTED_WEAVE")
    weave = WEAVES[weave_id]
    _require(not require_known or weave_id in pc["known_weaves"], "The weave has not been learned.")
    _require(pc["control"] >= weave["control"], "Control prerequisite not met.")
    _require(all(pc["flows"][flow] >= rating for flow, rating in weave["flows"].items()), "Flow prerequisite not met.")
    return weave


def _check(pc, attribute, skill, difficulty, support=True):
    modifier = 0
    pending = pc["support_pending"]
    if pending is not None and support and pending["skill_id"] == skill:
        modifier = 2
        pc["support_pending"] = None
    return {"difficulty": difficulty, "attribute": attribute,
            "attribute_rating": pc["attributes"][attribute], "skill_id": skill,
            "skill_rating": pc["control"] if skill == "channeling" else pc["skills"][skill],
            "modifier": modifier}


def _harm(state, amount, source, concentration):
    p = state["pc"]
    if source in ("projectile", "debris", "flame"):
        if any(e["weave_id"] == "W05" and e["target_id"] == "pc" for e in p["held"] + p["tied"]):
            amount = max(0, amount-1)
    if amount == 0:
        return
    p["vitality"] = max(0, p["vitality"]-amount)
    if p["vitality"] == 0:
        p["wounds"] = min(3, p["wounds"]+1)
        _drop(state)
        p["embraced"] = False
        state["world"]["active_conflict"] = False
        state["world"]["defeat_pending"] = True
    elif p["held"]:
        if concentration == "preserve":
            _require(p["strain"]+1 <= 2*p["capacity"], "Cannot afford concentration in every possible result.")
            p["strain"] += 1
        else:
            chosen = concentration if concentration not in ("drop", None) else p["held"][0]["id"]
            _require(any(e["id"] == chosen for e in p["held"]), "Unknown concentration release choice.")
            _drop(state, chosen)


def _cast(upfront, intent, action_id):
    _closed(intent, ("weave_id", "target_id"), ("mode", "difficulty", "cost", "area_metres", "concentration"))
    p, w = upfront["pc"], upfront["world"]
    _require(p["embraced"], "Embrace the Source first.")
    _require(p["pending_work_seconds"] == 0, "Finish the declared follow-up work before another cast.")
    weave_id, target_id = intent["weave_id"], intent["target_id"]
    weave = _weave_prerequisites(p, weave_id)
    mode = intent.get("mode", "utility")
    _require(mode in ("utility", "attack"), "Unsupported cast mode.")
    _require(intent.get("cost", "strain") in ("strain", "time"), "Utility cost must be strain or time.")
    concentration = intent.get("concentration", "drop")
    _require(type(concentration) is str, "Invalid concentration choice.")
    target = w if weave_id == "W04" and target_id == "world" else _target(upfront, target_id, weave["range"])
    attack = mode == "attack"
    if attack:
        _require(weave_id in ("W01", "W03"), "This attack variant is not implemented.", "UNSUPPORTED_MODE")
        _require(w["active_conflict"] and target.get("hostile") is True, "Attack requires an active published conflict.")
        _require(p["wounds"] < 3, "Three Wounds require recovery before field operations.")
        _require(not p["oaths_active"], "Oath-bound attacks require the reviewed Oaths resolver.", "UNSUPPORTED_OATH_ACTION")
        _require(target.get("resistance", 0) > 0 and not target.get("defeated", False), "Target no longer opposes the action.")
        _require(type(target.get("guard")) is int and target["guard"] in (14, 18)
                 and _integer(target.get("harm"), 1, 3), "Unsupported foe statistics.")
    else:
        _safe(upfront)
    if weave_id == "W01" and not attack:
        _require(target.get("dry_tinder") is True and not target.get("lit", False), "Spark needs unlit, dry, hand-sized prepared tinder.")
    elif weave_id == "W02":
        _require(target.get("kind") == "object" and _integer(target.get("mass_grams"), 0, 5000), "Air Hand needs an object of at most 5 kg.")
    elif weave_id == "W03":
        _require(target.get("kind") == "person" and target.get("ordinary_target") is True, "Binding needs one ordinary person.")
        _require(attack or target.get("consenting") is True, "Practice Binding requires consent.")
    elif weave_id == "W04":
        _require(target_id == "world" and _integer(intent.get("area_metres", 10), 1, 10), "Ward area must be 1–10 metres across.")
    elif weave_id == "W05":
        _require(target_id == "pc" or target.get("kind") == "person", "Guard needs one person.")
    elif weave_id == "W06":
        _require(target_id != "pc", "Healing cannot heal its caster.")
        _require(target.get("kind") == "person" and target.get("alive") is True, "Healing needs a living patient.")
        _require(target.get("consenting") is True or target["vitality"] == 0, "Healing requires consent.")
        _require(not target["healing_used"], "This patient already received Healing since their full rest.")
        _require(target["vitality"] < target["max_vitality"], "The patient has no missing Vitality.")
    same = [e for e in p["held"]+p["tied"] if e["weave_id"] == weave_id and e["target_id"] == target_id]
    reinforce = bool(same) and weave_id == "W03" and attack
    _require(not same or reinforce, "This weave already affects the target.")
    load = weave["load"]
    committed = sum(e["load"] for e in p["held"]+p["tied"])
    _require(committed + (0 if reinforce else load) <= p["capacity"], "Insufficient free Load, including for an instant cast.")
    _require(not weave["held"] or reinforce or len(p["held"]) < p["control"], "No held-weave slot available.")
    _require(p["strain"]+load <= 2*p["capacity"], "Casting Strain exceeds the limit.")
    p["strain"] += load
    if attack:
        difficulty = target["guard"]
    else:
        difficulty = intent.get("difficulty")
        _require(difficulty is None or difficulty in (14, 18, 22), "Difficulty must be omitted, 14, 18 or 22.")
        _require(type(difficulty) is not bool, "Difficulty must be an integer.")
    check = None if difficulty is None else _check(p, "will", "channeling", difficulty + (2 if p["strain"] > p["capacity"] else 0))
    if check and not attack and intent.get("cost", "strain") == "strain":
        _require(p["strain"]+1 <= 2*p["capacity"], "Cannot afford the declared utility cost.")
    _advance(upfront, 10)
    branches = {}
    for band in ("clean", "costly", "setback"):
        state = deepcopy(upfront)
        success = check is None or band != "setback"
        if success:
            q, t = state["pc"], state[target_id]
            if weave["held"] and not reinforce:
                entry = {"id": action_id, "weave_id": weave_id, "load": load, "target_id": target_id,
                         "binding_contribution": 0, "expires_at": None, "area_metres": intent.get("area_metres", 0)}
                q["held"].append(entry)
            if weave_id == "W01":
                if attack:
                    t["resistance"] = max(0, t["resistance"]-1)
                    if t["resistance"] == 0:
                        binding = sum(e["binding_contribution"] for e in q["held"]
                                      if e["weave_id"] == "W03" and e["target_id"] == target_id)
                        if binding:
                            t["restrained"] = True
                        else:
                            t["defeated"] = True
                else:
                    t["lit"] = True
            elif weave_id == "W03":
                entry = next(e for e in q["held"] if e["weave_id"] == "W03" and e["target_id"] == target_id)
                if attack:
                    removed = min(2, t["resistance"])
                    t["resistance"] -= removed
                    entry["binding_contribution"] += removed
                    t["restrained"] = t["resistance"] == 0
                else:
                    t["restrained"] = True
            elif weave_id == "W06":
                t["vitality"] = min(t["max_vitality"], t["vitality"]+4)
                t["healing_used"] = True
        if check is not None and band != "clean":
            if attack:
                _harm(state, target["harm"], target.get("harm_source", "melee"), concentration)
            elif intent.get("cost", "strain") == "strain":
                state["pc"]["strain"] += 1
            else:
                state["pc"]["pending_work_seconds"] += 600
        branches[band] = state
    name = weave["name"]
    return check, branches, "Use " + name + ".", "Apply the published initial-six form to " + target_id + "."


def build_action(state, head_hash, campaign_id, action_id, intent: dict, acceptance_ref: str) -> dict:
    """Build a frozen offer without rolling, mutation, or hidden effects.

    Supported verbs: embrace; cast; release; tie; untie; move; rest; wait;
    workoff; firstaid; study; support; cancel_support; prepare; check;
    choose and advance_event for a new authored episode.
    See tests and ``preview_action`` for executable examples.
    """
    validate_state(state)
    intent = normalize(intent)
    _require(type(intent) is dict and type(intent.get("verb")) is str, "Intent needs a verb.")
    _require(state["pc"]["vitality"] > 0 or intent["verb"] in ("rest", "wait"), "The character is incapacitated.")
    upfront = deepcopy(state)
    p, w = upfront["pc"], upfront["world"]
    check = None
    branches = None
    authored_summaries = None
    verb = intent["verb"]
    goal, method = verb.capitalize() + ".", "Use the published rules."
    if verb in ("choose", "advance_event"):
        from .story import resolve
        check, branches, goal, method, authored_summaries = resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm)
    elif verb == "cast":
        check, branches, goal, method = _cast(upfront, intent, action_id)
    elif verb == "embrace":
        _closed(intent, ())
        _safe(upfront)
        _require(not p["embraced"], "The Source is already embraced.")
        p["embraced"] = True
        _advance(upfront, 10)
        goal = "Embrace the Source safely."
    elif verb == "release":
        _closed(intent, (), ("held_id",))
        held_id = intent.get("held_id")
        _require(held_id is None or any(e["id"] == held_id for e in p["held"]), "Unknown held weave.")
        _drop(upfront, held_id)
        if held_id is None:
            p["embraced"] = False
        goal = "Release the stated held effects."
    elif verb in ("tie", "untie"):
        _closed(intent, ("held_id",) if verb == "tie" else ("tied_id",))
        _safe(upfront)
        key, collection = ("held_id", p["held"]) if verb == "tie" else ("tied_id", p["tied"])
        entry = next((e for e in collection if e["id"] == intent[key]), None)
        _require(entry is not None, "Unknown weave instance.")
        if verb == "tie":
            _require(p["control"] >= 3 and entry["weave_id"] in ("W04", "W05"), "This weave cannot be tied.")
            _require(len(p["tied"]) < p["control"] and p["strain"]+1 <= 2*p["capacity"], "Cannot afford tying.")
            p["strain"] += 1
            p["held"].remove(entry)
            entry["expires_at"] = w["time_seconds"]+10+3600
            p["tied"].append(entry)
        else:
            if entry["target_id"] != "world":
                _target(upfront, entry["target_id"], WEAVES[entry["weave_id"]]["range"])
            p["tied"].remove(entry)
            _release_entry(upfront, entry)
        _advance(upfront, 10)
    elif verb == "move":
        _closed(intent, ("held_id", "operation"), ("distance_metres",))
        _safe(upfront)
        entry = next((e for e in p["held"] if e["id"] == intent["held_id"] and e["weave_id"] == "W02"), None)
        _require(entry is not None, "Move requires a held Air Hand.")
        target = _target(upfront, entry["target_id"], 10)
        if intent["operation"] == "retrieve":
            distance = intent.get("distance_metres", 2)
            _require(_integer(distance, 1, 2), "Air Hand moves at most two metres per action.")
            target["distance_m"] = max(0, target["distance_m"]-distance)
        elif intent["operation"] in ("open", "close"):
            _require(target.get("simple_latch") is True, "Only an accessible simple latch is supported.")
            target["open"] = intent["operation"] == "open"
        else:
            raise RuleError("Unsupported Air Hand movement.", "UNSUPPORTED_MODE")
        _advance(upfront, 10)
    elif verb == "rest":
        _closed(intent, ("kind",), ("companions",))
        _safe(upfront)
        _require(not p["held"], "Release held weaves before rest.")
        _require(p["pending_work_seconds"] == 0 or p["vitality"] == 0,
                 "Finish declared follow-up work before restorative rest.")
        if intent["kind"] == "break":
            _require(not intent.get("companions"), "Companion rest requires a full rest.")
            end = w["time_seconds"]+600
            _require(p["last_break_end"] is None or end-p["last_break_end"] >= 3600, "The restorative-break cooldown has not elapsed.")
            _advance(upfront, 600)
            p["vitality"] = min(p["max_vitality"], p["vitality"]+2)
            p["strain"] = max(0, p["strain"]-2)
            p["last_break_end"] = end
        elif intent["kind"] == "full":
            companions = intent.get("companions", [])
            _require(type(companions) is list and len(set(companions)) == len(companions), "Invalid companions.")
            for ally_id in companions:
                ally = _target(upfront, ally_id, 0)
                _require(ally_id.startswith("npc-") and ally.get("willing") is True, "Companion cannot join the rest.")
            _advance(upfront, 28800)
            p["vitality"], p["strain"], p["embraced"] = p["max_vitality"], 0, False
            p["firstaid_used"] = p["healing_used"] = False
            for ally_id in companions:
                ally = upfront[ally_id]
                ally["vitality"] = ally["max_vitality"]
                ally["firstaid_used"] = ally["healing_used"] = False
                ally["support_remaining"] = 2
        else:
            raise RuleError("Rest kind must be break or full.")
    elif verb in ("wait", "workoff"):
        _closed(intent, ("seconds",))
        _safe(upfront)
        seconds = intent["seconds"]
        _require(_integer(seconds, 1, 28800), "Duration must be 1–28800 seconds.")
        if verb == "workoff":
            _require(seconds <= p["pending_work_seconds"], "Work exceeds the remaining obligation.")
            p["pending_work_seconds"] -= seconds
        _advance(upfront, seconds)
    elif verb == "firstaid":
        _closed(intent, ("target_id",))
        _safe(upfront)
        target = _target(upfront, intent["target_id"], 0)
        _require(intent["target_id"] == "pc" or target.get("kind") == "person", "First aid needs a person.")
        _require(not target["firstaid_used"], "First aid already used since the patient's full rest.")
        _require(target["vitality"] < target["max_vitality"], "The patient has no missing Vitality.")
        _require(target.get("alive", True), "First aid cannot revive the dead.")
        target["vitality"] = min(target["max_vitality"], target["vitality"]+2)
        target["firstaid_used"] = True
        _advance(upfront, 600)
        goal = "Provide safe routine first aid."
    elif verb == "study":
        _closed(intent, ("course_id",), ("seconds", "source"))
        _safe(upfront)
        _require(not p["held"] and not p["embraced"], "Release the Source before a study block.")
        _require(p["pending_work_seconds"] == 0, "Follow-up work cannot count as study.")
        source = intent.get("source", "curriculum-library")
        _require(source in ("curriculum-library", "npc-mentor"), "Unknown teaching source.")
        _require(w["library_available"] if source == "curriculum-library" else upfront[source]["willing"], "Teaching source unavailable; use the alternative.")
        course, seconds = intent["course_id"], intent.get("seconds", 28800)
        _require(_integer(seconds, 1, 28800), "Study duration must be 1–28800 seconds.")
        foundation = course in [f"N{i:02d}" for i in range(1, 11)]
        _require(foundation or course in WEAVES, "This course is not active.", "UNSUPPORTED_COURSE")
        required = (4 if foundation else 5)*28800
        progress = p["study_progress"].get(course, 0)
        _require(progress+seconds <= required, "Study would exceed the course's remaining time.")
        if not foundation:
            _weave_prerequisites(p, course, require_known=False)
            _require(course not in p["known_weaves"], "This weave is already known.")
            if progress == 0:
                _require(p["learning_opportunities"] > 0, "No chapter learning opportunity is available.")
                p["learning_opportunities"] -= 1
        day = str(w["time_seconds"] // 86400)
        _require(w["time_seconds"] % 86400 + seconds <= 86400, "Split study at the calendar-day boundary.")
        prior = w["main_activity"].get(day, {"kind": "study", "seconds": 0})
        _require(prior["kind"] == "study" and prior["seconds"]+seconds <= 28800, "The day's main activity is already allocated.")
        w["main_activity"][day] = {"kind": "study", "seconds": prior["seconds"]+seconds}
        p["study_progress"][course] = progress+seconds
        if not foundation and progress+seconds == required:
            p["known_weaves"].append(course)
        _advance(upfront, seconds)
        goal = "Study " + course + " with retained, exact progress."
    elif verb == "support":
        _closed(intent, ("ally_id", "skill_id"))
        _require(p["support_pending"] is None, "An ally's support is already pending.")
        ally = _target(upfront, intent["ally_id"], 10)
        _require(ally.get("willing") is True and ally.get("support_remaining", 0) > 0, "This ally cannot provide support.")
        _require(intent["skill_id"] in ally["competences"], "Support must fit an ally's competence.")
        ally["support_remaining"] -= 1
        p["support_pending"] = {"ally_id": intent["ally_id"], "skill_id": intent["skill_id"]}
        goal = "Reserve one credible ally bonus for the next matching check."
    elif verb == "cancel_support":
        _closed(intent, ())
        _require(p["support_pending"] is not None, "No support is pending.")
        p["support_pending"] = None
        goal = "Release the reserved support without refunding its spent use."
    elif verb in ("prepare", "check"):
        _closed(intent, ("task_id",))
        _safe(upfront)
        task_id = intent["task_id"]
        tasks = {"inspect_latch": ("wits", "notice", 14),
                 "focus_exercise": ("will", "composure", 14),
                 "compare_notes": ("wits", "scholarship", 18)}
        _require(task_id in tasks, "Unknown published check.", "UNSUPPORTED_CHECK")
        _require(task_id not in w["completed_checks"], "That task is already complete.")
        if verb == "prepare":
            _require(task_id not in p["prepared_checks"], "Preparation cannot stack.")
            p["prepared_checks"].append(task_id)
            _advance(upfront, 600)
        else:
            attribute, skill, difficulty = tasks[task_id]
            prepared = task_id in p["prepared_checks"]
            pending = p["support_pending"]
            support_id = pending["ally_id"] if pending and pending["skill_id"] == skill else "none"
            attempt_key = task_id + ":" + ("prepared" if prepared else "direct") + ":" + support_id
            _require(attempt_key not in p["attempted_checks"], "The unchanged method has already been tested.")
            p["attempted_checks"].append(attempt_key)
            check = _check(p, attribute, skill, difficulty)
            if prepared:
                check["modifier"] = 2
                p["prepared_checks"].remove(task_id)
            _advance(upfront, 10)
            branches = {}
            for band in ("clean", "costly", "setback"):
                result = deepcopy(upfront)
                if band != "setback":
                    result["world"]["completed_checks"].append(task_id)
                    if task_id == "inspect_latch":
                        result["obj-latch"]["inspected"] = True
                if band != "clean":
                    result["pc"]["pending_work_seconds"] += 600
                branches[band] = result
            goal = "Complete " + task_id.replace("_", " ") + "."
            method = "Use the published check; extra follow-up work is 600 seconds on a costly result or setback."
    else:
        raise RuleError("Unsupported intent verb: " + verb, "UNSUPPORTED_INTENT")
    if branches is None:
        branches = {band: deepcopy(upfront) for band in ("clean", "costly", "setback")}
    from .story import refresh
    refresh(upfront)
    for result in branches.values():
        refresh(result)
    summaries = {
        "clean": "Achieve the declared effect with only the upfront costs.",
        "costly": "Achieve the declared effect and apply exactly the listed additional costs.",
        "setback": "Do not achieve the declared effect; apply exactly the listed additional costs.",
    }
    if check is None:
        summaries = dict.fromkeys(summaries, "Complete the routine action with exactly the listed effects and costs.")
    if authored_summaries is not None:
        summaries = authored_summaries
    for result in (upfront, *branches.values()):
        validate_state(result)
    upfront_changes = _changes(state, upfront)
    private_fields = set(PRIVATE_NPC_FIELDS)
    private_changes = [c for c in upfront_changes if (c["record_id"], c["field_id"]) in private_fields]
    public_changes = [c for c in upfront_changes if (c["record_id"], c["field_id"]) not in private_fields]
    stakes = {"goal": goal, "method": method, "check": check,
              "time_seconds": upfront["world"]["time_seconds"]-state["world"]["time_seconds"],
              "upfront_changes": public_changes,
              "bands": {band: {"summary": summaries[band], "changes": _changes(upfront, result), "permanent_loss": False}
                        for band, result in branches.items()},
              "rolls": [] if check is None else [{"key": f"check/die-{i}", "sides": 10} for i in range(2)],
              "irreversible_risk": None}
    action = {"schema": "action-v1", "campaign_id": campaign_id, "action_id": action_id,
              "actor_id": "pc", "expected_head_hash": head_hash,
              "rules_version": RULES_VERSION, "content_version": CONTENT_VERSION, "engine_version": ENGINE_VERSION,
              "intent_text": canonical(intent).decode("utf-8"), "stakes": stakes, "stakes_hash": digest(stakes),
              "auxiliary_changes": private_changes, "npc_proposal_hashes": [], "acceptance_ref": acceptance_ref}
    action_valid(action)
    return action


def validate_action(action, state, head_hash):
    """Reject rehashed caller-authored effects by rebuilding the complete offer."""
    action_valid(action)
    intent = parse_json(action["intent_text"])
    rebuilt = build_action(state, head_hash, action["campaign_id"], action["action_id"], intent, action["acceptance_ref"])
    _require(canonical(action) == canonical(rebuilt), "Action differs from the deterministic rules offer.", "FORGED_ACTION")
    return True


def preview_action(action):
    """Return the public offer. No dice are generated here."""
    action_valid(action)
    stakes = action["stakes"]
    check = stakes["check"]
    lines = [stakes["goal"], stakes["method"], f"Time: {stakes['time_seconds']} seconds."]
    if check:
        lines.append(f"Check: 2d10 + {check['attribute_rating']} + {check['skill_rating']} + {check['modifier']}; difficulty {check['difficulty']}.")
    else:
        lines.append("Routine action; no roll.")
    for label, changes in [("Upfront", stakes["upfront_changes"])] + [(b, stakes["bands"][b]["changes"]) for b in ("clean", "costly", "setback")]:
        lines.append(label + ": " + ("; ".join(f"{c['record_id']}.{c['field_id']}: {c['before']} → {c['after']}" for c in changes) or "No additional change."))
    return "\n".join(lines)
