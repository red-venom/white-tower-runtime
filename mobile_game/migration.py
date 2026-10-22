"""Offline preservation capsules for future notion-manual-v2 campaign support.

Nothing here imports a campaign into a database, resolves an action, changes the
source, calls an API, or makes the disposable sample engine accept real state.
The checksum detects accidental modification; it authenticates neither a source
nor permission to activate it. Callers must independently establish source access,
freshness and completeness before a future migration.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

CAPSULE_SCHEMA = "white-tower-manual-migration-capsule-v1"
REPORT_SCHEMA = "white-tower-manual-migration-report-v1"
EDITION = "notion-manual-v2"
STATUS = "STAGED_NOT_PLAYABLE"
MAX_INT = 2**53 - 1
STATE_FIELDS = {
    "identity", "attributes", "skills", "rank", "level", "resources",
    "channeling", "clock", "progression", "world", "unresolved_decisions",
}
HEAD_FIELDS = {
    "schema", "campaign_id", "action_id", "sequence", "predecessor_page",
    "predecessor_revision", "rules_edition", "status", "intent", "rules_citations",
    "stakes", "acceptance", "dice", "pre_state", "post_state", "resolution",
    "narration", "checks",
}
ATTRIBUTES = ("Body", "Grace", "Wits", "Will", "Presence")
SKILLS = ("Athletics", "Melee", "Marksmanship", "Stealth", "Survival", "Notice",
          "Scholarship", "Medicine", "Insight", "Persuasion", "Leadership", "Composure")
FLOWS = ("Air", "Earth", "Fire", "Water", "Spirit")


class MigrationError(ValueError):
    """The supplied data cannot form a validated preservation capsule."""


def _need(condition, message):
    if not condition:
        raise MigrationError(message)


def _nat(value, maximum=MAX_INT):
    return type(value) is int and 0 <= value <= maximum


def _json_value(value):
    """Preserve unknown JSON fields, while rejecting non-JSON Python values."""
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float:
        _need(math.isfinite(value), "Nonfinite JSON number.")
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict:
        _need(all(type(key) is str for key in value), "JSON object keys must be strings.")
        for item in value.values():
            _json_value(item)
        return
    raise MigrationError("Unsupported non-JSON value.")


def canonical(value):
    _json_value(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise MigrationError("Invalid or excessively nested JSON.") from exc


def checksum(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load_json_bytes(raw):
    """Strict loading for local archives, rejecting duplicate keys and NaN."""
    _need(type(raw) in (bytes, str), "Supply UTF-8 JSON bytes or text.")

    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "Duplicate JSON object key.")
            result[key] = value
        return result

    def invalid_constant(_):
        raise MigrationError("Nonfinite JSON number.")

    try:
        value = json.loads(raw.decode("utf-8") if type(raw) is bytes else raw,
                           object_pairs_hook=pairs, parse_constant=invalid_constant)
        canonical(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise MigrationError("Invalid UTF-8 JSON archive.") from exc


def _reference_id(value):
    _need(type(value) is str and 1 <= len(value) <= 2048, "Missing source page reference.")
    if re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        return value.replace("-", "").lower()
    parsed = urlsplit(value)
    _need(parsed.scheme == "https" and parsed.hostname in ("app.notion.com", "notion.so", "www.notion.so"),
          "Unsupported source page reference.")
    ids = re.findall(r"(?<![0-9a-fA-F])(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})(?![0-9a-fA-F])", parsed.path)
    _need(len(ids) == 1, "Ambiguous source page reference.")
    return ids[0].replace("-", "").lower()


def _mapping(value, fields, name):
    _need(type(value) is dict and fields <= set(value), "Incomplete " + name + ".")


def _state(state):
    """Recognise the current manual shape; retain, rather than normalise, fields."""
    _mapping(state, STATE_FIELDS, "manual state")
    _need("schema" not in state, "Unsupported tagged manual-state schema.")
    _need(type(state["identity"]) is dict and type(state["rank"]) is str and
          type(state["level"]) is int and 1 <= state["level"] <= 12, "Invalid character header.")
    _mapping(state["attributes"], set(ATTRIBUTES), "manual Attributes")
    _mapping(state["skills"], set(SKILLS), "manual Skills")
    _need(all(_nat(state["attributes"][key], 3) for key in ATTRIBUTES), "Invalid Attribute rating.")
    _need(all(_nat(state["skills"][key], 4) for key in SKILLS), "Invalid Skill rating.")
    resources = state["resources"]
    _mapping(resources, {"vitality", "max_vitality", "wounds", "strain", "supply", "silver", "inventory"}, "resources")
    _need(resources["max_vitality"] == 6 + 2*state["attributes"]["Body"] and type(resources["max_vitality"]) is int,
          "Maximum Vitality does not match the saved Body rating.")
    for key, maximum in (("vitality", resources["max_vitality"]), ("wounds", 3), ("supply", 6), ("silver", MAX_INT)):
        _need(_nat(resources[key], maximum), "Invalid resource boundary.")
    channeling = state["channeling"]
    _mapping(channeling, {"potential", "potential_roll", "capacity", "control", "flows", "source_embraced",
                          "known_weaves", "held", "tied", "pending_cast", "circle", "angreal"}, "manual channeling state")
    _need(type(channeling["potential"]) is int and 8 <= channeling["potential"] <= 10,
          "Unsupported saved Potential.")
    _need(type(channeling["capacity"]) is int and 3 <= channeling["capacity"] <= channeling["potential"],
          "Invalid saved Capacity.")
    _need(type(channeling["control"]) is int and 1 <= channeling["control"] <= 4,
          "Invalid saved Control.")
    _need(_nat(resources["strain"], 2*channeling["capacity"]), "Invalid Strain boundary.")
    _mapping(channeling["flows"], set(FLOWS), "manual Flows")
    _need(all(type(channeling["flows"][key]) is int and 1 <= channeling["flows"][key] <= 3 for key in FLOWS), "Invalid Flow rating.")
    _need(type(channeling["source_embraced"]) is bool and
          all(type(channeling[key]) is list for key in ("known_weaves", "held", "tied")), "Invalid channeling records.")
    clock = state["clock"]
    _mapping(clock, {"fictional_seconds", "day_activity_seconds", "last_break_end", "last_full_rest_end"}, "manual clock")
    _need(_nat(clock["fictional_seconds"]) and _nat(clock["day_activity_seconds"], 28800), "Invalid clock boundary.")
    for key in ("last_break_end", "last_full_rest_end"):
        _need(clock[key] is None or _nat(clock[key], clock["fictional_seconds"]), "Invalid recovery timestamp.")
    progression = state["progression"]
    _mapping(progression, {"chapter", "proofs", "general_points", "channel_points", "learning_opportunities", "courses",
                           "capacity_proofs", "service_records", "readiness", "formal_test", "rank_choices", "completed_chapters"}, "progression")
    _mapping(progression["chapter"], {"number", "status"}, "manual chapter")
    _need(type(progression["chapter"]["number"]) is int and 1 <= progression["chapter"]["number"] <= 12,
          "Unsupported chapter number.")
    _need(all(_nat(progression[key]) for key in ("general_points", "channel_points", "learning_opportunities")), "Invalid advancement balance.")
    _need(type(progression["courses"]) is dict and all(type(progression[key]) is list for key in
          ("proofs", "capacity_proofs", "service_records", "completed_chapters")), "Invalid advancement ledgers.")
    world = state["world"]
    _mapping(world, {"location", "scene", "scene_plan", "known_facts", "allies", "npcs", "projects",
                     "commitments", "due_events", "threat_clocks", "conflict"}, "manual world")
    _mapping(world["scene"], {"id", "status", "description"}, "manual scene")
    _need(type(world["scene_plan"]) is dict, "Invalid scene plan.")
    _need(all(type(world[key]) is list for key in ("known_facts", "allies", "npcs", "projects", "commitments", "due_events", "threat_clocks")), "Invalid world ledgers.")
    _need(type(state["unresolved_decisions"]) is list, "Invalid unresolved decisions.")


def _sources(checkpoint, head, private_gm, committed_head_reference):
    for value in (checkpoint, head, private_gm):
        canonical(value)
    _mapping(checkpoint, {"campaign_id", "rules_edition", "head", "revision", "pending", "state"}, "checkpoint")
    _need("schema" not in checkpoint, "Unsupported tagged checkpoint schema.")
    _mapping(head, HEAD_FIELDS, "committed head")
    _need(head["schema"] == "notion-turn-v1", "Unsupported committed-turn schema.")
    _need(checkpoint["rules_edition"] == head["rules_edition"] == EDITION, "Unsupported or conflicting rules edition.")
    _need(checkpoint["pending"] is None, "Pending source transaction must be reconciled before staging.")
    _need(head["status"] == "COMMITTED", "The source head is not committed.")
    _need(type(checkpoint["campaign_id"]) is str and bool(checkpoint["campaign_id"]) and
          checkpoint["campaign_id"] == head["campaign_id"], "Source campaign mismatch.")
    _need(type(head["action_id"]) is str and bool(head["action_id"]), "Missing source action identity.")
    _need(_nat(checkpoint["revision"]) and checkpoint["revision"] > 0 and
          _nat(head["sequence"]) and _nat(head["predecessor_revision"]) and
          checkpoint["revision"] == head["sequence"] == head["predecessor_revision"] + 1,
          "Invalid source revision sequence.")
    _need(_reference_id(checkpoint["head"]) == _reference_id(committed_head_reference), "Fetched head reference differs from checkpoint.")
    _reference_id(head["predecessor_page"])
    _need(_reference_id(head["predecessor_page"]) != _reference_id(committed_head_reference), "Head cannot name itself as predecessor.")
    for state in (checkpoint["state"], head["pre_state"], head["post_state"]):
        _state(state)
    _need(canonical(checkpoint["state"]) == canonical(head["post_state"]), "Checkpoint and committed post-state disagree.")
    _mapping(head["resolution"], {"elapsed_seconds"}, "resolution")
    elapsed = head["resolution"]["elapsed_seconds"]
    _need(_nat(elapsed) and head["post_state"]["clock"]["fictional_seconds"] -
          head["pre_state"]["clock"]["fictional_seconds"] == elapsed, "Elapsed time disagrees with saved clocks.")
    _mapping(head["dice"], {"method", "values"}, "original dice record")
    _need(type(head["dice"]["method"]) is str and type(head["dice"]["values"]) is list,
          "Invalid original dice record.")
    _mapping(private_gm, {"id", "url", "title", "text"}, "private GM page entity")
    _need("schema" not in private_gm, "Unsupported private GM entity schema.")
    _need(type(private_gm["text"]) is str and bool(private_gm["text"]) and type(private_gm["title"]) is str,
          "Private GM content is incomplete.")
    _need(_reference_id(private_gm["id"]) == _reference_id(private_gm["url"]), "Private GM page identity mismatch.")
    _need(not any(private_gm.get(key) is True for key in ("truncated", "is_truncated", "has_more")),
          "Private GM content is explicitly incomplete.")


def create_capsule(checkpoint, head, private_gm, *, committed_head_reference):
    """Preserve complete source objects, with no alias conversion or live activation."""
    _sources(checkpoint, head, private_gm, committed_head_reference)
    archive = {"checkpoint": deepcopy(checkpoint), "committed_head": deepcopy(head),
               "committed_head_reference": committed_head_reference}
    private_reference = {"gm_record": deepcopy(private_gm)}
    source_hashes = {"checkpoint": checksum(checkpoint), "committed_head": checksum(head),
                     "private_gm_record": checksum(private_gm)}
    capsule = {
        "schema": CAPSULE_SCHEMA, "status": STATUS, "playable": False,
        "rules_edition": EDITION, "source_revision": checkpoint["revision"],
        "capsule_id": "migration-" + checksum({"source_hashes": source_hashes,
                      "head_id": _reference_id(committed_head_reference)})[:32],
        "source_hashes": source_hashes, "source_archive": archive,
        "private_reference": private_reference,
        "limitations": {
            "activation_performed": False, "fictional_time_advanced": False,
            "original_state_modified": False, "fresh_remote_read_verified": False,
            "source_authenticity_verified": False, "adjudication_verified": False,
            "full_historical_journal_included": False,
            "requires_compatible_campaign_engine": True,
            "private_backup_not_player_facing_export": True,
        },
    }
    capsule["checksum_sha256"] = checksum(capsule)
    return capsule


def validate_capsule(capsule):
    """Check integrity and rerun source checks without trusting asserted flags."""
    _need(type(capsule) is dict, "Missing migration capsule.")
    expected_keys = {"schema", "status", "playable", "rules_edition", "source_revision", "capsule_id",
                     "source_hashes", "source_archive", "private_reference", "limitations", "checksum_sha256"}
    _need(set(capsule) == expected_keys and capsule["schema"] == CAPSULE_SCHEMA, "Unsupported capsule schema.")
    archive, private = capsule["source_archive"], capsule["private_reference"]
    _need(type(archive) is dict and set(archive) == {"checkpoint", "committed_head", "committed_head_reference"}, "Incomplete source archive.")
    _need(type(private) is dict and set(private) == {"gm_record"}, "Incomplete private reference archive.")
    expected = create_capsule(archive["checkpoint"], archive["committed_head"], private["gm_record"],
                              committed_head_reference=archive["committed_head_reference"])
    _need(canonical(capsule) == canonical(expected), "Capsule integrity or preservation flags differ.")
    return True


def redacted_report(capsule):
    """Safe structural receipt: no identity, story, private text, URLs or source IDs."""
    validate_capsule(capsule)
    state = capsule["source_archive"]["checkpoint"]["state"]
    return {
        "schema": REPORT_SCHEMA, "capsule_schema": CAPSULE_SCHEMA, "status": STATUS,
        "playable": False, "source_rules_edition": EDITION,
        "source_revision": capsule["source_revision"], "checksum_sha256": capsule["checksum_sha256"],
        "checks": {
            "source_schema_recognised": True, "committed_head_reference_matches": True,
            "revision_and_edition_agree": True, "no_pending_source_transaction": True,
            "checkpoint_equals_complete_post_state": True, "elapsed_time_matches_clocks": True,
            "resource_bounds_checked": True, "complete_source_objects_preserved": True,
            "private_reference_separate_from_source_state": True, "capsule_integrity_verified": True,
            "live_import_performed": False, "gameplay_compatibility_verified": False,
            "freshness_or_authenticity_verified": False, "adjudication_verified": False,
        },
        "coverage": {"source_objects_preserved": 3, "state_root_fields": len(state),
                     "original_dice_records_retained": True, "unknown_json_fields_retained": True,
                     "full_historical_journal_included": False},
    }
