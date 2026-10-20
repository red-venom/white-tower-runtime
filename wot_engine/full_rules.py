"""Versioned full campaign rules. The initial-six engine remains immutable.

Every accepted action is rebuilt from trusted state and these installed rules.
Expansion is experimental until the complete G4 validation gate passes.
"""
from __future__ import annotations

from copy import deepcopy

from .contracts import (
    ContractError, action_valid, canonical, compose_changes, die, digest, normalize, parse_json, MAX_ENVELOPE_BYTES,
)

RULES_VERSION = "rules-v2"
CONTENT_VERSION = "fullcontent-v1"
ENGINE_VERSION = "engine-v1"
ATTRIBUTES = ("body", "grace", "wits", "will", "presence")
SKILLS = ("athletics", "melee", "marksmanship", "stealth", "survival", "notice",
          "scholarship", "medicine", "persuasion", "insight", "leadership", "composure")
FLOWS = ("air", "earth", "fire", "water", "spirit")
from .catalogue import WEAVES
from . import magic, progression, regional, combat, life

PUBLIC_PC_FIELDS = (
    "name", "rank", "level", "attributes", "skills", "vitality", "max_vitality",
    "wounds", "supply", "silver", "control", "flows", "capacity", "known_weaves",
    "held", "tied", "strain", "embraced", "study_progress", "learning_opportunities",
    "pending_work_seconds", "support_pending", "firstaid_used", "healing_used",
    "warning_ready", "general_points", "channel_points", "magic_status", "equipment", "identity",
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
PRIVATE_NPC_FIELDS = tuple(sorted(set(regional.PRIVATE_NPC_FIELDS) | {("npc-mentor", "private_oath_ruling")}))


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


def initial_state(name="Test novice", *, seed: bytes, campaign_id: str, episode=True, character=None):
    from .rules import initial_state as initial_six
    state = initial_six(name, seed=seed, campaign_id=campaign_id, episode=episode)
    regional.initialize(state)
    combat.initialize(state)
    magic.initialize(state)
    progression.initialize(state)
    life.initialize(state)
    state["pc"]["identity"] = None
    if character is not None:
        from .creation import configure
        state = configure(state, character)
    refresh_choices(state)
    validate_state(state)
    return normalize(state)


def validate_state(state):
    """Validate the resource boundaries used by this rules module."""
    normalize(state)
    _require(type(state) is dict and "pc" in state and "world" in state, "Missing state records.")
    p, w = state["pc"], state["world"]
    for field, low, high in (("potential", 8, 10), ("capacity", 3, 10), ("control", 1, 4),
                             ("vitality", 0, 12), ("max_vitality", 6, 12), ("wounds", 0, 3),
                             ("supply", 0, 6), ("silver", 0, 2**53-1), ("strain", 0, 20),
                             ("pending_work_seconds", 0, 2**53-1), ("learning_opportunities", 0, 2**53-1)):
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
    magic.validate(state)
    combat.validate(state)
    regional.validate_region(state)
    progression.validate(state)
    life.validate(state)
    _require(_integer(w["time_seconds"]), "Invalid world clock.")
    for record in state.values():
        if record.get("kind") == "person":
            _require(_integer(record.get("vitality"), 0, record.get("max_vitality", 0)), "Invalid patient Vitality.")
            _require(_integer(record.get("wounds"), 0, 3), "Invalid patient Wounds.")
            if "support_remaining" in record:
                _require(_integer(record["support_remaining"], 0, 2), "Invalid support uses.")
            if "resistance" in record:
                _require(_integer(record["resistance"], 0, record["max_resistance"]), "Invalid Resistance.")
    _require(len(canonical(public_state(state))) <= MAX_ENVELOPE_BYTES-1024,
             "The public save exceeds its supported size; this action needs a bounded content revision.")


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
    magic.release_entry(state, entry)


def _drop(state, weave_id=None):
    magic.drop(state, weave_id)


def _safe(state):
    _require(state["world"]["safe"] and not state["world"]["active_conflict"],
             "Establish a safe interval first.")


def _advance(state, seconds, *, allow_boundary=False):
    _require(_integer(seconds, 0, 28800), "Action duration outside supported interval.")
    start = state["world"]["time_seconds"]
    deadline = state["world"].get("next_event_second")
    _require(deadline is None or start + seconds < deadline or
             (allow_boundary and start + seconds == deadline),
             "A world event requires a decision before this action can finish.", "WORLD_EVENT_DUE")
    regional.account_time(state, start, start + seconds)
    state["world"]["time_seconds"] = start + seconds
    # An exchange settles effect, harm and concentration before expiry. The
    # clock is recorded once; after-result protection cannot advance it again.
    if state["world"]["active_conflict"] and seconds == 10:
        _require(state["conflict"]["deferred_clock"] is None, "Finish the prior exchange first.")
        state["conflict"]["deferred_clock"] = {"start":start,"end":start+seconds}
    else:
        magic.advance_effects(state, start, start + seconds)


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
    from .catalogue import prerequisites
    return prerequisites(pc, weave_id, require_known=require_known)


def _check(pc, attribute, skill, difficulty, support=True):
    modifier = 0
    pending = pc["support_pending"]
    if pending is not None and support and pending["skill_id"] == skill:
        modifier = 2
        pc["support_pending"] = None
        if pending["ally_id"].startswith("npc-"):
            pc["exchange_support_used"] = True
    return {"difficulty": difficulty, "attribute": attribute,
            "attribute_rating": pc["attributes"][attribute], "skill_id": skill,
            "skill_rating": pc["control"] if skill == "channeling" else pc["skills"][skill],
            "modifier": modifier}


def _harm(state, amount, source, concentration):
    combat.apply_harm(state, amount, source, concentration, settle=magic.harm)


def recovery_choices(state):
    p,w=state['pc'],state['world']
    if not w['safe'] or w['active_conflict']:
        return []
    now,deadline=w['time_seconds'],w.get('next_event_second')
    fits=lambda seconds: deadline is None or now+seconds < deadline
    choices=[]
    if not p['held'] and p['magic'].get('circle') is None and (not p['pending_work_seconds'] or p['vitality']==0):
        if fits(600) and (p['last_break_end'] is None or now+600-p['last_break_end']>=3600):
            choices.append({'label':'Take a restorative ten-minute break','intent':{'verb':'rest','kind':'break'}})
        if fits(28800):
            choices.append({'label':'Take a full eight-hour rest','intent':{'verb':'rest','kind':'full'}})
    if not w.get('episode') or w['episode']['phase']=='complete':
        if deadline is not None:
            choices.append({'label':'Wait towards the next scheduled project event','intent':{'verb':'region_event'}})
    seconds=min(28800,86400-now%86400,deadline-now-1 if deadline is not None else 28800)
    if seconds>0:
        choices.append({'label':'Wait safely for '+str(seconds)+' seconds','intent':{'verb':'wait','seconds':seconds}})
        if p['vitality']>0 and p['pending_work_seconds']:
            choices.append({'label':'Complete declared follow-up work','intent':{'verb':'workoff','seconds':min(seconds,p['pending_work_seconds'])}})
    return choices


def refresh_choices(state):
    from .story import refresh
    magic.refresh(state)
    regional.refresh(state)
    if state["conflict"]["pending_harm"] is not None:
        state["world"]["choices"] = [
            {"label": "Accept the declared harm", "intent": {"verb": "resolve_harm"}},
            *({"label": "Ask " + state[key]["name"] + " to protect you",
               "intent": {"verb": "resolve_harm", "ally_id": key}}
              for key in combat.eligible_support(state))]
        return
    if state['pc']['vitality']==0:
        state['world']['choices']=recovery_choices(state)
        return
    if state["world"]["active_conflict"] and state["conflict"]["target_id"] is not None:
        if state["conflict"]["limit_due"]:
            options = [("Withdraw with a ten-minute delay", "withdraw"),
                       ("Change position and approach", "flank"),
                       ("Change to negotiation", "negotiate")]
            state["world"]["choices"] = [
                {"label": label, "intent": {"verb": "combat", "kind": "reframe", "method": method}}
                for label, method in options if method not in state["conflict"]["methods"]]
        else:
            state["world"]["choices"] = [
                {"label": label, "intent": {"verb": "combat", "kind": kind}}
                for label, kind in (("Use your staff", "attack"), ("Defend", "defend"),
                                    ("Escape", "escape"), ("Negotiate disengagement", "progress"))]
            target=state[state['conflict']['target_id']]
            if target.get('threat') and state['pc']['oaths_active']:
                state['world']['choices'].extend(
                    {'label':label,'intent':{'verb':'oath_defence','target_id':state['conflict']['target_id'],'believes_extreme_peril':belief}}
                    for label,belief in (('Declare that you believe your life is in extreme peril',True),('Declare that you do not believe your life is in extreme peril',False)))
        return
    if state["world"].get("episode") and state["world"]["episode"]["phase"] != "complete":
        # Keep v1's authored opening immutable while adapting its daily view.
        ledger = state["world"]["main_activity"]
        state["world"]["main_activity"] = {
            str(ledger["day"]): {"kind": "study", "seconds": ledger["used_seconds"]}}
        try:
            refresh(state)
        finally:
            state["world"]["main_activity"] = ledger
    else:
        from .scenes import assessment, regional_scene
        scene = assessment(state)
        if scene:
            state["world"].update(scene_id=scene["id"], scene_description=scene["description"], choices=scene["choices"])
            return
        scene = regional_scene(state)
        state["world"].update(scene_id=scene["id"], scene_description=scene["description"])
        choices = []
        for module in (regional, progression, life):
            if hasattr(module, "available_choices"):
                choices.extend(module.available_choices(state))
        for choice in recovery_choices(state):
            if not any(item['intent']==choice['intent'] for item in choices):
                choices.append(choice)
        state["world"]["choices"] = choices


def public_state(state):
    region = regional.public_view(state)
    player = {k: deepcopy(v) for k, v in state["pc"].items() if k in PUBLIC_PC_FIELDS}
    world = {k: deepcopy(v) for k, v in state["world"].items() if k in PUBLIC_WORLD_FIELDS}
    world["region"] = region["region"]
    world["training"] = progression.public_view(state)
    world["conflict"] = combat.public_view(state)
    world["recovery"] = life.public_view(state)
    return {"pc": player, "world": world, "npcs": region["npcs"]}


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
    _require(state["pc"]["vitality"] > 0 or intent["verb"] in ("rest", "wait", "region_event"), "The character is incapacitated.")
    upfront = deepcopy(state)
    p, w = upfront["pc"], upfront["world"]
    check = None
    branches = None
    authored_summaries = None
    verb = intent["verb"]
    goal, method = verb.capitalize() + ".", "Use the published rules."
    combat.before_action(upfront, intent)
    progression.before_action(upfront, intent)
    magic.before_action(upfront, intent)
    if combat.handles(intent):
        check, branches, goal, method, authored_summaries = combat.resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm,
            settle_harm=magic.harm)
    elif magic.handles(intent):
        check, branches, goal, method, authored_summaries = magic.resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm)
    elif progression.handles(intent):
        check, branches, goal, method, authored_summaries = progression.resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm)
    elif life.handles(intent):
        check, branches, goal, method, authored_summaries = life.resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm)
    elif regional.handles(intent):
        check, branches, goal, method, authored_summaries = regional.resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm,
            context={"campaign_id": campaign_id, "head_hash": head_hash})
    elif verb == "choose" and intent.get("choice_id") == "training.review":
        _closed(intent, ("choice_id",))
        e = w["episode"]
        _require(e["phase"] == "training" and e["training_course"] is None and
                 e["training_seconds"] < 3600, "No foundation review is pending.")
        _safe(upfront)
        result = regional.advance_activity(upfront, 3600-e["training_seconds"], "study", advance_clock=_advance)
        e["training_seconds"] += result["credited_seconds"]
        goal = "Review already mastered foundation work without new mastery credit."
    elif verb in ("choose", "advance_event"):
        from .story import resolve
        check, branches, goal, method, authored_summaries = resolve(
            upfront, intent, action_id, advance=_advance, check=_check, harm=_harm)
    elif verb == "embrace":
        _closed(intent, ())
        _safe(upfront)
        _require(not p["embraced"], "The Source is already embraced.")
        p["embraced"] = True
        _advance(upfront, 10)
        goal = "Embrace the Source safely."
    elif verb == "rest":
        _closed(intent, ("kind",), ("companions",))
        _safe(upfront)
        _require(not p["held"], "Release held weaves before rest.")
        _require(p["magic"].get("circle") is None, "End the circle before resting.")
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
            rest_start = w["time_seconds"]
            companions = intent.get("companions", [])
            _require(type(companions) is list and len(set(companions)) == len(companions), "Invalid companions.")
            for ally_id in companions:
                ally = _target(upfront, ally_id, 0)
                _require(ally_id.startswith("npc-") and ally.get("willing") is True, "Companion cannot join the rest.")
            _advance(upfront, 28800)
            fed = regional.supplied_today(upfront)
            p["vitality"] = p["max_vitality"] if fed else max(p["vitality"], p["max_vitality"]//2)
            p["strain"] = 0 if fed else max(0, p["strain"]-2)
            p["embraced"] = False
            p["firstaid_used"] = p["healing_used"] = False
            for ally_id in companions:
                ally = upfront[ally_id]
                ally["vitality"] = ally["max_vitality"] if fed else max(ally["vitality"], ally["max_vitality"]//2)
                if "strain" in ally:
                    ally["strain"] = 0 if fed else max(0, ally["strain"]-2)
                    ally["embraced"] = False
                ally["firstaid_used"] = ally["healing_used"] = False
                regional.complete_ally_rest(upfront, ally_id, rest_start, w["time_seconds"])
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
    elif verb == "support":
        _closed(intent, ("ally_id", "skill_id"))
        _require(p["support_pending"] is None, "An ally's support is already pending.")
        ally = _target(upfront, intent["ally_id"], 10)
        _require(intent["ally_id"] not in magic._circle_members(upfront),
                 "A linked circle member cannot also supply ally support.")
        _require(ally.get("willing") is True and ally.get("support_remaining", 0) > 0, "This ally cannot provide support.")
        skill_id = intent["skill_id"]
        _require(skill_id in ally["competences"], "Support must fit an ally's competence.")
        ally["support_remaining"] -= 1
        p["support_pending"] = {"ally_id": intent["ally_id"], "skill_id": skill_id}
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
    refresh_choices(upfront)
    for result in branches.values():
        interval = result["conflict"]["deferred_clock"]
        if interval is not None and result["conflict"]["pending_harm"] is None:
            magic.advance_effects(result, interval["start"], interval["end"])
            result["conflict"]["deferred_clock"] = None
        combat.finish_exchange(result)
        regional.record_opening_proofs(result, action_id)
        refresh_choices(result)
    summaries = {
        "clean": "Achieve the declared effect with only the upfront costs.",
        "costly": "Achieve the declared effect and apply exactly the listed additional costs.",
        "setback": "Do not achieve the declared effect; apply exactly the listed additional costs.",
    }
    if check is None:
        summaries = dict.fromkeys(summaries, "Complete the routine action with exactly the listed effects and costs.")
    if authored_summaries is not None:
        summaries = authored_summaries
    # A routine result has no outcome-dependent effects. Store its identical
    # changes once instead of repeating a large choice menu in all three bands.
    if check is None and all(canonical(result)==canonical(branches['clean']) for result in branches.values()):
        upfront=deepcopy(branches['clean'])
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
              "auxiliary_changes": private_changes, "npc_proposal_hashes": regional.proposal_hashes(upfront, action_id), "acceptance_ref": acceptance_ref}
    action_valid(action)
    _check_envelope_sizes(action)
    return action


def _check_envelope_sizes(action):
    """Reject an unpublishable offer before it can become an accepted action.

    Hashes have fixed widths. Maximum supported counter/sequence widths make
    this conservative without generating a die or inventing an outcome.
    """
    maximum = 2**53-1
    for band, result in action['stakes']['bands'].items():
        event = {"schema":"event-v1","campaign_id":action['campaign_id'],"action_id":action['action_id'],
                 "sequence":maximum,"origin_epoch":maximum,"parent_hash":action['expected_head_hash'],
                 "rules_version":RULES_VERSION,"content_version":CONTENT_VERSION,"engine_version":ENGINE_VERSION,
                 "accepted_action_hash":"0"*64,"stakes_hash":action['stakes_hash'],
                 "before_state_hash":"0"*64,"after_state_hash":"0"*64,
                 "dice":[{**roll,"value":roll['sides'],"rejection_counter":maximum} for roll in action['stakes']['rolls']],
                 "outcome":band if action['stakes']['check'] is not None else 'routine',
                 "changes":compose_changes(action['stakes']['upfront_changes'],result['changes'],action['auxiliary_changes']),
                 "npc_proposal_hashes":action['npc_proposal_hashes'],"public_narration":result['summary'],
                 "revealed_fact_ids":[],"event_hash":"0"*64}
        envelope={"schema":"remote-envelope-v1","accepted_action":action,"event":event,"envelope_hash":"0"*64}
        _require(len(canonical(envelope))<=MAX_ENVELOPE_BYTES,
                 "This offer exceeds the saved-event limit; split the activity before accepting it.")


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
