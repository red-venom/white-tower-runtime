"""Published small conflicts, with one roll and one support use per exchange."""
from copy import deepcopy
from .rules import RuleError

FOES = {
    "foe-obstacle": ("A weak obstruction", 14, 4, 1),
    "foe-ordinary": ("A small group of road thieves", 14, 6, 2),
    "foe-dangerous": ("An experienced raider", 18, 8, 3),
}


def need(test, message):
    if not test:
        raise RuleError(message)


def initialize(state):
    state["pc"]["exchange_support_used"] = False
    state["pc"]["equipment"] = {"ordinary": "staff", "improvised": "stout stick", "heavy": None, "ranged": None,
                               "kit": ["basic clothes", "knife", "cloak", "notebook", "water container"]}
    state["conflict"] = {"target_id": None, "exchanges": 0, "limit_due": False,
                         "progress": 0, "outcome": None, "support_used": False,
                         "pending_harm": None, "methods": [], "physical_damage": 0,
                         "deferred_clock": None}
    for key, (name, guard, resistance, harm) in FOES.items():
        state[key] = {"kind": "person", "name": name, "guard": guard,
            "resistance": resistance, "max_resistance": resistance, "harm": harm,
            "harm_source": "melee", "available": False, "visible": False,
            "location": "unspecified", "distance_m": 0, "ordinary_target": True,
            "consenting": False, "alive": True, "defeated": False, "restrained": False, "hostile": False,
            "threat": None,
            "vitality": 8, "max_vitality": 8, "wounds": 0,
            "healing_used": False, "firstaid_used": False}


def activate(state, target_id, location):
    need(target_id in FOES and not state["world"]["active_conflict"], "Encounter cannot be activated.")
    target = state[target_id]
    need(not target["defeated"] and target["alive"], "This encounter is already resolved.")
    target.update(available=True, visible=True, location=location, distance_m=5)


def validate(state):
    c = state["conflict"]
    need(type(c["exchanges"]) is int and 0 <= c["exchanges"] <= 6, "Invalid exchange count.")
    need(type(c["progress"]) is int and 0 <= c["progress"] <= 4, "Invalid conflict progress.")
    need(type(c["support_used"]) is bool and type(c["limit_due"]) is bool, "Invalid conflict flags.")
    pending = c["pending_harm"]
    need(pending is None or (type(pending) is dict and set(pending) == {"amount", "source", "concentration"}
         and type(pending["amount"]) is int and pending["amount"] > 0), "Invalid pending harm.")
    interval = c["deferred_clock"]
    need(interval is None or (type(interval) is dict and set(interval)=={"start","end"}
         and type(interval["start"]) is int and type(interval["end"]) is int
         and 0 <= interval["start"] < interval["end"] == state["world"]["time_seconds"]
         and interval["end"]-interval["start"] == 10), "Invalid deferred exchange clock.")
    if state["world"]["active_conflict"]:
        opening_hazard = state["world"].get("episode", {}).get("phase") == "hazard"
        need(c["target_id"] in state or opening_hazard, "Missing declared opponent.")


def handles(intent):
    return intent.get("verb") in ("combat", "resolve_harm")


def eligible_support(state):
    circle = state["pc"].get("magic", {}).get("circle")
    linked = circle["members"] if circle else ()
    return [key for key, ally in state.items() if key.startswith("npc-")
            and key not in linked
            and ally.get("willing") is True and ally.get("visible") is True
            and ally.get("location") == state["world"]["location"]
            and ally.get("distance_m", 100) <= 10 and ally.get("support_remaining", 0) > 0
            and set(ally.get("competences", ())) & {"medicine", "melee", "athletics", "protection"}]


def apply_harm(state, amount, source, concentration, *, settle):
    c = state["conflict"]
    c["support_used"] = c["support_used"] or state["pc"]["exchange_support_used"]
    if amount > 0 and not c["support_used"] and eligible_support(state):
        need(c["pending_harm"] is None, "Resolve the existing harm choice first.")
        c["pending_harm"] = {"amount": amount, "source": source, "concentration": concentration}
        return
    settle(state, amount, source, concentration)


def before_action(state, intent):
    c, w = state["conflict"], state["world"]
    if c["pending_harm"] is not None:
        need(intent.get("verb") == "resolve_harm", "Choose ally protection or accept the declared harm first.")
    if intent.get("verb") != "resolve_harm":
        state["pc"]["exchange_support_used"] = False
        c["support_used"] = False
    if not w["active_conflict"] or c["target_id"] is None or intent.get("verb") == "resolve_harm":
        return
    if c["limit_due"]:
        need(intent.get("verb") == "combat" and intent.get("kind") == "reframe",
             "Six exchanges have passed. Choose withdrawal, negotiation or a different approach.")
    elif intent.get("verb") not in ("combat", "cast", "embrace", "release", "support",
                                    "cancel_support", "magic_use", "shield_struggle", "circle_end", "oath_defence"):
        raise RuleError("Resolve the conflict or withdraw before that activity.")
    timed_magic_use = intent.get("verb") == "magic_use" and intent.get("operation") != "bonus"
    if intent.get("verb") in ("cast", "embrace", "shield_struggle") or timed_magic_use or (
        intent.get("verb") == "combat" and intent.get("kind") in ("attack", "defend", "escape", "progress")):
        need(c["exchanges"] < 6, "A new approach must be declared first.")
        c["exchanges"] += 1
        c["support_used"] = False
        c["limit_due"] = c["exchanges"] == 6


def finish_exchange(state):
    c, w = state["conflict"], state["world"]
    if c["pending_harm"] is not None or c["deferred_clock"] is not None or c["target_id"] is None:
        return
    if state["pc"]["vitality"] == 0 and c["outcome"] != "rescue and delay":
        c["outcome"] = "rescue and delay"
        state["pc"]["pending_work_seconds"] += 600
        w.update(active_conflict=False, safe=True, defeat_pending=True)
    target = state[c["target_id"]]
    if w["active_conflict"] and (target.get("defeated") or target.get("restrained")):
        c["outcome"] = "restrained" if target.get("restrained") else "opposition ended"
        w.update(active_conflict=False, safe=True)
    if not w["active_conflict"] and "magic" in w:
        w["magic"]["opponent_id"] = None


def public_view(state):
    c = deepcopy(state["conflict"])
    if c["target_id"]:
        t = state[c["target_id"]]
        c["opponent"] = {k: t[k] for k in ("name", "guard", "resistance", "max_resistance", "harm")}
        c["opponent"]["threat"] = deepcopy(t.get("threat"))
    c["eligible_protectors"] = eligible_support(state) if c["pending_harm"] else []
    return c


def resolve(state, intent, action_id, *, advance, check, harm, settle_harm):
    c, p, w = state["conflict"], state["pc"], state["world"]
    if intent["verb"] == "resolve_harm":
        need(set(intent) <= {"verb", "ally_id"} and c["pending_harm"] is not None, "No harm choice is pending.")
        pending = c["pending_harm"]
        ally = intent.get("ally_id")
        reduction = 0
        if ally is not None:
            need(not c["support_used"] and ally in eligible_support(state), "That ally cannot provide protection.")
            state[ally]["support_remaining"] -= 1
            c["support_used"], reduction = True, 2
        c["pending_harm"] = None
        settle_harm(state, max(0, pending["amount"]-reduction), pending["source"], pending["concentration"])
        finish_exchange(state)
        text = "Your ally reduces the declared harm by two." if ally else "The declared harm and concentration consequences are applied."
        return None, None, "Resolve the saved harm choice.", "No new roll or fictional time.", dict.fromkeys(("clean", "costly", "setback"), text)
    need(set(intent) <= {"verb", "kind", "target_id", "weapon", "lethal", "concentration", "method"}, "Unknown combat option.")
    kind = intent.get("kind")
    if kind == "start":
        target_id = intent.get("target_id")
        need(not w["active_conflict"] and target_id in FOES, "Select an available encounter.")
        t = state[target_id]
        need(t["available"] and t["visible"] and t["location"] == w["location"] and not t["defeated"], "That encounter is not available here.")
        need(p["wounds"] < 3, "Rest and care are required before another field operation.")
        c.update(target_id=target_id, exchanges=0, limit_due=False, progress=0, outcome=None,
                 support_used=False, pending_harm=None, methods=[], physical_damage=0, deferred_clock=None)
        t["hostile"] = True
        if target_id == "foe-dangerous":
            t["threat"] = {"source_action":action_id,"observer_id":"pc","immediate_lethal_threat":True,
                           "description":"The raider openly threatens your life and advances to attack."}
        w.update(active_conflict=True, safe=False)
        if "magic" in w:
            w["magic"]["opponent_id"] = target_id
        text = f"{t['name']}: Guard {t['guard']}, Resistance {t['resistance']}, Harm {t['harm']}. Defeat means rescue and a ten-minute delay; withdrawal remains available."
        if t["threat"]:
            text += " " + t["threat"]["description"] + " This observation does not decide your belief about extreme peril."
        return None, None, "Enter the declared conflict.", "One player roll per ten-second exchange; review after six.", dict.fromkeys(("clean", "costly", "setback"), text)
    need(w["active_conflict"] and c["target_id"] in state, "No conflict is active.")
    t = state[c["target_id"]]
    if kind == "reframe":
        method = intent.get("method")
        need(c["limit_due"] and method in ("withdraw", "flank", "negotiate"), "Choose a published new approach.")
        if method == "withdraw":
            w.update(active_conflict=False, safe=True)
            if "magic" in w:
                w["magic"]["opponent_id"] = None
            c["outcome"] = "withdrew; objective remains unresolved"
            p["pending_work_seconds"] += 600
        else:
            need(method not in c["methods"], "That unchanged approach was already used.")
            c["methods"].append(method)
            c.update(exchanges=0, limit_due=False)
        return None, None, "Choose the conflict's next terms.", "Withdrawal costs a declared ten-minute delay; a new approach never adds a surprise attack.", None
    need(kind in ("attack", "defend", "escape", "progress"), "Unknown conflict action.")
    concentration = intent.get("concentration", "drop")
    need(concentration in ("drop", "preserve"), "Choose a concentration response.")
    need(concentration != "preserve" or not p["held"] or p["strain"]+1 <= 2*p["capacity"], "Cannot preserve concentration in every result.")
    damage = 0
    if kind == "attack":
        weapon = intent.get("weapon", "ordinary")
        need(weapon in ("ordinary", "improvised", "heavy", "ranged"), "Unknown weapon class.")
        need(bool(p["equipment"].get(weapon)), "The character does not have that weapon.")
        need(weapon != "heavy" or p["attributes"]["body"] >= 2, "Heavy weapons require Body 2 and both hands.")
        need(type(intent.get("lethal", False)) is bool, "Lethal intent must be explicit Boolean.")
        damage = {"ordinary": 2, "improvised": 1, "heavy": 3, "ranged": 2}[weapon]
        roll = check(p, "grace" if weapon == "ranged" else "body", "marksmanship" if weapon == "ranged" else "melee", t["guard"])
    elif kind == "progress":
        roll = check(p, "presence", "persuasion", t["guard"])
    else:
        warned=kind=='escape' and p.get('warning_ready',False)
        roll = check(p, "grace", "athletics", t["guard"], support=False) if warned else check(p, "grace", "athletics", t["guard"])
        if warned:
            roll['modifier']=2
            p['warning_ready']=False
    advance(state, 10, allow_boundary=True)
    branches, summaries = {}, {}
    for band in ("clean", "costly", "setback"):
        result = deepcopy(state)
        rc, rt = result["conflict"], result[c["target_id"]]
        if band != "setback":
            if kind == "attack":
                removed = min(damage, rt["resistance"])
                rt["resistance"] -= removed
                rc["physical_damage"] += removed
                if rt["resistance"] == 0:
                    binding = any(e["weave_id"] == "W03" and e["target_id"] == c["target_id"] and e["binding_contribution"] for e in result["pc"]["held"])
                    rt["restrained"] = binding
                    rt["defeated"] = not binding
                    if intent.get("lethal", False) and not binding:
                        rt["alive"] = False
            elif kind == "escape":
                result["world"].update(active_conflict=False, safe=True)
                rc["outcome"] = "escaped"
            elif kind == "progress":
                rc["progress"] = min(4, rc["progress"] + (2 if band == "clean" else 1))
                if rc["progress"] == 4:
                    rt["defeated"] = True
                    rc["outcome"] = "negotiated disengagement"
        amount = 0 if band == "clean" else (t["harm"]//2 if kind == "defend" and band == "costly" else t["harm"])
        if amount:
            harm(result, amount, t["harm_source"], concentration)
        finish_exchange(result)
        branches[band] = result
        effect = "The declared action succeeds." if band != "setback" else "The action fails; choose another response."
        summaries[band] = effect + (f" Declared Harm {amount}; choose available ally protection before settling it." if result["conflict"]["pending_harm"] else f" Applied Harm {amount} before protection.")
    return roll, branches, "Resolve " + kind + ".", "One published exchange; no separate foe attack. Lethal intent applies only when explicitly declared.", summaries
