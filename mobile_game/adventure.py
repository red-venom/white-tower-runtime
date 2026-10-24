"""The Letter in the Gallery: an original, disposable, branching Tower episode.

All scenario facts are authored in advance. No secret player-history imports.
Typed input is a conservative local interpreter, not a general language model.
"""
from copy import deepcopy
import re

from .channeling import WEAVES, safe_cast

EPISODE_ID = "gallery-letter-v1"
TITLE = "The Letter in the Gallery"


def initial_state():
    from . import rules
    state = rules.initial_state()
    state["world"].update(location="White Tower practice gallery", scene=TITLE,
                          known_facts=[], commitments=[], npcs=[
        {"id": "lysa", "name": "Lysa", "role": "Novice", "known": "Your classmate. She has just received a letter from home.", "memories": []},
        {"id": "maerin", "name": "Maerin Sedai", "role": "Aes Sedai tutor", "known": "Tutor for elementary practice in this gallery. She expects careful methods, not displays of strength.", "memories": []},
    ])
    state["world"]["episode"] = {
        "id": EPISODE_ID, "stage": "arrival", "completed": False, "result": None,
        "asked": False, "prepared": False, "pole_tried": False, "reflection": False,
        "spark_practised": False, "theory_minutes": 0,
        "lesson_ends_at": 39600,
        "objective": "Decide whether and how to help Lysa recover her unopened letter. A completed recovery ends the task; further practice is optional.",
        "evidence": [], "last_cast": None,
    }
    return state


def validate(state):
    from .rules import _integer
    e = state["world"]["episode"]
    if state.get("disposable") is not True or state.get("rules_edition") != "notion-manual-v2" or e["id"] != EPISODE_ID:
        raise ValueError("Only the authored disposable adventure is supported.")
    if e["stage"] not in ("arrival", "search", "complete") or e["completed"] != (e["stage"] == "complete"):
        raise ValueError("Inconsistent adventure stage.")
    for key in ("asked", "prepared", "pole_tried", "reflection", "spark_practised", "completed"):
        if type(e[key]) is not bool:
            raise ValueError("Invalid adventure flag.")
    c, r = state["channeling"], state["resources"]
    for value, low, high in ((c["current_capacity"], 1, 10), (c["potential"], c["current_capacity"], 10),
                              (c["control"], 1, 4), (r["strain"], 0, 2*c["current_capacity"]),
                              (r["vitality"], 0, r["max_vitality"]), (r["wounds"], 0, 3),
                              (state["clock"]["fictional_seconds"], 0, 2**53-1),
                              (state["clock"]["day_activity_seconds"], 0, 28800)):
        if not _integer(value, low, high):
            raise ValueError("Invalid saved character or clock.")
    if e["theory_minutes"] not in (0, 20):
        raise ValueError("Invalid lesson progress.")


def _choice(id, label, description, stakes, roll=False):
    return {"id": id, "label": label, "description": description, "stakes": stakes, "requires_roll": roll}


def _can_cast(state, id):
    try:
        _, receipt = safe_cast(state, id, supervised=True, range_paces=4, weight_kg=.05, dry_fuel=True)
        return state["clock"]["fictional_seconds"] + receipt["elapsed_seconds"] <= state["world"]["episode"].get("lesson_ends_at", 39600)
    except ValueError:
        return False


def choices(state):
    validate(state)
    e, out = state["world"]["episode"], []
    if e["stage"] == "arrival":
        if not e["asked"]:
            out.append(_choice("ask_lysa", "Ask Lysa what happened", "Hear her account before deciding what to do.", "1 minute; no roll or resource cost. You choose your own words."))
        out.append(_choice("look_gallery", "Look around the gallery", "Follow the obvious places a loose envelope could have gone.", "1 minute; ordinary observation succeeds. No roll."))
        out.append(_choice("decline_letter", "Leave the search to Lysa", "You can decline this personal request without losing standing or progress.", "No time, resource cost or penalty. Ends the optional task."))
    elif e["stage"] == "search":
        if _can_cast(state, "W02"):
            out.append(_choice("air_letter", "Guide the letter down with Air", "Under Maerin Sedai's supervision, use your known Air Hand on the visible envelope, then release the working.", "Safe routine use; no roll. 1 Strain, at most 20 seconds. Return the letter unopened; task complete."))
        if not e["pole_tried"]:
            if not e["prepared"]:
                out.append(_choice("prepare_hook", "Pad the hook before reaching", "Wrap the curtain hook in a cloth so it will not catch the paper.", "1 minute; one +2 preparation bonus. No roll or stacking."))
            bonus = state["attributes"]["grace"] + state["skills"]["athletics"] + (2 if e["prepared"] else 0)
            out.append(_choice("hook_letter", "Retrieve it with the curtain hook", "Reach from the floor, easing the paper off the grille without tearing it.",
                f"2d10 + Grace + Athletics + preparation = dice + {bonus}; difficulty 14. Clean: 2 minutes, returned unopened. Costly (11–13): 5 minutes, creased envelope, contents intact. Setback (10 or less): 2 minutes, letter slips to a visible dry ledge; use Air or the porter, with no repeat roll.", True))
        out.append(_choice("ask_porter", "Ask the porter to lower the screen", "Wait while the nearby porter safely releases its fastenings. No ladder or channeling is required.", "6 minutes; no roll or resource cost. Return the letter unopened; task complete."))
    else:
        if not e["reflection"] and state["clock"]["fictional_seconds"] + 180 <= e.get("lesson_ends_at", 39600):
            out.append(_choice("talk_after", "Stay for a quiet conversation", "Give Lysa room to speak, without asking to read her private letter.", "3 minutes; no roll. No promise or feeling is chosen for your character."))
        if not e["spark_practised"] and _can_cast(state, "W01"):
            out.append(_choice("practise_spark", "Practise a small flame", "Maerin Sedai offers a supervised candle exercise at the stone practice table.", "Known Spark; 1 Strain, at most 20 seconds. Safe practice needs no roll. Records practice; grants no new weave or points."))
        if not e["theory_minutes"] and state["clock"]["fictional_seconds"] + 1200 <= e.get("lesson_ends_at", 39600):
            out.append(_choice("study_block", "Study until the short lesson ends", "Review handling and release for twenty uninterrupted minutes with Maerin Sedai.", "20 minutes, resolved together. Theory only: no Strain, cast, new weave or advancement points."))
        out.append(_choice("quiet_interval", "Enjoy ten quiet minutes", "Let the finished business stay finished.", "10 minutes; no roll, reward or new obligation."))
    clock = state["clock"]
    if state["resources"]["strain"] or state["resources"]["vitality"] < state["resources"]["max_vitality"]:
        if clock["last_break_end"] is None or clock["fictional_seconds"] + 600 - clock["last_break_end"] >= 3600:
            out.append(_choice("rest_break", "Take a recovery break", "Rest safely in the gallery.", "10 minutes; restore up to 2 Vitality and remove up to 2 Strain. No Wound healing. Recovery cooldown applies."))
    if state["channeling"]["embraced"] or state["channeling"]["held_weaves"]:
        out.append(_choice("release_source", "Release the Source", "Let your held workings go.", "Free; held weaves end. Previously spent Strain is not refunded."))
    # A full activity day does not prevent free actions or recovery.
    if clock["day_activity_seconds"] >= 28800:
        out = [c for c in out if c["id"] in ("rest_break", "quiet_interval", "release_source", "decline_letter")]
    return out


def view(state):
    validate(state)
    e = state["world"]["episode"]
    if e["stage"] == "arrival":
        story = "Lysa has spread her notebook, cloak and empty writing case across a gallery bench. She checks the case once more, then closes it too carefully. ‘A letter from my mother. I had it a moment ago.’\n\nAt the practice table, Maerin Sedai sets a candle into its holder. ‘We have time to look before the lesson.’ An open window stirs the edge of Lysa's cloak. Nobody has accused anyone of taking anything."
    elif e["stage"] == "search":
        story = "The pale corner of an envelope shows against the inner window grille, four paces away. Its seal is intact. A curtain hook and a clean cloth lie beside the bench. The porter is working at the far end of the gallery.\n\nMaerin Sedai follows your glance. ‘A small enough task for the form you know. Slowly, if you use it; I will watch.’ Lysa waits beside the bench, her hands still."
        if e["pole_tried"]:
            story = "The envelope now rests on the dry ledge below the grille, still visible and within four paces. Trying the hook again would not improve the method. Maerin Sedai remains beside you, and the porter can lower the screen."
    elif e["result"] == "declined":
        story = "Lysa asks the porter for help with her search. Maerin Sedai turns back to the practice table. Your decision has brought no penalty; the optional request is closed. The rest of your interval is your own."
    else:
        story = "Lysa has her letter back, its seal unbroken. She folds it into her notebook instead of leaving it loose. The window screen is secure, and Maerin Sedai returns to the candle on the practice table. The search is finished."
    if state["clock"]["fictional_seconds"] >= e.get("lesson_ends_at", 39600):
        story = ("The gallery's teaching interval has ended. Maerin Sedai has gone to her next duty; further supervised casting is unavailable here. "
                 + ("The optional task remains complete. Your quiet interval carries no new obligation." if e["completed"] else "The porter and curtain hook remain available for the unfinished search."))
    return {"title": TITLE, "episode_id": EPISODE_ID, "rules_edition": "notion-manual-v2", "disposable": True,
            "character": {k: state["identity"][k] for k in ("name", "age")} | {"rank": state["rank"]},
            "location": state["world"]["location"], "story": story, "objective": e["objective"],
            "choices": choices(state), "status": "complete" if e["completed"] else "in_progress",
            "completed": e["completed"], "result": e["result"],
            "resources": {k: state["resources"][k] for k in ("vitality", "max_vitality", "wounds", "strain", "supply", "silver")},
            "fictional_seconds": state["clock"]["fictional_seconds"],
            "sample_notice": "Original disposable adventure; supported typed intentions and authored dialogue. No live campaign or general AI GM is loaded."}


def _remember(state, who, fact):
    npc = next(n for n in state["world"]["npcs"] if n["id"] == who)
    if fact not in npc["memories"]:
        npc["memories"].append(fact)


def resolve(state, choice_id, dice=None):
    available = {c["id"]: c for c in choices(state)}
    if choice_id not in available:
        raise ValueError("This approach is not available in the current scene.")
    if available[choice_id]["requires_roll"]:
        if type(dice) not in (list, tuple) or len(dice) != 2 or any(type(d) is not int or not 1 <= d <= 10 for d in dice):
            raise ValueError("Use exactly two d10 results.")
    elif dice not in (None, []):
        raise ValueError("Routine actions do not require dice.")
    next_state = deepcopy(state)
    e = next_state["world"]["episode"]
    seconds, roll, recovered = 0, None, False
    if choice_id == "ask_lysa":
        e["asked"] = True; seconds = 60
        narration = "‘I was sitting here when the window banged,’ Lysa says. ‘I caught my notebook. I thought the letter was inside it.’ She points to the bench, then the open screen. ‘I haven't opened it yet. She hasn't written for weeks.’ Her account tells you where to look; it is not evidence against another person."
        _remember(next_state, "lysa", "You heard her account before acting.")
    elif choice_id == "look_gallery":
        e["stage"] = "search"; seconds = 60
        fact = "You found Lysa's sealed envelope at the inner window grille, within four paces."
        next_state["world"]["known_facts"].append(fact)
        narration = "You check the bench, the floor beside it and the open screen. A pale edge catches the light: the envelope is caught in the inner grille, within four paces. There is no need to guess who took it.\n\nMaerin Sedai looks up. ‘Air could bring that down, if you keep it gentle. Or use the hook. Think about the paper, not merely the distance.’"
    elif choice_id == "prepare_hook":
        e["prepared"] = True; seconds = 60
        narration = "You wrap the hook in a clean cloth. Its sharp edge is covered, and you can guide the paper without catching it. Maerin Sedai nods once, leaving the next choice to you."
    elif choice_id == "hook_letter":
        e["pole_tried"] = True
        bonus = 2 if e["prepared"] else 0
        total = sum(dice) + state["attributes"]["grace"] + state["skills"]["athletics"] + bonus
        result = "clean" if total >= 14 else "costly" if total >= 11 else "setback"
        roll = {"dice": list(dice), "attribute_rating": state["attributes"]["grace"], "skill_rating": state["skills"]["athletics"],
                "modifier": bonus, "difficulty": 14, "total": total, "outcome": result}
        seconds = 300 if result == "costly" else 120
        recovered = result != "setback"
        narration = {"clean": "The hook catches the envelope's edge. You ease it free and lower it to Lysa, the seal untouched.",
                     "costly": "The envelope folds against the grille before you can ease it loose. Five careful minutes leave one crease in the paper, but the seal and contents are intact. You return it to Lysa.",
                     "setback": "The envelope slips from the hook onto the dry ledge. Two minutes have passed; nothing is torn or lost. Air can still reach it, or the porter can lower the screen. There is no reason to repeat the same attempt."}[result]
    elif choice_id in ("air_letter", "practise_spark"):
        weave = "W02" if choice_id == "air_letter" else "W01"
        next_state, receipt = safe_cast(next_state, weave, supervised=True, range_paces=4, weight_kg=.05, dry_fuel=True)
        e = next_state["world"]["episode"]; e["last_cast"] = receipt; seconds = receipt["elapsed_seconds"]
        if "Safe supervised use and release" not in e["evidence"]:
            e["evidence"].append("Safe supervised use and release")
        if choice_id == "air_letter":
            recovered = True
            narration = "You open yourself to saidar and guide a fine working of Air to the envelope. It slides free of the grille, turns once, and settles into Lysa's waiting hands. You release the working.\n\n‘That was enough,’ Maerin Sedai says. Lysa checks the seal, then looks up. ‘Thank you.’"
        else:
            e["spark_practised"] = True
            narration = "At the stone table, you touch the dry wick with a small Spark. The candle catches. You release the working rather than feeding the flame further.\n\n‘Enough for the purpose,’ Maerin Sedai says, setting the snuffer beside it. The practice is recorded; no new technique has been granted."
        _remember(next_state, "maerin", "Observed your careful use and release of a known form.")
    elif choice_id == "ask_porter":
        recovered = True; seconds = 360
        narration = "The porter brings the short handle used for the screen's fastenings. You keep the bench clear while he lowers it; the letter comes within easy reach. Six minutes later it is back with Lysa, unopened. A simple tool has done the job."
    elif choice_id == "decline_letter":
        e.update(stage="complete", completed=True, result="declined")
        narration = "You leave Lysa to arrange the search. She calls to the porter, and Maerin Sedai sets out the lesson notes. No standing, resources or earned progress are lost. This optional request is finished for you."
    elif choice_id == "talk_after":
        seconds = 180; e["reflection"] = True
        narration = ("Lysa keeps the letter folded shut while you sit nearby. ‘My mother writes every line as if paper costs more in Tar Valon,’ she says. A small smile changes her tired face. ‘I might take this to the garden later.’ She leaves the invitation open; you have made no promise." if e["result"] != "declined" else "Lysa sits down while the porter finishes his arrangements. ‘I should have put it away,’ she says, sliding her writing case beneath her notebook. She asks whether the morning's lesson was difficult. You can answer in your own words; no reply is supplied for you.")
        _remember(next_state, "lysa", "Shared a quiet interval without a new obligation.")
    elif choice_id == "study_block":
        seconds = 1200; e["theory_minutes"] = 20
        next_state["progression"]["study"]["gallery_review"] = {"minutes": 20, "status": "complete", "kind": "theory", "new_weave": None}
        e["evidence"].append("Twenty-minute theory review completed")
        narration = "Maerin Sedai lays two diagrams beside the candle. For twenty minutes you review where a working takes hold and how to release it cleanly. She answers the practical questions as they arise.\n\nAt the end she gathers the pages. ‘That is the lesson for today.’ The full block is recorded. No cast occurred during the theory, and there is no extra examination before you may finish."
    elif choice_id == "rest_break":
        seconds = 600
        next_state["resources"]["strain"] = max(0, next_state["resources"]["strain"] - 2)
        next_state["resources"]["vitality"] = min(next_state["resources"]["max_vitality"], next_state["resources"]["vitality"] + 2)
        next_state["clock"]["last_break_end"] = state["clock"]["fictional_seconds"] + seconds
        narration = "You sit safely for ten minutes while the gallery settles into its usual rhythm. The break eases ordinary fatigue; it does not heal a Wound or create another task."
    elif choice_id == "release_source":
        next_state["channeling"].update(embraced=False, held_weaves=[], pending_cast=None)
        narration = "You release the Source. Your held workings end; already spent Strain remains."
    else:
        seconds = 600
        narration = "Light shifts across the gallery floor. For ten minutes there is nothing to prove and no new errand to perform. The finished task stays finished."
    if recovered:
        e.update(stage="complete", completed=True, result="letter_returned")
        e["evidence"].append("Letter returned with its seal intact")
        _remember(next_state, "lysa", "You returned her letter without opening it.")
        narration += "\n\nThe search is complete. Further practice and conversation are optional."
    start = state["clock"]["fictional_seconds"]
    if choice_id == "quiet_interval" and start < e.get("lesson_ends_at", 39600) < start + seconds:
        seconds = e.get("lesson_ends_at", 39600) - start
        narration = "Your quiet interval stops when Maerin Sedai gathers her teaching notes. You have not been committed to another activity."
    next_state["clock"]["fictional_seconds"] += seconds
    if start < e.get("lesson_ends_at", 39600) <= start + seconds:
        narration += "\n\nMaerin Sedai's teaching interval is now over. She leaves the gallery; Lysa returns to her own work. Further supervised practice here is unavailable."
    if choice_id not in ("quiet_interval", "rest_break", "release_source", "decline_letter"):
        first_day_seconds = min(seconds, 86400 - start % 86400)
        if next_state["clock"]["day_activity_seconds"] + first_day_seconds > 28800:
            raise ValueError("This block would exceed the day's activity allowance. Choose rest instead.")
        next_state["clock"]["day_activity_seconds"] += seconds
    if start // 86400 != next_state["clock"]["fictional_seconds"] // 86400:
        next_state["clock"]["day_activity_seconds"] = (start + seconds) % 86400 if choice_id not in ("quiet_interval", "rest_break", "release_source", "decline_letter") else 0
    validate(next_state)
    return {"state": next_state, "narration": narration, "roll": roll, "elapsed_seconds": seconds}


def companion(state):
    """Player-only reference; never send the whole save or hidden GM material."""
    e, c = state["world"]["episode"], state["channeling"]
    return {"recap": view(state)["story"], "location": state["world"]["location"],
            "objective": e["objective"], "evidence": list(e["evidence"]),
            "people": [{**{k: deepcopy(n[k]) for k in ("name", "role", "known", "memories")},
                        "present": state["clock"]["fictional_seconds"] < e.get("lesson_ends_at", 39600)} for n in state["world"]["npcs"]],
            "facts": list(state["world"]["known_facts"]),
            "sheet": {"rank": state["rank"], "level": state["level"], "attributes": deepcopy(state["attributes"]),
                      "skills": deepcopy(state["skills"]), "inventory": list(state["resources"]["inventory"]),
                      "capacity": c["current_capacity"], "control": c["control"], "flows": deepcopy(c["flows"]),
                      "potential": c["potential"] if state["identity"].get("potential_visibility") == "visible" else None,
                      "weaves": [{"id": id, **deepcopy(WEAVES[id])} for id in c["known_weaves"] if id in WEAVES]},
            "study": deepcopy(state["progression"]["study"]), "last_cast": deepcopy(e["last_cast"]),
            "lore_notes": ["Original scene and supporting cast; no historical event is implied.",
                           "The weave measurements and advancement procedures are manual-v2 house rules.",
                           "Learning a weave and having permission to practise it are separate. Maerin Sedai is present here."]}


def interpret(state, prompt):
    """No mutation or external calls. Only a definite supported intent proposes action."""
    if type(prompt) is not str or not 1 <= len(prompt.strip()) <= 2000 or "\x00" in prompt:
        raise ValueError("Use a short approach or question, up to 2,000 characters.")
    prompt.encode("utf-8")
    text = prompt.lower().replace("’", "'").strip()
    available = {c["id"]: c for c in choices(state)}
    def answer(message, kind="answer", choice=None):
        return {"kind": kind, "message": message, "choice_id": choice}
    if re.search(r"\b(ignore|system prompt|api key|developer|reveal secrets)\b", text):
        return answer("I can describe what your character knows or help with the available approaches. Private notes and instructions do not form part of play.")
    if re.search(r"\b(heal|healing|balefire|attack|burn|kill|steal|read her|open the letter|open her|shield|teleport|gateway)\b", text):
        return answer("That intention is outside this episode's supported methods. I have not substituted another action or changed the story. You can choose an available method or ask about it.", "clarify")
    if "?" in text or re.match(r"^(what|why|how|can|could|would|should|is|do|does)\b", text):
        if re.search(r"\b(strain|capacity|air|channel|weave|spark)\b", text):
            return answer("You know Spark and Air Hand. Each safe use here costs 1 Strain, with Maerin Sedai supervising. Air Hand can move a visible object of at most 5 kg within 10 paces. Questions do not cast or advance time.")
        if re.search(r"\b(done|finish|complete|next)\b", text) and state["world"]["episode"]["completed"]:
            return answer("The optional task is finished. You can leave it finished, talk, practise, study a full twenty-minute block or enjoy a quiet interval. None is an additional qualification.")
        if re.search(r"\b(do|approaches|options|available)\b", text):
            return answer("Available now: " + "; ".join(c["label"] for c in available.values()) + ". You can choose below or type a supported approach. No action has been taken.")
        return answer(view(state)["story"])
    if re.search(r"\b(maybe|perhaps|if|might|then|after that|and)\b", text):
        return answer("Choose the first definite approach you want to take. A tentative plan has not committed an action.", "clarify")
    if re.search(r"\b(don't|do not|won't|will not|refuse|decline)\b", text):
        if "decline_letter" in available and re.fullmatch(r"(?:i )?(?:decline|refuse)(?: to help| the task| the request| the optional task)?[.!]?", text):
            return answer("Leave the optional search to Lysa.", "proposal", "decline_letter")
        return answer("No action taken. You can choose another approach or ask about the situation.", "clarify")
    command = re.sub(r"^(?:i |she |elin )", "", text).rstrip(".! ")
    patterns = {
        "ask_lysa": r"(?:ask|talk to|speak to|listen to) lysa(?: what happened| about (?:her|the) letter)?",
        "look_gallery": r"(?:look around|search|inspect|observe|check)(?: the gallery| the room| the window)?|watch(?: quietly)?",
        "air_letter": r"(?:use|cast|weave) (?:my )?air(?: hand)?(?: to (?:retrieve|lower|bring down|get) (?:the |her )?(?:letter|envelope))?|(?:retrieve|lower) the letter with air(?: hand)?",
        "prepare_hook": r"(?:pad|wrap|prepare) (?:the )?(?:hook|pole)(?: (?:with|in) (?:a |the )?(?:clean )?cloth)?",
        "hook_letter": r"(?:use|reach with) (?:the )?(?:hook|pole)|(?:retrieve|get|lift) (?:the )?letter with (?:the )?(?:hook|pole)",
        "ask_porter": r"(?:ask|call|fetch|get|wait for) (?:the )?porter(?: for help| to lower the screen)?",
        "talk_after": r"(?:talk to|sit with|listen to|speak to) lysa|stay for (?:a )?(?:quiet )?conversation",
        "practise_spark": r"(?:practise|practice|cast|use) (?:a )?(?:small )?spark|light (?:the |a )?candle",
        "study_block": r"study(?: for (?:twenty|20) minutes| until (?:the )?(?:short )?lesson ends)?|review the lesson|finish the lesson",
        "quiet_interval": r"(?:enjoy|take|spend) (?:a )?quiet (?:interval|ten minutes)|relax|wait quietly",
        "rest_break": r"rest|recover|take (?:a )?(?:recovery )?break",
        "release_source": r"(?:release|let go of) (?:the )?(?:source|saidar|weaves)",
    }
    matched = [id for id, pattern in patterns.items() if id in available and re.fullmatch(pattern, command)]
    if len(matched) == 1:
        choice = available[matched[0]]
        return answer(choice["description"], "proposal", matched[0])
    return answer("I haven't taken an action. This authored adventure understands the listed approaches and some typed variations. Choose the closest method below, or ask about the scene; a general AI GM is not enabled.", "clarify")
