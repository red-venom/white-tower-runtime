"""Reviewed manual-v2 safe training operations. No invented exceptional powers."""
from copy import deepcopy

WEAVES = {
    "W01": {"name": "Spark", "control": 1, "flows": {"fire": 1}, "load": 1,
            "range_paces": 10, "duration": "instant", "effect": "Light a small exposed dry fuel source."},
    "W02": {"name": "Air Hand", "control": 1, "flows": {"air": 1}, "load": 1,
            "range_paces": 10, "duration": "sustained", "effect": "Move a visible object of at most 5 kg slowly; no unknown locks or resisting people."},
}


def safe_cast(state, weave_id, *, supervised, range_paces, weight_kg=0, dry_fuel=False):
    """Validate first, pay once, complete a bounded practice use, release its weave.

    Targets and supervision are supplied by the authored scene, never a client.
    This is not a combat, tying, healing or general spellcasting resolver.
    """
    caster = state["channeling"]
    weave = WEAVES.get(weave_id)
    if not supervised or not weave or weave_id not in caster["known_weaves"]:
        raise ValueError("This form needs established knowledge and supervision.")
    if caster["pending_cast"] is not None:
        raise ValueError("Finish or release the existing cast first.")
    if caster["control"] < weave["control"] or any(caster["flows"].get(k, 0) < v for k, v in weave["flows"].items()):
        raise ValueError("The learned handling prerequisites are not met.")
    if not 0 <= range_paces <= weave["range_paces"]:
        raise ValueError("The target is out of range.")
    if weave_id == "W02" and not 0 <= weight_kg <= 5:
        raise ValueError("Air Hand cannot move that weight.")
    if weave_id == "W01" and not dry_fuel:
        raise ValueError("Spark needs exposed dry fuel.")
    held = sum(w["load"] for w in caster["held_weaves"])
    if held + weave["load"] > caster["current_capacity"] or (weave["duration"] == "sustained" and len(caster["held_weaves"]) >= caster["control"]):
        raise ValueError("Release an existing working before adding this one.")
    if state["resources"]["strain"] + weave["load"] > 2 * caster["current_capacity"]:
        raise ValueError("Recover before adding more Strain.")
    result = deepcopy(state)
    result["resources"]["strain"] += weave["load"]
    # The bounded action includes ordinary embrace, its brief use and release.
    # Existing held effects/source state are preserved; no existing cost refunds.
    return result, {"weave_id": weave_id, "load": weave["load"], "strain_paid": weave["load"],
                    "roll_required": False, "elapsed_seconds": 10 if caster["embraced"] else 20,
                    "released_after_use": True, "rules_edition": "notion-manual-v2"}
