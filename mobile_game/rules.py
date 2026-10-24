"""Bounded disposable episode using the notion-manual-v2 resolution rules.

This is a new authored sample, not an importer or a replacement for the complete
manual. No real campaign data belongs here. Storage owns action identifiers,
transactions and random generation; this module only computes a pure transition.
"""
from copy import deepcopy

RULES_EDITION = "notion-manual-v2"
EPISODE_ID = "courtyard-cover-disposable-v1"
MAX_INT = 2**53 - 1


def initial_state(episode_id=None):
    """Return independent complete sample state; setup ratings are test fixtures."""
    if episode_id is not None and episode_id != EPISODE_ID:
        from . import adventure, sandbox
        if episode_id == sandbox.EPISODE_ID:
            return sandbox.initial_state()
        if episode_id != adventure.EPISODE_ID:
            raise ValueError("Unknown disposable episode.")
        return adventure.initial_state()
    return {
        "schema": "mobile-disposable-state-v1", "rules_edition": RULES_EDITION,
        "disposable": True,
        "identity": {
            "name": "Elin QA", "age": 18, "gender": "woman", "origin": "Andor",
            "background": "village upbringing", "personal_aim": "learn useful skills",
            "oaths_active": False, "ajah": None, "dice_method": "server-random",
            "potential_visibility": "visible", "setup": "predetermined disposable fixture",
        },
        "attributes": {"body": 1, "grace": 2, "wits": 2, "will": 1, "presence": 0},
        "skills": {
            "athletics": 2, "melee": 0, "marksmanship": 0, "stealth": 0,
            "survival": 1, "notice": 1, "scholarship": 1, "medicine": 1,
            "persuasion": 0, "insight": 0, "leadership": 0, "composure": 2,
        },
        "rank": "novice", "level": 1,
        "resources": {
            "vitality": 8, "max_vitality": 8, "wounds": 0, "strain": 0,
            "supply": 4, "silver": 6,
            "inventory": ["novice whites", "cloak", "notebook", "water container"],
        },
        "channeling": {
            "potential": 9, "potential_source": "fixed disposable fixture; no generation roll",
            "current_capacity": 3, "control": 1,
            "flows": {"air": 2, "earth": 1, "fire": 1, "water": 1, "spirit": 1},
            "known_weaves": ["W01", "W02"], "embraced": False,
            "held_weaves": [], "tied_weaves": [], "pending_cast": None,
        },
        "clock": {
            "fictional_seconds": 32400,
            "calendar_anchor": {"year": "950 NE", "day": "Sample Day 1", "named_date": None},
            "day_activity_seconds": 0, "last_break_end": None,
            "last_full_rest_end": 32400, "first_aid_since_rest": [],
            "healing_since_rest": [], "exposed_days_charged": [],
            "wound_recovery_credit": 0, "follow_up_seconds": 0,
        },
        "progression": {
            "chapter": 1, "general_points": 0, "channel_points": 0,
            "chapter_evidence": [], "completed_chapters": [], "study": {},
        },
        "world": {
            "location": "White Tower garden arcade", "scene": "The approaching shower",
            "known_facts": [], "allies": [], "npcs": [], "projects": [],
            "commitments": [], "due_events": [], "threat_clocks": [], "conflict": None,
            "episode": {
                "id": EPISODE_ID, "stage": "invitation", "prepared": False,
                "result": None, "completed": False, "check_count": 0,
                "objective": "Bring the cover to the garden shelter, or choose another way to keep the reading group dry. This task is optional.",
            },
        },
        "unresolved_decisions": [],
    }


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, low=0, high=MAX_INT):
    return type(value) is int and low <= value <= high


def _validate(state):
    _need(type(state) is dict and state.get("disposable") is True,
          "Only the disposable sample is supported; campaign import is not available.")
    _need(state.get("rules_edition") == RULES_EDITION, "Unsupported rules edition.")
    episode = state.get("world", {}).get("episode", {})
    _need(episode.get("id") == EPISODE_ID, "Unsupported sample episode.")
    _need(episode.get("stage") in ("invitation", "planning", "fallback", "complete"), "Invalid episode stage.")
    _need(type(episode.get("prepared")) is bool and type(episode.get("completed")) is bool, "Invalid episode flags.")
    _need(episode["completed"] == (episode["stage"] == "complete"), "Conflicting episode completion.")
    _need(_integer(episode.get("check_count"), 0, 1), "Invalid sample check count.")
    clock = state.get("clock", {})
    _need(_integer(clock.get("fictional_seconds")), "Invalid fictional clock.")
    _need(_integer(clock.get("day_activity_seconds"), 0, 28800), "Invalid activity time.")
    _need(clock.get("last_break_end") is None or _integer(clock["last_break_end"], 0, clock["fictional_seconds"]), "Invalid break record.")
    for group, key, low, high in (("attributes", "grace", 0, 3), ("skills", "athletics", 0, 4)):
        _need(_integer(state.get(group, {}).get(key), low, high), "Invalid test ability.")
    resources = state.get("resources", {})
    _need(_integer(resources.get("max_vitality"), 6, 12), "Invalid maximum Vitality.")
    for key, maximum in (("vitality", resources["max_vitality"]), ("wounds", 3), ("strain", 6), ("supply", 6), ("silver", MAX_INT)):
        _need(_integer(resources.get(key), 0, maximum), "Invalid resource: " + key)


def _check(state):
    modifier = 2 if state["world"]["episode"]["prepared"] else 0
    return {"formula": "2d10 + Grace + Athletics + preparation",
            "attribute": "grace", "attribute_rating": state["attributes"]["grace"],
            "skill": "athletics", "skill_rating": state["skills"]["athletics"],
            "modifier": modifier, "difficulty": 14}


def _choice(identifier, label, description, stakes, requires_roll=False):
    return {"id": identifier, "label": label, "description": description,
            "stakes": stakes, "requires_roll": requires_roll}


def _choices(state):
    episode = state["world"]["episode"]
    stage = episode["stage"]
    if stage == "invitation":
        return [
            _choice("accept_task", "Fetch the cover", "Take responsibility for bringing the rolled canvas from the potting shed.", "Routine; 1 minute. No roll or resource cost. You can choose the route next."),
            _choice("move_inside", "Move the lesson under the arcade", "Offer a useful alternative: help the readers and their books into the covered space.", "Routine; 10 minutes. Completes the task by another method; no roll or resource cost."),
            _choice("decline_task", "Decline the optional task", "Leave the arrangement to the Accepted and return to your free interval.", "Routine; no fictional time or resource cost. Ends this optional episode without an award or penalty."),
        ]
    if stage == "planning":
        check = _check(state)
        bonus = check["attribute_rating"] + check["skill_rating"] + check["modifier"]
        choices = []
        if not episode["prepared"]:
            choices.append(_choice("prepare_grip", "Secure the carrying strap", "Take time to shorten the loose strap and test how the roll balances before crossing.", "Routine; 1 minute. Gives the single +2 preparation bonus on the crossing. No roll or resource cost; this cannot stack."))
        choices.extend([
            _choice("cross_courtyard", "Carry it across the courtyard", "Use the short route over rain-slick stones. The bulky roll makes balance uncertain.",
                    f"Roll 2d10 + Grace {check['attribute_rating']} + Athletics {check['skill_rating']} + preparation {check['modifier']} (total bonus +{bonus}); difficulty 14. Clean: total 14+; cover installed in 5 minutes, task complete. Costly: total 11–13; cover installed in 10 minutes, task complete. Setback: total 10 or less; spend 5 minutes recovering the snagged roll at the shed, then choose the covered route or assistance. No injury, lost resources or repeat crossing roll.", True),
            _choice("covered_route", "Take the covered route", "Carry the canvas through the longer arcade, avoiding the slippery courtyard.", "Routine; 15 minutes. Install the cover and complete the task. No roll, injury or resource cost."),
            _choice("move_inside", "Change plans and move the lesson inside", "Leave the canvas in the shed and help move the reading group under the arcade.", "Routine; 10 minutes. Completes the task by another method; no roll or resource cost."),
        ])
        return choices
    if stage == "fallback":
        return [
            _choice("covered_route", "Take the covered route", "The loose canvas is secure again. Carry it through the arcade and finish the job.", "Routine; 15 minutes. Install the cover and complete the task. No further roll or resource cost."),
            _choice("ask_porter", "Carry it with the gardener", "Ask the gardener at the shed to take the other end; you guide the roll through the covered passage together.", "Routine; 10 minutes. Install the cover and complete the task. No roll or resource cost."),
            _choice("move_inside", "Move the lesson under the arcade instead", "Choose the indoor alternative and leave the cover safely stored.", "Routine; 10 minutes. Completes the task by another method; no roll or resource cost."),
        ]
    choices = [_choice("quiet_interval", "Enjoy a quiet ten minutes", "Sit under the arcade with a drink and let the finished business stay finished.", "Routine; 10 minutes. No roll, recovery credit, reward or new obligation.")]
    clock = state["clock"]
    if clock["last_break_end"] is None or clock["fictional_seconds"] + 600 - clock["last_break_end"] >= 3600:
        choices.append(_choice("rest_break", "Take a recovery break", "Rest safely for ten minutes.", "Routine; 10 minutes. Restore up to 2 Vitality and remove up to 2 Strain. No Wound healing. Another restorative break must end at least one hour after this one."))
    return choices


def view(state):
    """Explicit public projection; unknown and private state never leak by default."""
    from . import adventure, sandbox
    if state.get("world", {}).get("episode", {}).get("id") == sandbox.EPISODE_ID:
        return sandbox.view(state)
    if state.get("world", {}).get("episode", {}).get("id") == adventure.EPISODE_ID:
        return adventure.view(state)
    _validate(state)
    episode = state["world"]["episode"]
    stories = {
        "invitation": "Rain patters against the garden wall. An Accepted supervising a small reading group points out a rolled canvas cover in the potting shed. ‘Would you bring that over, Elin? Or we can take the books under the arcade.’ The lesson is ordinary Tower work; you have room to choose a useful part in it.",
        "planning": "The canvas lies beside the open shed door. Across the courtyard, the garden shelter is waiting. The short path is slick with rain; the covered arcade is longer and dry. Bringing the cover over and fitting it will finish the errand.",
        "fallback": "The canvas caught on the shed's iron door hook as you turned. You have freed it without tearing it or getting hurt. The direct crossing is no longer the useful plan. The arcade remains clear, and the gardener can spare a hand.",
        "complete": "The episode is finished. The next interval is yours; there is no further inspection, extra qualification or new obligation attached to the task.",
    }
    if episode["stage"] == "complete":
        endings = {
            "cover_installed": "The canvas is secured over the garden shelter. The readers settle back onto the benches while rain taps harmlessly overhead. Your chosen task is complete.",
            "lesson_moved": "The last book is dry under the arcade. The reading group settles into its new places and the Accepted resumes the lesson. Your alternative worked; the task is complete.",
            "declined": "The Accepted accepts your answer and makes her own arrangements. You return to your free interval. The optional episode is closed, with no penalty.",
        }
        story = endings.get(episode["result"], stories["complete"])
    else:
        story = stories[episode["stage"]]
        if episode["prepared"]:
            story += " The carrying strap is secured; your preparation gives +2 if you choose the crossing."
    return {
        "title": "A shower in the Tower gardens", "episode_id": EPISODE_ID,
        "rules_edition": RULES_EDITION, "disposable": True,
        "character": {"name": state["identity"]["name"], "rank": state["rank"], "age": state["identity"]["age"]},
        "story": story, "objective": episode["objective"], "choices": _choices(state),
        "status": "complete" if episode["completed"] else "in_progress",
        "completed": episode["completed"], "result": episode["result"],
        "resources": {key: state["resources"][key] for key in ("vitality", "max_vitality", "wounds", "strain", "supply", "silver")},
        "fictional_seconds": state["clock"]["fictional_seconds"],
        "sample_notice": "Disposable authored episode; fixed character setup. No real campaign is loaded. This pilot does not yet support freeform campaign play or migration.",
    }


def _finish(state, result):
    episode = state["world"]["episode"]
    episode.update(stage="complete", completed=True, result=result)
    state["world"]["location"] = "White Tower garden arcade"
    state["world"]["scene"] = "A completed errand and a quiet interval"
    # One small task is not a whole chapter: no point, rank or level award.


def resolve(state, choice_id, dice=None):
    """Compute one available choice. Input state is never mutated, including on error."""
    from . import adventure, sandbox
    if state.get("world", {}).get("episode", {}).get("id") == sandbox.EPISODE_ID:
        return sandbox.resolve(state, choice_id, dice)
    if state.get("world", {}).get("episode", {}).get("id") == adventure.EPISODE_ID:
        return adventure.resolve(state, choice_id, dice)
    _validate(state)
    _need(type(choice_id) is str, "Choose a listed action.")
    choices = {choice["id"]: choice for choice in _choices(state)}
    _need(choice_id in choices, "This choice is unavailable in the current state.")
    choice = choices[choice_id]
    if choice["requires_roll"]:
        _need(type(dice) in (list, tuple) and len(dice) == 2 and all(_integer(d, 1, 10) for d in dice), "An uncertain action needs exactly two d10 results.")
    else:
        _need(dice is None or dice == [], "Routine actions do not use dice.")
    next_state = deepcopy(state)
    episode = next_state["world"]["episode"]
    seconds, roll = 0, None
    if choice_id == "accept_task":
        episode["stage"] = "planning"
        next_state["world"]["location"] = "White Tower potting shed"
        seconds = 60
        narration = "You reach the shed and find the cover ready to carry. No permission or further inspection is needed. The short wet path and the longer covered route are both open to you."
    elif choice_id == "prepare_grip":
        episode["prepared"] = True
        seconds = 60
        narration = "You shorten the strap and test the weight. The canvas sits securely against your shoulder. This preparation gives one +2 bonus if you use the courtyard route."
    elif choice_id == "cross_courtyard":
        roll = _check(state)
        roll["dice"] = list(dice)
        roll["total"] = sum(dice) + roll["attribute_rating"] + roll["skill_rating"] + roll["modifier"]
        gap = roll["difficulty"] - roll["total"]
        roll["outcome"] = "clean" if gap <= 0 else "costly" if gap <= 3 else "setback"
        episode["check_count"] += 1
        if roll["outcome"] == "clean":
            seconds = 300
            _finish(next_state, "cover_installed")
            narration = "You carry the canvas across the wet stones and fit it over the shelter. The last fastening holds as the shower strengthens. The readers have their dry place, and your task is finished."
        elif roll["outcome"] == "costly":
            seconds = 600
            _finish(next_state, "cover_installed")
            narration = "You stop twice to regain your footing and shift the awkward roll. It takes five minutes longer than the direct crossing should have, but you bring it over intact and secure the shelter. The task is finished; there is no additional cost."
        else:
            seconds = 300
            episode["stage"] = "fallback"
            narration = "The trailing fold catches on the shed's iron hook as you turn. Freeing it safely uses five minutes. The canvas is intact and you are unhurt. The gardener is now beside the doorway, and the dry arcade offers a clear way to finish without another crossing test."
    elif choice_id in ("covered_route", "ask_porter"):
        seconds = 900 if choice_id == "covered_route" else 600
        _finish(next_state, "cover_installed")
        narration = ("You carry the roll through the dry arcade" if choice_id == "covered_route" else "The gardener takes the other end while you guide the roll through the arcade") + ", then secure the canvas over the garden shelter. The reading group stays dry. That completes the task; nobody adds another errand."
    elif choice_id == "move_inside":
        seconds = 600
        _finish(next_state, "lesson_moved")
        narration = "You help carry the books and arrange a dry place beneath the arcade. The group moves with you; the canvas can stay in the shed. The Accepted resumes the lesson. Your alternative has completed the task."
    elif choice_id == "decline_task":
        _finish(next_state, "declined")
        narration = "The Accepted acknowledges your decision and makes her own arrangements. The request was optional. You return to your free interval with no lost resources, extra duty or hidden penalty."
    elif choice_id == "quiet_interval":
        seconds = 600
        narration = "You settle under the arcade with a drink. Rain makes a soft, steady sound in the garden. Ten quiet minutes pass, and the completed episode stays complete."
    elif choice_id == "rest_break":
        seconds = 600
        resources = next_state["resources"]
        resources["vitality"] = min(resources["max_vitality"], resources["vitality"] + 2)
        resources["strain"] = max(0, resources["strain"] - 2)
        next_state["clock"]["last_break_end"] = state["clock"]["fictional_seconds"] + seconds
        narration = "You take ten minutes of safe recovery. The break restores up to two Vitality and removes up to two Strain, within their limits. It creates no new task and does not heal a Wound."
    else:
        raise ValueError("Unsupported action.")
    start = state["clock"]["fictional_seconds"]
    _need(start + seconds <= MAX_INT, "Fictional clock limit reached.")
    next_state["clock"]["fictional_seconds"] = start + seconds
    if start // 86400 != (start + seconds) // 86400:
        next_state["clock"]["day_activity_seconds"] = 0
    _validate(next_state)
    return {"state": next_state, "narration": narration, "roll": roll, "elapsed_seconds": seconds}
