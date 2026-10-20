"""Authored initial-six Tower episode, not a general fiction generator.

All people, events, and adjudication choices are campaign inventions. Teacher
statements use the typed Oaths module with authored meanings and sourced actor
evidence. This episode is not an unrestricted prose classifier or player pilot.
Legacy states without ``world.episode`` remain untouched.
"""
from copy import deepcopy

from .contracts import ContractError

EPISODE_ID = "tower-inventory-v1"


class StoryError(ContractError):
    pass


def require(condition, message):
    if not condition:
        raise StoryError(message)


def initialize(state):
    """Add original public scene state only during new campaign creation."""
    w = state["world"]
    state["pc"]["warning_ready"] = False
    w.update({
        "episode": {
            "id": EPISODE_ID, "phase": "invitation", "mentor_choice": "unanswered",
            "peer_choice": "unanswered", "steward_choice": "unanswered",
            "lesson_complete": False, "lesson_source": None,
            "inspection_attempted": False, "inventory_complete": False,
            "inventory_method": None, "peer_help_used": False,
            "hazard_resolved": False, "hazard_choice": None,
            "ledger_condition": "sound", "handoff_complete": False,
            "credit_choice": None, "training_baseline": None, "training_course": None, "training_seconds": 0,
        },
        "event_queue": [], "last_event": None, "last_oath_result": None,
    })
    for npc_id in ("npc-mentor", "npc-peer", "npc-steward"):
        npc = state[npc_id]
        npc["oaths_active"] = npc_id == "npc-mentor"
        npc["oaths_source_event"] = "genesis" if npc["oaths_active"] else None
        npc["beliefs"] = [
            {"belief_id": "mentor-lesson-belief", "proposition_id": "voluntary-lesson",
             "value": True, "evidence_ids": ["lesson-policy"]},
            {"belief_id": "mentor-library-belief", "proposition_id": "library-offers-lesson",
             "value": True, "evidence_ids": ["library-notice"]},
        ] if npc_id == "npc-mentor" else []
        npc["evidence"] = [
            {"evidence_id": "lesson-policy", "basis": "observation",
             "statement": "This lesson concerns safe practice.", "source_event": "genesis", "audience_ids": ["npc-mentor"]},
            {"evidence_id": "library-notice", "basis": "observation",
             "statement": "The curriculum library offers this lesson as well.", "source_event": "genesis", "audience_ids": ["npc-mentor"]},
        ] if npc_id == "npc-mentor" else []
        if npc_id == "npc-mentor":
            npc["private_oath_ruling"] = None
    refresh(state)


def _choice(choice_id, label, **intent):
    return {"id": choice_id, "label": label,
            "intent": intent or {"verb": "choose", "choice_id": choice_id}}


def refresh(state):
    """Derive available public choices; never invent a world event or advance time."""
    w, p = state["world"], state["pc"]
    e = w.get("episode")
    if e is None:
        return
    require(e["id"] == EPISODE_ID, "Unsupported authored episode version.")
    phase = e["phase"]
    choices = []
    if phase in ("invitation", "service"):
        if e["mentor_choice"] == "unanswered" and not e["lesson_complete"]:
            choices += [_choice("mentor.lesson", "Accept Maerin's ten-minute lesson."),
                        _choice("mentor.decline", "Decline Maerin's lesson; use the library instead.")]
        if e["peer_choice"] == "unanswered":
            choices += [_choice("peer.partner", "Work with Lysa and promise to credit her actual contribution."),
                        _choice("peer.decline", "Decline Lysa's partnership and work independently.")]
        if (e["steward_choice"] == "unanswered"
                and state["npc-steward"]["location"] == w["location"]):
            choices += [_choice("steward.accept", "Accept Toman's request for an accurate inventory handoff."),
                        _choice("steward.decline", "Decline Toman's personal request; the public service task stays available.")]
        if not e["lesson_complete"]:
            choices.append(_choice("library.lesson", "Take the same ten-minute lesson from the curriculum library."))
    if phase == "invitation":
        w["scene_id"] = "tower-inventory-invitation"
        w["scene_description"] = (
            "Prepared tinder and a practice latch stand beside a stack of empty wooden crates. "
            "Maerin offers instruction, Lysa offers partnership, and Toman requests help checking the inventory. "
            "Their offers are optional. Complete a lesson and light the prepared tinder before starting service."
        )
        if not p["embraced"]:
            choices.append(_choice("practice.embrace", "Embrace the Source for the prepared-tinder exercise.", verb="embrace"))
        elif not state["obj-tinder"]["lit"]:
            choices.append(_choice("practice.spark", "Use Spark on the prepared tinder.", verb="cast", weave_id="W01", target_id="obj-tinder"))
        if e["lesson_complete"] and state["obj-tinder"]["lit"]:
            choices.append(_choice("service.begin", "Begin the inventory task. Toman returns through the doorway in fifteen minutes."))
    elif phase == "service":
        w["scene_id"] = "tower-inventory-service"
        w["scene_description"] = (
            "Check the inventory before Toman returns. A quick inspection can settle the count. "
            "A routine count takes ten minutes alone or five with Lysa's available help. "
            "The scheduled return remains visible; stop for it before crossing that time boundary."
        )
        if ("W04" in p["known_weaves"] and p["control"] >= 2 and p["flows"]["spirit"] >= 2
                and p["embraced"] and p["strain"]+2 <= 2*p["capacity"]
                and len(p["held"]) < p["control"] and sum(x["load"] for x in p["held"]+p["tied"])+2 <= p["capacity"]
                and not any(x["weave_id"] == "W04" and x["target_id"] == "world" for x in p["held"]+p["tied"])):
            choices.append(_choice("practice.ward", "Place Warning Ward across the marked doorway.", verb="cast", weave_id="W04", target_id="world", area_metres=2))
        if not e["inventory_complete"]:
            if not e["inspection_attempted"]:
                choices.append(_choice("service.inspect", "Try a ten-second Notice check; a costly result or setback adds ten minutes of follow-up work."))
            if p["pending_work_seconds"] == 0:
                choices.append(_choice("service.count", "Complete a routine inventory count with the available help."))
        choices.append(_choice("event.wait", "Wait to Toman's scheduled return and resolve that event.", verb="advance_event"))
    elif phase == "hazard":
        w["scene_id"] = "tower-inventory-hazard"
        w["scene_description"] = (
            "The doorway opens. A cart clips the stack, and an empty crate tips towards the work area. "
            "You have time for one response. Steady it, step clear, or call staff and accept a delay."
        )
        if p["wounds"] < 3:
            choices += [_choice("danger.steady", "Try to steady the crate: Body + Athletics, difficulty 14; possible Harm 2."),
                        _choice("danger.escape", "Step clear: Grace + Athletics, difficulty 14; the Ward can give +2; possible Harm 2.")]
        choices.append(_choice("danger.call_staff", "Call staff and withdraw safely. Resolving the disruption takes ten minutes."))
    elif phase == "debrief":
        w["scene_id"] = "tower-inventory-debrief"
        w["scene_description"] = (
            "The crate is no longer a threat. Finish any inventory work and hand over an accurate record. "
            "Then decide how to describe the contributions. Completed lessons and study remain yours."
        )
        if not e["inventory_complete"] and p["pending_work_seconds"] == 0:
            choices.append(_choice("service.count", "Finish the routine inventory count."))
        if e["inventory_complete"] and not e["handoff_complete"] and p["pending_work_seconds"] == 0:
            choices.append(_choice("service.handoff", "Hand over the accurate inventory and report the disruption."))
        if e["handoff_complete"] and e["credit_choice"] is None:
            choices.append(_choice("debrief.credit", "Credit the work each person actually completed."))
            if e["peer_help_used"]:
                choices.append(_choice("debrief.sole", "Claim sole credit despite Lysa's contribution; this breaks your promise."))
    elif phase == "training":
        w["scene_id"] = "tower-inventory-training"
        baseline, course = e["training_baseline"], e["training_course"]
        if course is not None:
            e["training_seconds"] = max(0, p["study_progress"].get(course, 0)-baseline)
        w["scene_description"] = (
            "The inventory is handed over. Record a one-hour foundation study period to close this opening episode. "
            "This is partial curriculum progress. It does not grant a level, rank, or chapter reward."
        )
        remaining = max(0, 3600-e["training_seconds"])
        if remaining:
            if course is None:
                choices.append(_choice("training.review", "Review mastered foundation work for one hour without new mastery credit."))
            else:
                day = str(w["time_seconds"]//86400)
                prior = w["main_activity"].get(day, {"kind": "study", "seconds": 0})
                free = max(0, 28800-prior["seconds"]) if prior["kind"] == "study" else 0
                seconds = min(remaining, free, 86400-w["time_seconds"]%86400)
                if seconds:
                    choices.append(_choice("training.study", "Record the next available foundation study block.",
                                           verb="study", course_id=course, seconds=seconds))
                else:
                    choices.append(_choice("training.wait", "Wait towards the next calendar day; this gives no training credit.",
                                           verb="wait", seconds=min(28800, 86400-w["time_seconds"]%86400)))
        else:
            choices.append(_choice("episode.finish", "Close the episode with the saved lesson, service, choice and training record."))
    elif phase == "complete":
        w["scene_id"] = "tower-inventory-complete"
        w["scene_description"] = (
            "The opening episode is complete. Your lesson, inventory method, response, relationships and study time are recorded. "
            "The next chapter is not implemented in this initial-six release."
        )
    else:
        raise StoryError("Unknown episode phase.")
    if p["held"] or p["embraced"]:
        choices.append(_choice("practice.release", "Release held weaves and the Source.", verb="release"))
    if p["pending_work_seconds"] and not w["active_conflict"]:
        seconds = min(p["pending_work_seconds"], 28800)
        deadline = w["next_event_second"]
        if deadline is not None:
            seconds = min(seconds, max(0, deadline-w["time_seconds"]-1))
        if seconds:
            choices.append(_choice("followup.work", "Complete the next available block of declared follow-up work.", verb="workoff", seconds=seconds))
    if w["safe"] and not p["held"] and (not p["pending_work_seconds"] or p["vitality"] == 0) and w["next_event_second"] is None:
        choices.append(_choice("recovery.rest", "Take a full safe rest. Existing Wounds and unfinished obligations remain.", verb="rest", kind="full"))
    if p["vitality"] == 0:
        choices = [x for x in choices if x["intent"]["verb"] == "rest"]
    w["choices"] = choices


def _oath_ruling(state, statement_id):
    """Only fixed, truthful-intent teacher lines; do not infer unseen beliefs."""
    actor = state["npc-mentor"]
    require(type(actor.get("oaths_active")) is bool, "Teacher Oaths status is missing.")
    statements = {
        "lesson": ("This lesson concerns safe practice.", "voluntary-lesson"),
        "decline": ("The curriculum library offers this lesson as well.", "library-offers-lesson"),
    }
    require(statement_id in statements, "Unreviewed teacher statement.")
    statement, proposition_id = statements[statement_id]
    from .oaths import adjudicate, public_view
    ruling = adjudicate({
        "actor_id": "npc-mentor", "oaths_active": actor["oaths_active"],
        "oaths_source_event": actor["oaths_source_event"],
        "beliefs": deepcopy(actor["beliefs"]), "evidence": deepcopy(actor["evidence"]),
    }, {
        "proposal_id": "teacher-"+statement_id, "kind": "speech", "statement_or_action": statement,
        "intent": "Explain the safe scope or available alternative for this voluntary lesson.",
        "details": {"speech_act": "statement", "proposition_id": proposition_id,
                    "assertion": True, "literal_credible": True},
    })
    require(ruling["result"] == "ALLOW", ruling["public_reason"])
    actor["private_oath_ruling"] = ruling
    state["world"]["last_oath_result"] = public_view(ruling)
    return statement


def _partner(state):
    e, ally = state["world"]["episode"], state["npc-peer"]
    return (e["peer_choice"] == "accepted" and ally["willing"]
            and ally["location"] == state["world"]["location"] and ally["support_remaining"] > 0)


def _use_partner(state):
    state["npc-peer"]["support_remaining"] -= 1
    state["world"]["episode"]["peer_help_used"] = True


def _routine(state, goal, method, summary):
    return None, {band: deepcopy(state) for band in ("clean", "costly", "setback")}, goal, method, dict.fromkeys(("clean", "costly", "setback"), summary)


def resolve(state, intent, action_id, *, advance, check, harm):
    """Mutate a private action copy; return frozen branch states and prose."""
    w, p = state["world"], state["pc"]
    e = w.get("episode")
    require(e is not None and e["id"] == EPISODE_ID, "This save has no authored Tower episode. Start a fresh G2 campaign.")
    require(p["vitality"] > 0, "Recover before making an episode choice.")
    if intent["verb"] == "advance_event":
        require(set(intent) == {"verb"}, "advance_event takes no extra fields.")
        require(e["phase"] == "service" and len(w["event_queue"]) == 1, "No authored event is pending.")
        event = w["event_queue"][0]
        require(event["event_id"] == "steward-doorway-return" and event["due_second"] == w["next_event_second"], "Invalid authored event boundary.")
        seconds = event["due_second"]-w["time_seconds"]
        require(0 <= seconds <= 28800, "Event is outside the supported time interval.")
        advance(state, seconds, allow_boundary=True)
        # Expiry runs before crossing. A weave expiring at this second cannot warn.
        warned = any(x["weave_id"] == "W04" and x["target_id"] == "world"
                     for x in p["held"]+p["tied"])
        p["warning_ready"] = warned
        w["last_event"] = {
            "event_id": event["event_id"], "at_second": w["time_seconds"], "kind": "physical-boundary-crossing",
            "ward_alert": "A physical creature crossed the ward boundary." if warned else None,
            "description": "The doorway opens. A cart catches an empty crate, which tips towards the work area.",
        }
        w["event_queue"] = []
        w["next_event_second"] = None
        w["active_conflict"], w["safe"] = True, False
        state["npc-steward"].update(location=w["location"], distance_m=0, visible=True)
        e["phase"] = "hazard"
        summary = "The doorway crossing triggers your Warning Ward. A crate tips; choose your response." if warned else "A crate tips as the doorway opens. Choose your response."
        return _routine(state, "Resolve the scheduled doorway crossing.", "Wait only to the published boundary; then stop for a decision.", summary)
    require(intent["verb"] == "choose" and set(intent) == {"verb", "choice_id"}, "A choice needs only verb and choice_id.")
    choice = intent["choice_id"]
    require(type(choice) is str, "choice_id must be text.")
    available = {x["id"] for x in w["choices"] if x["intent"].get("verb") == "choose"}
    require(choice in available, "That choice is not available in the current scene.")
    if choice in ("mentor.lesson", "library.lesson"):
        require(not w["active_conflict"] and p["pending_work_seconds"] == 0, "Finish the immediate situation and follow-up work before the lesson.")
        if choice == "mentor.lesson":
            require(state["npc-mentor"]["willing"], "The appointed tutor is unavailable; use the library.")
            statement = _oath_ruling(state, "lesson")
            e["mentor_choice"] = "accepted"
        else:
            require(w["library_available"], "The library is unavailable; the tutor remains an alternative.")
            statement = "The library's prepared lesson covers the same safe technique."
        advance(state, 600)
        e["lesson_complete"], e["lesson_source"] = True, choice
        return _routine(state, "Complete the safe-practice lesson.", "Ten minutes of instruction; the separate Spark exercise still costs its normal action and Strain.", statement)
    if choice == "mentor.decline":
        statement = _oath_ruling(state, "decline")
        e["mentor_choice"] = "declined"
        return _routine(state, "Decline the tutor's personal offer.", "Required instruction remains available through the library. No trust or rank penalty applies.", statement)
    if choice in ("peer.partner", "peer.decline", "steward.accept", "steward.decline"):
        peer = choice.startswith("peer")
        key = "peer_choice" if peer else "steward_choice"
        e[key] = "accepted" if choice.endswith(("partner", "accept")) else "declined"
        summary = {
            "peer.partner": "Lysa agrees to help when a useful task arises. You promise to credit her actual work.",
            "peer.decline": "Lysa accepts your decision and returns to her own work. The solo route remains open.",
            "steward.accept": "Toman asks for an accurate handoff. You accept that commitment.",
            "steward.decline": "Toman accepts your refusal. The same public service notice remains available without a personal promise.",
        }[choice]
        return _routine(state, "Respond to the offer.", "Acceptance records a specific commitment. Declining spends no resource and closes no training route.", summary)
    if choice == "service.begin":
        require(e["lesson_complete"] and state["obj-tinder"]["lit"], "Complete the lesson and prepared-tinder exercise first.")
        e["phase"] = "service"
        due = w["time_seconds"]+900
        w["event_queue"] = [{"event_id": "steward-doorway-return", "due_second": due}]
        w["next_event_second"] = due
        state["npc-steward"].update(location="Tower corridor", distance_m=15, visible=False)
        return _routine(state, "Begin the inventory service task.", "Toman returns in exactly 900 seconds. An action cannot silently cross that boundary.", "The inventory task begins. Toman leaves to collect the cart.")
    if choice == "service.count":
        require(p["pending_work_seconds"] == 0, "Complete declared follow-up work before the routine count.")
        partnered = _partner(state)
        seconds = 300 if partnered else 600
        if partnered:
            _use_partner(state)
        advance(state, seconds)
        e["inventory_complete"], e["inventory_method"] = True, "partner count" if partnered else "solo count"
        return _routine(state, "Complete the inventory by routine counting.", f"The count takes {seconds} seconds. It requires no roll and grants no advancement points.", "The checked inventory is ready for handoff.")
    if choice == "service.inspect":
        e["inspection_attempted"] = True
        test = check(p, "wits", "notice", 14)
        if _partner(state) and test["modifier"] == 0:
            _use_partner(state)
            test["modifier"] = 2
        advance(state, 10)
        outcomes = {}
        for band in ("clean", "costly", "setback"):
            result = deepcopy(state)
            if band != "setback":
                result["world"]["episode"].update(inventory_complete=True, inventory_method="inspection")
            if band != "clean":
                result["pc"]["pending_work_seconds"] += 600
            outcomes[band] = result
        return test, outcomes, "Inspect the inventory quickly.", "Use Wits + Notice. On a costly result or setback, record 600 seconds of follow-up work.", {
            "clean": "You verify the inventory. It is ready for handoff.",
            "costly": "You verify the inventory and must spend ten minutes recording the discrepancy.",
            "setback": "The quick inspection cannot settle the count. Record ten minutes of follow-up work; routine counting remains available.",
        }
    if choice.startswith("danger."):
        require(e["phase"] == "hazard", "There is no active crate hazard.")
        if choice == "danger.call_staff":
            advance(state, 600)
            e.update(phase="debrief", hazard_resolved=True, hazard_choice="call_staff", ledger_condition="delayed")
            w["active_conflict"], w["safe"] = False, True
            p["warning_ready"] = False
            return _routine(state, "Withdraw and call staff.", "Staff stop the cart and clear the crate. The disruption takes 600 seconds; there is no roll or harm.", "You withdraw safely. Staff clear the obstruction, and work can resume.")
        escape = choice == "danger.escape"
        require(escape or choice == "danger.steady", "Unsupported hazard response.")
        test = check(p, "grace" if escape else "body", "athletics", 14)
        if escape and p["warning_ready"]:
            test["modifier"] = 2  # It never stacks with another +2.
        p["warning_ready"] = False
        advance(state, 10)
        outcomes = {}
        for band in ("clean", "costly", "setback"):
            result = deepcopy(state)
            ep = result["world"]["episode"]
            ep.update(phase="debrief", hazard_resolved=True, hazard_choice="escape" if escape else "steady")
            result["world"]["active_conflict"], result["world"]["safe"] = False, True
            if band != "clean":
                harm(result, 2, "debris", "drop")
            if escape or band == "setback":
                ep["ledger_condition"] = "scattered"
                result["pc"]["pending_work_seconds"] += 600
            outcomes[band] = result
        summaries = ({
            "clean": "You step clear without injury. Gathering the scattered papers takes ten minutes.",
            "costly": "You get clear but take Harm 2 before protection. Gathering the papers takes ten minutes.",
            "setback": "The crate catches you: Harm 2 before protection. Staff end the hazard; gathering the papers takes ten minutes.",
        } if escape else {
            "clean": "You steady the empty crate. Nobody is hurt and the papers remain in order.",
            "costly": "You steady the crate but take Harm 2 before protection. The papers remain in order.",
            "setback": "You take Harm 2 before protection. Staff end the hazard; gathering the papers takes ten minutes.",
        })
        return test, outcomes, "Step clear of the crate." if escape else "Try to steady the crate.", "One ten-second response. Harm, protection, incapacitation and concentration resolve together; defeat never removes rank eligibility.", summaries
    if choice == "service.handoff":
        require(e["inventory_complete"] and e["hazard_resolved"] and p["pending_work_seconds"] == 0,
                "Finish the inventory, hazard and declared follow-up work before handoff.")
        advance(state, 60)
        e["handoff_complete"] = True
        if e["steward_choice"] == "accepted":
            state["npc-steward"]["bond"] = min(3, state["npc-steward"]["bond"]+1)
        return _routine(state, "Hand over the accurate inventory.", "One minute completes the task. A kept personal commitment raises Toman's trust by at most one; no rank gate changes.", "Toman accepts the inventory and your report of the disruption.")
    if choice in ("debrief.credit", "debrief.sole"):
        e["credit_choice"] = "accurate" if choice == "debrief.credit" else "sole"
        if e["peer_help_used"]:
            change = 1 if choice == "debrief.credit" else -1
            state["npc-peer"]["bond"] = min(3, max(0, state["npc-peer"]["bond"]+change))
        e["phase"] = "training"
        e["training_course"] = next((f"N{i:02d}" for i in range(1, 11)
                                     if p["study_progress"].get(f"N{i:02d}", 0) <= 4*28800-3600), None)
        e["training_baseline"] = p["study_progress"].get(e["training_course"], 0)
        return _routine(state, "Give your account of the work.", "Only the distinct kept or broken credit commitment changes Lysa's trust. All completed training remains available.", "Your account is recorded. A one-hour foundation study period remains before the episode closes.")
    if choice == "training.review":
        require(not p["embraced"] and not p["held"] and p["pending_work_seconds"] == 0, "Release the Source and finish follow-up work before review.")
        day = str(w["time_seconds"]//86400)
        prior = w["main_activity"].get(day, {"kind": "study", "seconds": 0})
        require(prior["kind"] == "study" and prior["seconds"]+3600 <= 28800, "The day's main study activity is already allocated.")
        require(w["time_seconds"]%86400+3600 <= 86400, "Start this review in a day with one full hour available.")
        w["main_activity"][day] = {"kind": "study", "seconds": prior["seconds"]+3600}
        advance(state, 3600)
        e["training_seconds"] = 3600
        return _routine(state, "Review mastered foundation work.", "One hour of study uses the day's main activity allowance and grants no repeated mastery or points.", "The foundation review is recorded. The episode can close.")
    if choice == "episode.finish":
        require(e["handoff_complete"] and e["training_seconds"] >= 3600, "Complete the handoff and recorded training first.")
        e["phase"] = "complete"
        return _routine(state, "Close the opening episode.", "Record completion only. No level, rank, capacity or learning opportunity is awarded.", "The opening episode closes with your choices and progress saved.")
    raise StoryError("Unknown authored choice.")
