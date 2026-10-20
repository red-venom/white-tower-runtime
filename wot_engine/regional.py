"""Original regional content for rules-v2; never imported by the v1 rules.

All identities, projects, routes, distances and authored decisions are campaign
inventions. Numerical procedures are house rules. This is a finite trusted
policy, not a prose interpreter, autonomous agent or source of canonical lore.
"""
from copy import deepcopy
from math import ceil

from .contracts import ContractError, canonical, digest
from . import knowledge

VERSION = "region-950ne-v1"
DAY = 86400
WORK_DAY = 28800
NPCS = {
    "npc-mentor": ("Maerin", "appointed tutor", "Teach safe technique.", ("channeling", "scholarship"), "Will not permit unconsented experiments.", "practice"),
    "npc-peer": ("Lysa", "fellow novice", "Build confidence through shared work.", ("composure", "notice"), "Will not take blame for another person's choices.", "practice"),
    "npc-steward": ("Toman", "Tower steward", "Keep daily work reliable.", ("persuasion", "medicine"), "Will not conceal missing supplies.", "practice"),
    "npc-asenne": ("Asenne", "alternate tutor", "Make instruction accessible.", ("channeling", "insight"), "Will not teach unsafe shortcuts.", "library"),
    "npc-harin": ("Harin", "Accepted study coordinator", "Keep shared study useful.", ("scholarship", "leadership"), "Cannot grant rank or replace a qualified supervisor.", "library"),
    "npc-jessa": ("Jessa", "archive clerk", "Preserve useful records.", ("scholarship", "notice"), "Will not invent citations.", "library"),
    "npc-pellan": ("Pellan", "carpenter", "Complete sound repairs.", ("athletics", "notice"), "Will not certify unfinished work.", "workshop"),
    "npc-deren": ("Deren", "river transport clerk", "Keep journeys reliable.", ("survival", "leadership"), "Will not arrange an unsafe departure.", "landing"),
    "npc-mira": ("Mira", "infirmary steward", "Keep ordinary care available.", ("medicine", "insight"), "Will respect the patient's consent.", "infirmary"),
    "npc-sefra": ("Sefra", "gardener", "Maintain a shared garden.", ("survival", "scholarship"), "Will not wastefully damage the garden.", "garden"),
    "npc-oren": ("Oren", "messenger", "Deliver accurate messages.", ("survival", "persuasion"), "Will distinguish observation from a reported claim.", "market"),
    "npc-vessa": ("Vessa", "merchant", "Trade on clear terms.", ("persuasion", "notice"), "Will state price before acceptance.", "market"),
}
TEACHERS = ("npc-mentor", "npc-asenne")
NPC_SERVICES = {"npc-mentor":"instruction", "npc-asenne":"instruction", "npc-peer":"parallel", "npc-harin":"study_notice",
                "npc-jessa":"evidence", "npc-steward":"introduction", "npc-pellan":"repair_access", "npc-deren":"transport",
                "npc-mira":"care_access", "npc-sefra":"garden_access", "npc-oren":"message", "npc-vessa":"provisions"}
PRIVATE_NPC_FIELDS = tuple((npc, field) for npc in NPCS for field in
                          ("private_state", "private_oath_ruling", "private_intent"))
LOCATIONS = {
    "practice": ("Tower practice room", True), "library": ("Curriculum library", True),
    "workshop": ("Tower workshop", True), "infirmary": ("Infirmary work room", True),
    "garden": ("Tower garden", True), "market": ("Local market", False),
    "landing": ("River landing", False),
}
PROJECTS = {
    "project-teaching": ("npc-mentor", "Publish a workable teaching rota.", 4, 2*3600, 2, DAY),
    "project-archive": ("npc-jessa", "Index the public records.", 4, 4*3600, 2, 2*DAY),
    "project-repairs": ("npc-pellan", "Repair the practice-room rail.", 4, 6*3600, 2, DAY),
    "project-delivery": ("npc-deren", "Deliver provisions to the receiving store.", 6, 2*WORK_DAY, 2, 3*DAY),
    "project-linen": ("npc-mira", "Rotate the infirmary linen.", 4, 2*WORK_DAY, 6, DAY),
    "project-garden": ("npc-sefra", "Hold a courtyard seed exchange.", 4, 4*3600, 2, 4*DAY),
}
SERVICES = {
    "novice-library": ("novice", "npc-jessa", "Readers using verified records", "library", "records_indexed"),
    "novice-stores": ("novice", "npc-steward", "Staff receiving accurate supplies", "practice", "stores_checked"),
    "accepted-records": ("accepted", "npc-jessa", "People needing checked public evidence", "library", "reports_verified"),
    "accepted-provisions": ("accepted", "npc-deren", "Receiving staff and transport crews", "landing", "deliveries_checked"),
    "independent-care": ("independent", "npc-mira", "Patients receiving ordinary practical care", "infirmary", "care_shifts"),
    "independent-transport": ("independent", "npc-deren", "Travellers receiving checked arrangements", "landing", "journeys_checked"),
}
CHAPTER_AIMS = (
    "Establish safe practice and complete a small service.",
    "Coordinate shared work with competing responsibilities.",
    "Prepare a field task and verify its return.",
    "Explain a novice review using supported evidence.",
    "Choose an Accepted study direction after the test.",
    "Complete Accepted field service with a documented result.",
    "Investigate a disagreement and explain the evidence.",
    "Take responsibility for a decision affecting others.",
    "Resolve a chosen project through broad practical control.",
    "Prepare a complete technical review.",
    "Complete independent service and explain the judgement.",
    "Resolve the formal assessment and choose what follows.",
)
ASSIGNMENTS = {
    1: ("The receiving staff need a usable inventory and an honest account of contributions.", "Deliver a checked count.", "Include contributors in the handover."),
    2: ("Practice and quiet study share two room slots. Neither request has priority by default.", "Give each group its own slot.", "Agree a shared slot and reserve the other for quiet work."),
    3: ("A field task needs an observed destination and a checked return arrangement.", "Record the actual route and return condition.", "Compare the route with the receiving staff's arrangement."),
    4: ("The novice review must distinguish demonstrated readiness from unsupported claims.", "Publish demonstrated limits.", "Explain the remaining support and supervision needs."),
    5: ("The single Accepted test establishes a new study direction.", "Use the completed test's actual choices.", "Use the completed test's actual costs."),
    6: ("Accepted field service needs a result that its beneficiaries can use.", "Verify the completed work against its stated need.", "Check its handover with the people affected."),
    7: ("A dispatch record says sent; a receiving record says not yet counted. Neither proves theft.", "Preserve both records and resolve the counting discrepancy.", "Record the uncertainty and establish a witnessed receiving check."),
    8: ("Two groups request limited work time: care staff and transport staff.", "Reserve the first slot for care and the second for transport.", "Consult both groups and reverse the slot order by agreement."),
    9: ("A completed project has an established result. It does not need a replacement obstacle.", "Review its lasting benefit and limits.", "Record its outcome with the affected people."),
    10: ("The technical review must identify what the completed curriculum actually supports.", "State verified capabilities and limits.", "Record a careful handover of the technical evidence."),
    11: ("Independent service needs a defensible judgement about the effects on other people.", "Explain the actual benefit and remaining limits.", "Explain the competing needs and your selected response."),
    12: ("The single shawl assessment and the player's rank choices conclude this stage.", "Retain the actual formal-test decisions.", "Retain the actual formal-test costs."),
}
VERBS = {"region_choice", "project_work", "region_travel", "region_event", "commitment", "npc_service"}
ACTIVITIES = {"study", "service", "recovery", "travel", "work"}


class RegionalError(ContractError):
    pass


def require(condition, message):
    if not condition:
        raise RegionalError(message)


def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high


def handles(intent):
    return type(intent) is dict and intent.get("verb") in VERBS


def _closed(intent, required, optional=()):
    require(type(intent) is dict and set(required) <= set(intent) and
            set(intent) <= {"verb", *required, *optional}, "Unsupported regional intent fields.")


def _region(state):
    return state["world"]["region"]


def _known(state):
    return state["region-memory"]["known_facts"]


def _commitments(state):
    return state["region-memory"]["commitments"]


def _chapter(state):
    return state.get("progression", {}).get("chapter", {}).get("number", _region(state)["chapter"])


def chapter_proofs(chapter):
    require(integer(chapter, 1, 10000), "Invalid chapter.")
    aim = CHAPTER_AIMS[chapter-1] if chapter <= 12 else "Complete a new agreed post-shawl project and explain its effects."
    third = "readiness" if chapter == 4 else "formal_test" if chapter in (5, 12) else "service"
    return {"chapter": chapter, "aim": aim, "proof_ids": [f"chapter-{chapter}-{x}" for x in ("problem", "judgement", third)], "proofs": [
        {"proof_id": f"chapter-{chapter}-problem", "description": "Resolve the published assignment with its actual result.", "methods": ["care", "consultation"]},
        {"proof_id": f"chapter-{chapter}-judgement", "description": "Choose and explain a stated tradeoff without an invented moral answer.", "methods": ["care", "speed", "consultation"]},
        {"proof_id": f"chapter-{chapter}-{third}", "description": "Use the already earned readiness or formal evidence." if third != "service" else "Complete a new useful service day for its stated beneficiary.", "methods": ["records", "practical"]},
    ]}


def begin_chapter(state, chapter, action_id):
    contract = chapter_proofs(chapter)
    r = _region(state)
    require(chapter >= r["chapter"], "A completed chapter cannot be reopened.")
    if chapter == r["chapter"]:
        require(not r["proofs"], "Current chapter evidence cannot be reset.")
    carried = {key:value for key,value in _commitments(state).items() if value["status"] == "active"}
    _commitments(state).clear()
    _commitments(state).update(carried)
    r.update(chapter=chapter, proofs={}, assignment={"id": f"assignment-{chapter}", "status": "open", "method": None,
             "beneficiary": "People relying on the chapter's published result", "source_action": action_id})


def initialize(state):
    require("region" not in state["world"], "Region is already initialized.")
    w = state["world"]
    w["main_activity"] = {"day": w["time_seconds"]//DAY, "used_seconds": 0, "by_kind": {k: 0 for k in sorted(ACTIVITIES)}}
    state["region-memory"] = {"known_facts": {}, "commitments": {}, "service_evidence": dict.fromkeys(str(x) for x in (1,2,3,6,7,8,9,10,11)), "post_service": None}
    w["region"] = {"version": VERSION, "location_id": "practice", "chapter": 1, "proofs": {}, "assignment": {},
        "opening": {"lesson": None, "peer": None, "service": None},
        "benefits": {**{x[4]: 0 for x in SERVICES.values()}, "opening_service": 0}, "supply_day": {"day": w["time_seconds"]//DAY, "units": 0, "shortage": 0},
        "last_time_supplied": True,
        "party": ["pc"], "last_event": None, "last_npc_decision": None, "last_oath_result": None,
        "route_access": [], "disposition": None, "field_situation": None}
    begin_chapter(state, 1, "genesis")
    for npc_id, (name, role, goal, competences, boundary, location) in NPCS.items():
        npc = state.setdefault(npc_id, {"kind": "person", "name": name, "role": role, "location": LOCATIONS[location][0],
            "motive": goal, "competences": list(competences), "boundary": boundary, "bond": 1, "support_remaining": 2,
            "willing": True, "consenting": True, "alive": True, "ordinary_target": True, "distance_m": 0,
            "visible": location == "practice", "vitality": 8, "max_vitality": 8, "wounds": 0,
            "firstaid_used": False, "healing_used": False, "restrained": False, "private_intent": "observe"})
        npc["oaths_active"] = npc_id in TEACHERS
        npc["private_oath_ruling"] = None
        npc.setdefault("magic", {"treatment": None, "treatment_completed_at": None, "shielded_by": None})
        npc["private_state"] = {"location_id": location, "resources": {"work_seconds": WORK_DAY, "mount_loans": 1 if npc_id == "npc-deren" else 0},
            "commitments": {}, "relationships": {"pc": "acquaintance"}, "plan": "role-policy",
            "beliefs": [{"belief_id": npc_id+"-service-belief", "proposition_id": "safe-service", "value": True,
                         "evidence_ids": [npc_id+"-notice"]}] if npc_id in TEACHERS else [],
            "evidence": [npc_id+"-notice"], "last_decision": None, "last_rest_end": None, "pending_task_seconds": 600 if npc_id == "npc-peer" else 0}
    for project_id, (owner, aim, target, labour, materials, due) in PROJECTS.items():
        state[project_id] = {"kind": "project", "owner_id": owner, "aim": aim, "target": target, "progress": 0,
            "budget": {"work_seconds": labour, "materials": materials}, "required": {"work_seconds": labour, "materials": materials},
            "prerequisites": {"access": True, "materials": True, "participants": project_id != "project-garden"},
            "status": "active", "due_second": w["time_seconds"]+due, "event_id": project_id+"-due", "source_action": "genesis",
            "outcome": None}
    _observe_location(state)
    _update_deadline(state)
    validate_region(state)


def validate_region(state):
    r = _region(state)
    require(r["version"] == VERSION and r["location_id"] in LOCATIONS, "Unknown region or location.")
    require(integer(r["chapter"], 1, 10000), "Invalid chapter state.")
    require(len(r["proofs"]) <= 3 and len(_known(state)) <= 32 and len(_commitments(state)) <= 12, "Regional evidence exceeds its bound.")
    for npc_id in NPCS:
        npc = state[npc_id]
        require(npc["kind"] == "person" and len(npc["competences"]) == 2, "Invalid NPC definition.")
        require(integer(npc["bond"], 0, 3) and integer(npc["support_remaining"], 0, 2), "Invalid ally resources.")
        private = npc["private_state"]
        require(private["location_id"] in LOCATIONS and integer(private["resources"]["work_seconds"]), "Invalid private NPC state.")
    for project_id in PROJECTS:
        p = state[project_id]
        require(p["owner_id"] in NPCS and integer(p["progress"], 0, p["target"]) and p["target"] in (4, 6), "Invalid project progress.")
        require(p["status"] in ("active", "completed", "stalled", "cancelled", "failed"), "Invalid project status.")
        require(p["due_second"] is None or integer(p["due_second"]), "Invalid project deadline.")
        require(all(integer(x) for x in p["budget"].values()), "Negative project budget.")
        require(all(type(x) is bool for x in p["prerequisites"].values()), "Invalid project prerequisite.")
    ledger = state["world"]["main_activity"]
    require(set(ledger) == {"day", "used_seconds", "by_kind"} and integer(ledger["day"]) and
            integer(ledger["used_seconds"], 0, WORK_DAY) and set(ledger["by_kind"]) == ACTIVITIES and
            all(integer(x, 0, WORK_DAY) for x in ledger["by_kind"].values()) and
            sum(ledger["by_kind"].values()) == ledger["used_seconds"], "Invalid daily activity ledger.")


def _update_deadline(state):
    if _opening_active(state):
        return
    times = [state[x]["due_second"] for x in PROJECTS if state[x]["status"] == "active" and state[x]["due_second"] is not None]
    state["world"]["next_event_second"] = min(times) if times else None


def _opening_active(state):
    return state["world"].get("episode", {}).get("phase") not in (None, "complete")


def refresh(state):
    """Update derived deadlines on a private action copy, never in a read view."""
    _update_deadline(state)


def account_time(state, start, end):
    """Shared clock hook: charge actual exposed days once, including rest/wait.

    The root clock calls this exactly once before assigning the new time.
    Calendar boundaries may be crossed by a continuous rest. No main-activity
    credit is granted here. A due event must still be resolved separately.
    """
    require(integer(start) and integer(end, start) and start == state["world"]["time_seconds"], "Invalid clock accounting interval.")
    if end == start:
        return
    if _opening_active(state):
        due = state["world"]["next_event_second"]
    else:
        times = [state[x]["due_second"] for x in PROJECTS if state[x]["status"] == "active" and state[x]["due_second"] is not None]
        due = min(times) if times else None
    require(due is None or end <= due, "A regional event interrupts this interval.")
    if state["world"]["supplied"]:
        _region(state)["last_time_supplied"] = True
        return
    r = _region(state)
    party = r["party"]
    require(type(party) is list and "pc" in party and len(set(party)) == len(party) and
            all(x == "pc" or x in NPCS for x in party), "Invalid travelling group.")
    units, charge = ceil(len(party)/4), r["supply_day"]
    days = range(start//DAY, (end-1)//DAY+1)
    all_supplied = True
    for day in days:
        provided = charge["units"] if charge["day"] == day else 0
        needed = max(0, units-provided)
        paid = min(needed, state["pc"]["supply"])
        state["pc"]["supply"] -= paid
        provided += paid
        shortage = max(0, units-provided)
        all_supplied = all_supplied and shortage == 0
        charge.update(day=day, units=provided, shortage=shortage)
    r["last_time_supplied"] = all_supplied


def supplied_today(state):
    """Whether the last accounted interval had institutional or paid provisions."""
    return state["world"]["supplied"] or _region(state)["last_time_supplied"]


def can_supply_interval(state, start, end):
    if state["world"]["supplied"] or start == end:
        return True
    charge = _region(state)["supply_day"]
    units = ceil(len(_region(state)["party"])/4)
    needed = sum(max(0, units-(charge["units"] if charge["day"] == day else 0)) for day in range(start//DAY, (end-1)//DAY+1))
    return state["pc"]["supply"] >= needed


def complete_ally_rest(state, npc_id, start, end):
    require(npc_id in NPCS and end-start == WORK_DAY and end == state["world"]["time_seconds"] and state["world"]["safe"], "An ally needs its own full safe rest.")
    npc = state[npc_id]
    require(npc["visible"] and npc["willing"] and npc["private_state"]["location_id"] == _region(state)["location_id"], "This ally did not share the rest location.")
    npc["support_remaining"] = 2
    npc["private_state"]["resources"]["work_seconds"] = WORK_DAY
    npc["private_state"]["last_rest_end"] = end


def travel_seconds(distance_km, mode="walk", *, rough=False, severe_weather=False):
    require(integer(distance_km,1) and mode in ("walk","ride") and type(rough) is bool and type(severe_weather) is bool, "Invalid authored route.")
    rate = 24 if mode == "walk" else 40
    divisor = (2 if rough else 1)*(2 if severe_weather else 1)
    return ceil(480*distance_km*divisor/rate)*60


def next_boundary(state, requested_seconds):
    require(integer(requested_seconds, 1), "Duration must be a positive integer.")
    now = state["world"]["time_seconds"]
    due = sorted((state[x]["due_second"], state[x]["event_id"]) for x in PROJECTS
                 if state[x]["status"] == "active" and state[x]["due_second"] is not None)
    if _opening_active(state):
        due = [] if state["world"]["next_event_second"] is None else [(state["world"]["next_event_second"], "opening-event")]
    end = min(now+requested_seconds, now+WORK_DAY, (now//DAY+1)*DAY)
    reason = "requested" if end == now+requested_seconds else "calendar"
    if due and due[0][0] <= end:
        end, reason = max(now, due[0][0]), "event"
    return {"elapsed_seconds": end-now, "stop_reason": reason,
            "due_event_ids": [event for second, event in due if second <= end] if reason == "event" else []}


def advance_activity(state, requested_seconds, kind, *, advance_clock):
    require(kind in ACTIVITIES | {"wait", "rest"}, "Unknown activity kind.")
    boundary = next_boundary(state, requested_seconds)
    now, r = state["world"]["time_seconds"], _region(state)
    elapsed = boundary["elapsed_seconds"]
    ledger = state["world"]["main_activity"]
    day = now//DAY
    if ledger["day"] != day:
        ledger.update(day=day, used_seconds=0, by_kind={k: 0 for k in sorted(ACTIVITIES)})
    if kind in ACTIVITIES and elapsed > WORK_DAY-ledger["used_seconds"]:
        elapsed = WORK_DAY-ledger["used_seconds"]
        boundary.update(stop_reason="activity_allowance", due_event_ids=[])
    require(elapsed > 0, "Resolve the current event or activity boundary before continuing.")
    if kind == "recovery":
        require(ledger["used_seconds"] == ledger["by_kind"]["recovery"], "Wound recovery cannot share this day's main activity with other work.")
    elif kind in ACTIVITIES:
        require(ledger["by_kind"]["recovery"] == 0, "This day's main activity is reserved for Wound recovery.")
    advance_clock(state, elapsed, allow_boundary=True)
    if kind in ACTIVITIES:
        ledger["used_seconds"] += elapsed
        ledger["by_kind"][kind] += elapsed
    return {"elapsed_seconds": elapsed, "credited_seconds": elapsed if kind in ACTIVITIES else 0,
            "stop_reason": boundary["stop_reason"], "due_event_ids": boundary["due_event_ids"]}


def _observe_location(state):
    w, r = state["world"], _region(state)
    w["location"], w["supplied"] = LOCATIONS[r["location_id"]]
    w["safe"] = True
    for npc_id in NPCS:
        npc = state[npc_id]
        npc["visible"] = npc["private_state"]["location_id"] == r["location_id"]
        if npc["visible"]:
            npc["location"], npc["distance_m"] = w["location"], 0


def _proof(state, category, action_id, detail):
    chapter, r = _chapter(state), _region(state)
    require(chapter == r["chapter"], "Publish this chapter's regional contract first.")
    key = f"chapter-{chapter}-{category}"
    require(key in chapter_proofs(chapter)["proof_ids"], "Unknown authored proof.")
    if key not in r["proofs"]:
        r["proofs"][key] = {"action_id": action_id, "detail": detail}


def proof_facts(state):
    facts = deepcopy(_region(state)["proofs"])
    chapter = _chapter(state)
    progress = state.get("progression", {})
    service = state["region-memory"]["service_evidence"].get(str(chapter))
    if chapter > 12:
        service = state["region-memory"]["post_service"]
        if service and service["chapter"] != chapter:
            service = None
    if service:
        facts[f"chapter-{chapter}-service"] = deepcopy(service)
    if chapter == 4:
        review = progress.get("reviews", {}).get("accepted")
        if review and review["status"] == "ready":
            facts["chapter-4-readiness"] = {"action_id": review["event"], "detail": "Completed Accepted readiness review."}
    elif chapter in (5, 12):
        test = progress.get("accepted_test" if chapter == 5 else "shawl_test", {})
        evidence = test.get("evidence", [])
        if test.get("completed") and len(evidence) >= 3:
            for category, source in zip(("problem", "judgement", "formal_test"), evidence[-3:]):
                facts[f"chapter-{chapter}-{category}"] = {"action_id": source, "detail": "Actual completed formal-test scene; no repeat assignment or service day."}
    return facts


def record_opening_proofs(state, action_id):
    """Credit only actual completed opening effects, never an invented work day."""
    episode = state["world"].get("episode", {})
    if episode.get("phase") != "complete" or _chapter(state) != 1:
        return
    if episode.get("handoff_complete") and episode.get("inventory_complete"):
        if "chapter-1-problem" not in _region(state)["proofs"]:
            _proof(state, "problem", action_id, "Verified opening inventory and handoff.")
            _region(state)["assignment"].update(status="resolved", method=episode["inventory_method"], source_action=action_id)
    if episode.get("credit_choice") in ("accurate", "sole"):
        _proof(state, "judgement", action_id, "Actual contribution-credit choice: "+episode["credit_choice"])
    if episode.get("lesson_complete") and _region(state)["opening"]["lesson"] is None:
        _region(state)["opening"]["lesson"] = {"method": episode["lesson_source"], "source_action": action_id}


def _service_days(state):
    return sum(value for key, value in _region(state)["benefits"].items() if key != "opening_service")


def _assignment_ready(state):
    chapter = _chapter(state)
    if chapter in (5, 12):
        return False
    if chapter == 3:
        return any("visit-"+x in _known(state) for x in ("market", "landing"))
    if chapter in (4, 10):
        review = state.get("progression", {}).get("reviews", {}).get("accepted" if chapter == 4 else "technical")
        return bool(review and review["status"] == "ready")
    if chapter in (6, 11):
        return state.get("progression", {}).get("service_"+("accepted" if chapter == 6 else "independent"), {}).get("benefits", 0) > 0
    if chapter == 9:
        return any(state[x]["status"] == "completed" for x in PROJECTS)
    return chapter <= 12 or f"chapter-{chapter}-service" in proof_facts(state)


def _activity_fits(state, seconds, kind):
    if next_boundary(state, seconds)["elapsed_seconds"] != seconds:
        return False
    ledger = state["world"]["main_activity"]
    if ledger["day"] != state["world"]["time_seconds"]//DAY or kind not in ACTIVITIES:
        return True
    return ledger["by_kind"]["recovery"] == 0 and ledger["used_seconds"]+seconds <= WORK_DAY


def service_task(task_id, state):
    require(task_id in SERVICES, "Unknown authored service task.")
    track, owner, beneficiary, location, benefit = SERVICES[task_id]
    rank = state["pc"]["rank"]
    require(track == "novice" or rank in ("Accepted", "accepted", "Aes Sedai", "aes_sedai", "aessedai"), "This service needs Accepted responsibility.")
    return {"task_id": task_id, "track": track, "owner_id": owner, "beneficiary": beneficiary,
            "location_id": location, "required_seconds": WORK_DAY, "methods": ["care", "consultation"],
            "prerequisites": ["safe", "supplied_or_daily_supply"], "proof_ids": [f"chapter-{_chapter(state)}-service"],
            "description": "Complete a documented useful work day for "+beneficiary+".", "benefit_id": benefit}


def complete_service(state, task_id, action_id, days=1):
    task = service_task(task_id, state)
    require(integer(days, 1, 100), "Invalid completed service days.")
    progress = state["progression"]["service_"+task["track"]]
    credit = progress["task_credit"].get(task_id)
    require(credit is not None and integer(credit["days"]) and integer(credit["consumed_days"]) and
            credit["days"]-credit["consumed_days"] >= days, "Service has no unconsumed completed work day.")
    require(_region(state)["location_id"] == task["location_id"], "Service beneficiary is at another location.")
    credit["consumed_days"] += days
    if task["location_id"] not in progress["settings"]:
        progress["settings"].append(task["location_id"])
    progress["outside_group"] = progress["outside_group"] or task["track"] == "independent" or task_id == "accepted-provisions"
    progress["benefits"] += days
    _region(state)["benefits"][task["benefit_id"]] += days
    eligible = {"novice": (1,2,3), "accepted": (6,7,8,9,10), "independent": (11,)}[task["track"]]
    slots = state["region-memory"]["service_evidence"]
    for _ in range(days):
        available = next((chapter for chapter in eligible if slots[str(chapter)] is None), None)
        evidence = {"action_id": action_id, "detail": task["beneficiary"]}
        if available is not None:
            slots[str(available)] = evidence
        elif _chapter(state) > 12:
            state["region-memory"]["post_service"] = {**evidence, "chapter": _chapter(state)}


def _evidence(npc_id, npc):
    """Expand only held, explicitly authored evidence references from this build."""
    result = []
    for item in npc["private_state"]["evidence"]:
        if type(item) is str:
            require(item == npc_id+"-notice", "Unknown authored evidence reference.")
            result.append({"evidence_id": item, "basis": "observation", "statement": "This service has the stated safe scope.",
                           "source_event": "genesis", "audience_ids": [npc_id]})
        else:
            result.append(deepcopy(item))
    return result


def _guard(state, npc_id, rule_id, changes, action_id, context):
    require(type(context) is dict and set(context) >= {"campaign_id", "head_hash"}, "NPC decision needs trusted campaign context.")
    npc = state[npc_id]
    evidence_id = npc_id+"-notice"
    facts, sources = [], {}
    actor_evidence = _evidence(npc_id, npc)
    for evidence in actor_evidence:
        facts.append({"fact_id": evidence["evidence_id"], "statement": evidence["statement"],
                      "basis": "message" if evidence["basis"] == "testimony" else evidence["basis"],
                      "source_ids": [evidence["source_event"]], "visibility": "npc", "audience_ids": evidence["audience_ids"]})
        sources[evidence["source_event"]] = {"visibility": "npc", "audience_ids": evidence["audience_ids"]}
    resource_id, boundary_id = npc_id+"-resources", context["head_hash"]
    facts.append({"fact_id":resource_id,"statement":canonical(npc["private_state"]["resources"]).decode(),"basis":"observation",
                  "source_ids":[boundary_id],"visibility":"npc","audience_ids":[npc_id]})
    sources[boundary_id]={"visibility":"npc","audience_ids":[npc_id]}
    kwargs = {**context, "recipient_role": "npc", "recipient_id": npc_id, "facts": facts, "sources": sources}
    packet = knowledge.build_packet(**kwargs)
    knowledge.validate_issued_packet(packet, **kwargs)
    now = state["world"]["time_seconds"]
    policy = {"schema": "npc-policy-v1", **context, "npc_id": npc_id, "not_before_second": now, "expires_at_second": now,
        "options": [{"rule_id": rule_id, "npc_id": npc_id, "required_evidence_ids": [evidence_id,resource_id], "changes": changes, "scope": "public_stakes"}]}
    proposal_id = "npc-"+digest({"action":action_id,"npc":npc_id})[:48]
    proposal = {"schema": "npc-proposal-v1", **context, "proposal_id": proposal_id,
        "npc_id": npc_id, "packet_hash": packet["packet_hash"], "decision": "Perform the exact authored option within the published boundary.",
        "evidence_ids": [evidence_id,resource_id], "proposed_changes": changes, "rule_ids": [rule_id], "valid_until_second": now}
    review = knowledge.validate_proposal(proposal, packet, **context, now_seconds=now, state=state,
                                         policy=policy, private_npc_fields=PRIVATE_NPC_FIELDS)
    npc["private_state"]["last_decision"] = {"action_id": action_id, "proposal_hash": review.as_data()["proposal_hash"],
                                               "packet_hash": packet["packet_hash"], "rule_id": rule_id}
    _region(state)["last_npc_decision"] = {"npc_id": npc_id, "rule_id": rule_id, "source_action": action_id}
    if npc["oaths_active"]:
        from .oaths import adjudicate, public_view as public_oath
        ruling = adjudicate({"actor_id": npc_id, "oaths_active": True, "oaths_source_event": "genesis",
                             "beliefs": npc["private_state"]["beliefs"], "evidence": actor_evidence},
            {"proposal_id": "oath-"+digest({"action":action_id,"npc":npc_id})[:48], "kind": "speech", "statement_or_action": "This service has the stated safe scope.",
             "intent": "Explain the authored service.", "details": {"speech_act": "statement", "proposition_id": "safe-service", "assertion": True, "literal_credible": True}})
        require(ruling["result"] == "ALLOW", ruling["public_reason"])
        npc["private_oath_ruling"] = ruling
        _region(state)["last_oath_result"] = public_oath(ruling)


def _guard_result(before, after, npc_id, rule_id, action_id, context):
    """Validate the actual authored effects, not an empty ceremonial proposal."""
    changes=[]
    for record_id in sorted(before):
        require(set(before[record_id]) == set(after[record_id]),"Regional decisions cannot add fields.")
        for field_id in sorted(before[record_id]):
            a,b=before[record_id][field_id],after[record_id][field_id]
            if canonical(a) != canonical(b):
                changes.append({"record_id":record_id,"field_id":field_id,"before":deepcopy(a),"after":deepcopy(b)})
    _guard(before,npc_id,rule_id,changes,action_id,context)
    after[npc_id]["private_state"]["last_decision"]=deepcopy(before[npc_id]["private_state"]["last_decision"])
    after[npc_id]["private_oath_ruling"]=deepcopy(before[npc_id]["private_oath_ruling"])
    for field in ("last_npc_decision","last_oath_result"):
        _region(after)[field]=deepcopy(_region(before)[field])


def proposal_hashes(state, action_id):
    return sorted(npc["private_state"]["last_decision"]["proposal_hash"] for key, npc in state.items()
                  if key in NPCS and npc["private_state"]["last_decision"] is not None and
                  npc["private_state"]["last_decision"]["action_id"] == action_id)


def _routine(state, goal, summary):
    validate_region(state)
    return None, {band: deepcopy(state) for band in ("clean", "costly", "setback")}, goal, "Use the published regional rule and exact listed costs.", dict.fromkeys(("clean", "costly", "setback"), summary)


def resolve(state, intent, action_id, *, advance, check=None, harm=None, context=None):
    """Resolve on the caller's private copy, never on committed state."""
    require(handles(intent), "Unknown regional verb.")
    require(not _opening_active(state), "Finish the authored opening before regional actions.")
    validate_region(state)
    r, w, p = _region(state), state["world"], state["pc"]
    decision_before, npc_decision = deepcopy(state), None
    verb = intent["verb"]
    require(not w["active_conflict"], "Finish the active conflict before regional work.")
    summary = "Complete the stated regional action."
    if verb == "region_choice":
        _closed(intent, ("choice_id",), ("method",))
        choice = intent["choice_id"]
        if choice in ("lesson", "library"):
            require(r["opening"]["lesson"] is None, "This opening lesson is already recorded.")
            require(r["location_id"] in ("practice", "library"), "Travel to an instruction location first.")
            if choice == "lesson":
                teacher = "npc-mentor" if r["location_id"] == "practice" else "npc-asenne"
                require(state[teacher]["willing"], "Use the independent teaching route.")
                npc_decision = (teacher, "regional-safe-lesson")
            result = advance_activity(state, 600, "study", advance_clock=advance)
            require(result["elapsed_seconds"] == 600, "The lesson cannot finish before this boundary; use a shorter activity.")
            r["opening"]["lesson"] = {"method": choice, "source_action": action_id}
            summary = "Complete the voluntary lesson without a chapter reward or new weave grant."
        elif choice in ("peer.help", "peer.other", "peer.decline"):
            require(r["opening"]["peer"] is None, "This peer decision is already recorded.")
            require(state["npc-peer"]["visible"], "Lysa is not present.")
            if choice != "peer.decline":
                npc_decision = ("npc-peer", "regional-peer-choice")
                advance_activity(state, 600 if choice == "peer.help" else 60, "work", advance_clock=advance)
                state["npc-peer"]["private_state"]["pending_task_seconds"] = 0 if choice == "peer.help" else 600
                state["npc-peer"]["private_state"]["relationships"]["pc"] = "Received practical help" if choice == "peer.help" else "Received another helper's introduction"
            r["opening"]["peer"] = {"choice": choice, "source_action": action_id}
            summary = "Record the stated peer choice without assigning your feelings or allegiance."
        elif choice == "chapter.resolve":
            require(r["assignment"]["status"] == "open", "This assignment is already resolved.")
            method = intent.get("method")
            require(method in ("care", "consultation"), "Choose a published method.")
            chapter = _chapter(state)
            require(chapter not in (5,12), "The actual formal-test scenes supply this chapter's proofs.")
            if chapter == 3:
                require(any("visit-"+x in _known(state) for x in ("market","landing")), "Observe an actual field destination before claiming a checked return plan.")
            if chapter in (4,10):
                kind = "accepted" if chapter == 4 else "technical"
                review = state.get("progression",{}).get("reviews",{}).get(kind)
                require(review and review["status"] == "ready", "Use the actual completed readiness review.")
            if chapter in (6,11):
                track = "accepted" if chapter == 6 else "independent"
                require(state.get("progression",{}).get("service_"+track,{}).get("benefits",0) > 0,"Use an actual beneficial service result.")
            if chapter == 9:
                require(any(state[x]["status"] == "completed" for x in PROJECTS), "Resolve a real project first; an early completed result counts.")
            duration = 600 if chapter in (4,9,10,11) else 3600 if method == "care" else 7200
            result = advance_activity(state, duration, "work", advance_clock=advance)
            require(result["elapsed_seconds"] == duration, "Split other work at the pending boundary before this assignment.")
            definition = ASSIGNMENTS.get(chapter, ("A new post-shawl service chapter has a different current beneficiary.", "Verify the newly completed work.", "Consult its current beneficiaries."))
            if chapter > 12:
                require(f"chapter-{chapter}-service" in proof_facts(state), "A post-shawl assignment needs its own new service result.")
            r["assignment"].update(status="resolved", method=method, source_action=action_id,
                                   result=definition[1 if method == "care" else 2])
            _proof(state, "problem", action_id, chapter_proofs(_chapter(state))["aim"])
            _proof(state, "judgement", action_id, definition[1 if method == "care" else 2])
            summary = "Resolve the published chapter assignment with the chosen method. Preserve that result."
        elif choice == "service.method":
            method = intent.get("method")
            require(method in ("speed", "care", "consultation") and r["opening"]["service"] is None, "Invalid or completed service-method choice.")
            duration = {"speed":300,"care":600,"consultation":1200}[method]
            result = advance_activity(state,duration,"work",advance_clock=advance)
            require(result["elapsed_seconds"] == duration,"This service method needs its stated time before the next boundary.")
            beneficiary = {"speed":"Staff needing an early usable count","care":"Staff needing a checked detailed record","consultation":"Workers whose different needs enter the handover"}[method]
            r["opening"]["service"] = {"method": method, "source_action": action_id, "beneficiary":beneficiary}
            r["benefits"]["opening_service"] += 1
            summary = "Complete the chosen service method for "+beneficiary+". No method is a secret correct answer."
        elif choice in ("field.encounter", "field.dangerous", "field.report"):
            require(r["location_id"] == "landing" and r["field_situation"] is None, "This optional field situation is absent or already resolved.")
            if choice == "field.report":
                result=advance_activity(state,600,"work",advance_clock=advance)
                require(result["elapsed_seconds"] == 600,"Make the report before the next boundary.")
                r["field_situation"]={"result":"Reported the public demand for an unauthorized fee; left the road clear for staff.","source_action":action_id}
                summary="Report the observed obstruction and leave its handling to the responsible staff. No combat is required."
            else:
                from .combat import activate
                require(p["wounds"] < 3,"Rest and care are required before another field operation.")
                require("foe-ordinary" in state,"The full conflict module is not initialized.")
                target_id='foe-dangerous' if choice=='field.dangerous' else 'foe-ordinary'
                activate(state,target_id,w['location'])
                from .magic import boundary_crossing
                if 'magic' in p:
                    boundary_crossing(state,location=w['location'])
                r['field_situation']={'result':'Observed the approaching raider.' if choice=='field.dangerous' else 'Observed the road group demanding an unauthorized fee.','source_action':action_id}
                target=state[target_id]
                summary=f"The optional encounter approaches across the observed boundary: Guard{target['guard']}, Resistance{target['resistance']}, Harm{target['harm']}. Choose engagement or leave; no promotion proof requires this conflict."
        else:
            raise RegionalError("Unknown regional choice.")
    elif verb == "project_work":
        _closed(intent, ("project_id", "method"))
        require(intent["project_id"] in PROJECTS, "Unknown project.")
        project = state[intent["project_id"]]
        require(project["status"] in ("active", "stalled"), "Completed or cancelled projects cannot reopen.")
        require(intent["method"] in ("care", "consultation"), "Unknown work method.")
        require(all(project["prerequisites"].values()), "This project's published prerequisites are missing.")
        gain = min(2, project["target"]-project["progress"])
        material_cost = ceil(project["required"]["materials"]*gain/(project["target"]-project["progress"]))
        require(project["budget"]["materials"] >= material_cost, "This project lacks the stated materials.")
        owner_location = state[project["owner_id"]]["private_state"]["location_id"]
        require(r["location_id"] == owner_location, "Travel to this project's work location first.")
        result = advance_activity(state, 3600, "work", advance_clock=advance)
        require(result["elapsed_seconds"] == 3600, "A project contribution needs one complete available hour.")
        project["budget"]["materials"] -= material_cost
        project["required"]["materials"] -= material_cost
        project["required"]["work_seconds"] = max(0, project["required"]["work_seconds"]-3600)
        project["progress"] += gain
        project["source_action"] = action_id
        if project["progress"] == project["target"]:
            project.update(status="completed", due_second=None, outcome="Completed through the recorded contributions.")
        _update_deadline(state)
        summary = "Add the actual work to the project. A completed project stays complete."
    elif verb == "region_event":
        _closed(intent, ())
        due = sorted((state[x]["due_second"], state[x]["event_id"], x) for x in PROJECTS
                     if state[x]["status"] == "active" and state[x]["due_second"] is not None)
        require(due, "No regional event is scheduled.")
        second, event_id, project_id = due[0]
        if second > w["time_seconds"]:
            result = advance_activity(state, second-w["time_seconds"], "wait", advance_clock=advance)
            if w["time_seconds"] < second:
                return _routine(state, "Wait to the next safe time boundary.", "Advance only to this calendar boundary; the project event remains pending.")
        project = state[project_id]
        can_finish = all(project["prerequisites"].values()) and all(project["budget"][x] >= project["required"][x] for x in project["required"])
        status = "completed" if can_finish else "failed" if project_id == "project-garden" and not project["prerequisites"]["participants"] else "stalled"
        npc_decision = (project["owner_id"], "regional-project-deadline")
        if can_finish:
            for resource, amount in project["required"].items():
                project["budget"][resource] -= amount
            project["progress"] = project["target"]
        project.update(status=status, due_second=None, source_action=action_id,
                       outcome="The owner reports completed work." if can_finish else "The exchange ends without participants; the seeds remain available." if status == "failed" else "The owner reports missing prerequisites or resources; no free progress occurs.")
        r["last_event"] = {"event_id": event_id, "source_action": action_id, "result": project["outcome"], "basis": "message"}
        _update_deadline(state)
        summary = project["outcome"]
    elif verb == "region_travel":
        _closed(intent, ("destination",), ("mode",))
        destination = intent["destination"]
        require(destination in LOCATIONS and destination != r["location_id"], "Choose another known regional location.")
        require(LOCATIONS[destination][1] or p["wounds"] < 3,"Use rest and care before another exposed field journey; return to institutional care remains available.")
        mode = intent.get("mode", "walk")
        require(mode in ("walk", "ride"), "Unknown travel method.")
        require(mode != "ride" or "supplied-fit-mount" in r["route_access"], "Riding requires a supplied fit mount.")
        exposed = not LOCATIONS[destination][1] or not LOCATIONS[r["location_id"]][1]
        seconds = travel_seconds(1,mode) if exposed else 600
        w["supplied"] = not exposed
        require(LOCATIONS[destination][1] or can_supply_interval(state,w["time_seconds"],w["time_seconds"]+seconds),
                "Obtain provisions or return directly to an institutional supplied location before onward travel.")
        result = advance_activity(state, seconds, "travel", advance_clock=advance)
        require(result["elapsed_seconds"] == seconds, "This route cannot finish before the next boundary.")
        r["location_id"] = destination
        _observe_location(state)
        if 'magic' in p:
            from .magic import advance_effects
            advance_effects(state,w['time_seconds'],w['time_seconds'])
            p['warning_ready']=False
        _known(state)["visit-"+destination] = {"statement":"Observed the published route and destination: "+LOCATIONS[destination][0],"basis":"observation","source_action":action_id}
        summary = "Complete the published route and observe only people actually present."
    elif verb == "commitment":
        _closed(intent, ("npc_id", "operation"))
        npc_id, operation = intent["npc_id"], intent["operation"]
        require(npc_id in NPCS and state[npc_id]["visible"], "The named person is not present.")
        require(operation in ("accept", "fulfil", "break", "decline"), "Unknown commitment operation.")
        key = next((key for key,value in _commitments(state).items() if key.endswith("-"+npc_id) and value["status"] == "active"), f"chapter-{_chapter(state)}-{npc_id}")
        entry = _commitments(state).get(key)
        if operation in ("accept", "decline"):
            require(entry is None, "This commitment already has a recorded decision.")
            _commitments(state)[key] = {"status": "active" if operation == "accept" else "declined", "action_id": action_id,
                                      "term": "Complete a new useful service day before claiming this promise fulfilled.", "benefits_before": _service_days(state)}
        else:
            require(entry is not None and entry["status"] == "active", "No unresolved accepted commitment.")
            if operation == "fulfil":
                require(_service_days(state) > entry["benefits_before"], "No new service day supports fulfilment.")
            after = min(3, state[npc_id]["bond"]+1) if operation == "fulfil" else max(0, state[npc_id]["bond"]-1)
            npc_decision = (npc_id, "regional-recorded-commitment")
            state[npc_id]["bond"] = after
            entry.update(status="fulfilled" if operation == "fulfil" else "broken", action_id=action_id)
        state[npc_id]["private_state"]["commitments"] = {key: deepcopy(_commitments(state)[key])}
        state[npc_id]["private_state"]["relationships"]["pc"] = _commitments(state)[key]["status"]+" stated commitment"
        summary = "Record the explicit commitment decision and its supported relationship consequence."
    elif verb == "npc_service":
        _closed(intent, ("npc_id", "service"))
        npc_id, service = intent["npc_id"], intent["service"]
        require(npc_id in NPCS and state[npc_id]["visible"] and state[npc_id]["willing"], "This person cannot provide the requested help here.")
        require(service == NPC_SERVICES[npc_id] or (npc_id == "npc-deren" and service == "return_mount"), "Help must fit this person's authored competence and resources.")
        require(npc_id not in _known(state) or service in ("provisions", "parallel", "return_mount"), "This same assistance is already recorded; use its result.")
        npc_decision = (npc_id, "regional-"+service)
        if service == "provisions":
            require(p["silver"] >= 1 and p["supply"] <= 4, "Two Supply cost one silver and must fit the cap.")
            p["silver"] -= 1; p["supply"] += 2
        elif service == "parallel":
            require(state[npc_id]["support_remaining"] > 0 and p["pending_work_seconds"] >= 600, "Parallel help needs an actual unfinished ten-minute task and an ally use.")
            state[npc_id]["support_remaining"] -= 1
            require(state[npc_id]["private_state"]["resources"]["work_seconds"] >= 600, "The ally has no work time left.")
            result = advance_activity(state, 600, "wait", advance_clock=advance)
            require(result["elapsed_seconds"] == 600, "The ally cannot finish before the next boundary.")
            state[npc_id]["private_state"]["resources"]["work_seconds"] -= 600
            p["pending_work_seconds"] -= 600
        elif service == "transport":
            require(state[npc_id]["private_state"]["resources"]["mount_loans"] > 0,"No supplied fit mount is available for this arrangement.")
            state[npc_id]["private_state"]["resources"]["mount_loans"] -= 1
            r["route_access"].extend(["transport-contact","supplied-fit-mount"])
            r["disposition"]={"loan":"One supplied fit mount","owner_id":npc_id,"term":"Return the mount at the landing when you finish using it.","source_action":action_id}
        elif service == "return_mount":
            require("supplied-fit-mount" in r["route_access"] and r["disposition"] and r["disposition"].get("owner_id") == npc_id, "There is no current mount loan to return.")
            r["route_access"].remove("supplied-fit-mount")
            state[npc_id]["private_state"]["resources"]["mount_loans"] += 1
            r["disposition"] = {"result":"Returned the mount to its owner at the landing.","source_action":action_id}
        _known(state)[npc_id] = {"statement": "The named person provides the stated "+service+" within its published scope.", "basis": "message", "source_action": action_id}
        summary = "Record the person's actual useful assistance and its stated costs."
    _update_deadline(state)
    if npc_decision:
        _guard_result(decision_before,state,*npc_decision,action_id,context)
    return _routine(state, summary, summary)


def available_choices(state):
    if _opening_active(state):
        return []
    r = _region(state)
    choices = []
    if r["opening"]["lesson"] is None and r["location_id"] in ("practice", "library") and _activity_fits(state,600,"study"):
        teacher="npc-mentor" if r["location_id"] == "practice" else "npc-asenne"
        if state[teacher]["willing"]:
            choices.append({"label": "Take a voluntary practical lesson.", "intent": {"verb": "region_choice", "choice_id": "lesson"}})
        choices.append({"label": "Use the curriculum library lesson.", "intent": {"verb": "region_choice", "choice_id": "library"}})
    if r["opening"]["peer"] is None and state["npc-peer"]["visible"]:
        for choice,label,seconds in (("peer.help","Help Lysa with ten minutes of practical work.",600),("peer.other","Introduce Lysa to another helper.",60),("peer.decline","Decline Lysa's optional request.",0)):
            if seconds == 0 or _activity_fits(state,seconds,"work"):
                choices.append({"label":label,"intent":{"verb":"region_choice","choice_id":choice}})
    if r["opening"]["service"] is None:
        for method,seconds in (("speed",300),("care",600),("consultation",1200)):
            if _activity_fits(state,seconds,"work"):
                choices.append({"label":"Complete the optional short service through "+method+".","intent":{"verb":"region_choice","choice_id":"service.method","method":method}})
    if r["assignment"]["status"] == "open" and _assignment_ready(state):
        choices.extend({"label": "Resolve the assignment through "+method+".", "intent": {"verb": "region_choice", "choice_id": "chapter.resolve", "method": method}} for method in ("care", "consultation")
                       if _activity_fits(state,600 if _chapter(state) in (4,9,10,11) else 3600 if method == "care" else 7200,"work"))
    if state["world"]["next_event_second"] is not None:
        choices.append({"label": "Wait towards the next scheduled project event.", "intent": {"verb": "region_event"}})
    for destination,(label,supplied) in LOCATIONS.items():
        if destination == r["location_id"]:
            continue
        seconds=600 if supplied and LOCATIONS[r["location_id"]][1] else 1200
        preview=state
        if not supplied:
            preview=deepcopy(state);preview["world"]["supplied"]=False
        if (supplied or state["pc"]["wounds"] < 3) and _activity_fits(state,seconds,"travel") and (supplied or can_supply_interval(preview,state["world"]["time_seconds"],state["world"]["time_seconds"]+seconds)):
            choices.append({"label":"Travel to "+label+".","intent":{"verb":"region_travel","destination":destination}})
    for npc_id,service in NPC_SERVICES.items():
        npc=state[npc_id]
        if not npc["visible"] or not npc["willing"] or (npc_id in _known(state) and service not in ("provisions","parallel")):
            continue
        if service == "provisions" and not (state["pc"]["silver"] >= 1 and state["pc"]["supply"] <= 4):
            continue
        if service == "parallel" and not (npc["support_remaining"] > 0 and state["pc"]["pending_work_seconds"] >= 600 and npc["private_state"]["resources"]["work_seconds"] >= 600 and _activity_fits(state,600,"wait")):
            continue
        if service == "transport" and npc["private_state"]["resources"]["mount_loans"] == 0:
            continue
        choices.append({"label":"Ask "+npc["name"]+" for "+service.replace("_"," ")+".","intent":{"verb":"npc_service","npc_id":npc_id,"service":service}})
    if r["location_id"] == "landing" and r["field_situation"] is None:
        if _activity_fits(state,600,"work"):
            choices.append({"label":"Report the optional road obstruction and leave its handling to staff.","intent":{"verb":"region_choice","choice_id":"field.report"}})
        if "foe-ordinary" in state and state["pc"]["wounds"] < 3:
            choices.append({"label":"Observe the optional dangerous road group; engagement remains a separate choice.","intent":{"verb":"region_choice","choice_id":"field.encounter"}})
            choices.append({'label':'Observe the optional experienced raider (Guard18, Resistance8, Harm3); engagement remains separate.','intent':{'verb':'region_choice','choice_id':'field.dangerous'}})
    if not state['world']['active_conflict']:
        for key in ('foe-ordinary','foe-dangerous'):
            target=state.get(key,{})
            if target.get('available') and target.get('alive') and not target.get('defeated') and target.get('location')==state['world']['location']:
                choices.append({'label':'Engage '+target['name'],'intent':{'verb':'combat','kind':'start','target_id':key}})
    if r["location_id"] == "landing" and "supplied-fit-mount" in r["route_access"]:
        choices.append({"label":"Return the borrowed mount to Deren.","intent":{"verb":"npc_service","npc_id":"npc-deren","service":"return_mount"}})
    return choices


def public_view(state):
    r = deepcopy(_region(state))
    r.update(deepcopy(state["region-memory"]))
    r["contract"] = chapter_proofs(_chapter(state))
    definition = ASSIGNMENTS.get(_chapter(state), ("Complete a new post-shawl service for its current beneficiaries.", "Check the result.", "Consult its beneficiaries."))
    r["assignment_definition"] = {"facts":definition[0],"care":definition[1],"consultation":definition[2],"lore_class":"invention","source":"regional.py:"+VERSION}
    r["choices"] = available_choices(state)
    r["projects"] = {key: deepcopy(state[key]) for key in PROJECTS}
    r["locations"] = {key:{"name":name,"institutional_provisions":supplied,"source":"genesis-staff-directory"} for key,(name,supplied) in LOCATIONS.items()}
    public_fields = ("name", "role", "location", "motive", "competences", "boundary", "bond", "support_remaining", "willing", "oaths_active", "vitality", "max_vitality", "wounds")
    return {"region": r, "npcs": {key: {field: deepcopy(state[key][field]) for field in public_fields} for key in NPCS}}
