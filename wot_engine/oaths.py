"""Bounded, deterministic Oaths adjudication; no world lookup or prose classifier.

The caller supplies a frozen meaning/effect and an actor-scoped belief packet.
Only trusted authored actions may supply those classifications. This module does
not establish that arbitrary prose matches its typed meaning, authenticate source
events, or discover beliefs. Invalid packets raise OathInputError before a ruling.
Valid but unresolved meanings return CLARIFY without spending game resources.

The defaults implement lore-and-oaths.md, not a claimed canonical algorithm.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .contracts import canonical, digest


MODULE_VERSION = "oaths-950ne-v1"
SOURCE_LOCATOR = {
    "source_id": "S01",
    "url": "https://reactormag.com/the-wheel-of-time-re-read-new-spring-part-6/",
    "locator": "New Spring, chapter 11: Just Before Dawn; reproduced oath quotation",
    "claim_ids": ["L001", "L002", "L003", "L004"],
    "evidence": "Primary novel quotation in a publisher article; printed edition not collated",
    "date_scope": "950 NE institutional extension is provisional (L005)",
}
HOUSE_DEFAULTS = {
    "HD-STATUS": "Explicit recorded Oaths status; never infer it from rank.",
    "HD-CLARIFY": "An unfamiliar or unresolved meaning needs clarification without a penalty.",
    "HD-O01": "Honest error follows the actor's established belief.",
    "HD-O03": "A credible literal truth can omit another fact.",
    "HD-O04": "A promise contradicting an established intention is false.",
    "HD-O06": "Manufactured items use their intended purpose, including mundane manufacture.",
    "HD-O07": "Extreme defence needs an evidenced perceived threat to a named protected person.",
    "HD-O09": "A restraint is permitted only without injury or immediate harmful exposure.",
    "HD-O10": "Intended harmful effects count as weapon use despite a harmless name.",
    "HD-O11": "Inactive Oaths impose no restriction; other rules still apply.",
    "HD-O12": "Circle participation cannot bypass the participant's Oaths.",
    "HD-CONSTRUCT": "Persistent weapon constructs are checked under both relevant restrictions.",
}


class OathInputError(ValueError):
    """Malformed or unauthorised actor packet; no ruling was made."""


def _require(condition, message):
    if not condition:
        raise OathInputError(message)


def _keys(value, expected, label):
    _require(type(value) is dict and set(value) == set(expected), f"Invalid {label} fields")


def _id(value):
    _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value), "Invalid identifier")


def _text(value):
    _require(type(value) is str and 0 < len(value.strip()) <= 4000, "Invalid text")


def _maybe_bool(value):
    _require(value is None or type(value) is bool, "Expected Boolean or unresolved value")


def _maybe_id(value):
    if value is not None:
        _id(value)


def _actor_valid(actor):
    _keys(actor, ("actor_id", "oaths_active", "oaths_source_event", "beliefs", "evidence"), "actor")
    _id(actor["actor_id"])
    _maybe_bool(actor["oaths_active"])
    _maybe_id(actor["oaths_source_event"])
    _require(type(actor["beliefs"]) is list and len(actor["beliefs"]) <= 128, "Invalid beliefs")
    _require(type(actor["evidence"]) is list and len(actor["evidence"]) <= 256, "Invalid evidence")
    evidence = {}
    for item in actor["evidence"]:
        _keys(item, ("evidence_id", "basis", "statement", "source_event", "audience_ids"), "evidence")
        _id(item["evidence_id"])
        _id(item["source_event"])
        _text(item["statement"])
        _require(item["basis"] in ("observation", "testimony", "inference"), "Invalid evidence basis")
        audience = item["audience_ids"]
        _require(type(audience) is list and 0 < len(audience) <= 128, "Invalid evidence audience")
        for audience_id in audience:
            _id(audience_id)
        _require(actor["actor_id"] in audience, "Evidence is unavailable to this actor")
        _require(item["evidence_id"] not in evidence, "Duplicate evidence identifier")
        evidence[item["evidence_id"]] = item
    belief_ids = set()
    for item in actor["beliefs"]:
        _keys(item, ("belief_id", "proposition_id", "value", "evidence_ids"), "belief")
        _id(item["belief_id"])
        _id(item["proposition_id"])
        _require(type(item["value"]) is bool, "Invalid belief value")
        refs = item["evidence_ids"]
        _require(type(refs) is list and 0 < len(refs) <= 128, "A belief needs supplied evidence")
        for ref in refs:
            _id(ref)
            _require(ref in evidence, "Belief cites unavailable evidence")
        _require(item["belief_id"] not in belief_ids, "Duplicate belief identifier")
        belief_ids.add(item["belief_id"])


def _manufacture_valid(details):
    _keys(details, ("item_kind", "intended_human_killing"), "manufacture")
    _require(details["item_kind"] in ("tool", "weapon", "construct", "unclear"), "Invalid item kind")
    _maybe_bool(details["intended_human_killing"])


def _proposal_valid(proposal, *, inside_circle=False):
    _keys(proposal, ("proposal_id", "kind", "statement_or_action", "intent", "details"), "proposal")
    _id(proposal["proposal_id"])
    _text(proposal["statement_or_action"])
    _text(proposal["intent"])
    kind, details = proposal["kind"], proposal["details"]
    _require(type(kind) is str and kind in ("speech", "manufacture", "power", "circle", "ordinary", "unclear"), "Invalid proposal kind")
    if kind == "speech":
        _require(type(details) is dict, "Invalid speech details")
        if details.get("speech_act") == "statement":
            _keys(details, ("speech_act", "proposition_id", "assertion", "literal_credible"), "statement")
            _id(details["proposition_id"])
            _require(type(details["assertion"]) is bool, "Invalid assertion")
        elif details.get("speech_act") == "promise":
            _keys(details, ("speech_act", "intent_to_fulfil", "literal_credible"), "promise")
            _maybe_bool(details["intent_to_fulfil"])
        else:
            _keys(details, ("speech_act", "literal_credible"), "unresolved speech")
            _require(details["speech_act"] == "unclear", "Invalid speech act")
        _maybe_bool(details["literal_credible"])
    elif kind == "manufacture":
        _manufacture_valid(details)
    elif kind == "power":
        _keys(details, ("effect", "injures", "exposes_immediate_harm", "shadowspawn_proposition_id", "danger", "construct"), "Power effect")
        _require(details["effect"] in ("utility", "restraint", "weapon", "unclear"), "Invalid effect")
        _maybe_bool(details["injures"])
        _maybe_bool(details["exposes_immediate_harm"])
        _maybe_id(details["shadowspawn_proposition_id"])
        if details["danger"] is not None:
            danger = details["danger"]
            _keys(danger, ("threat_proposition_id", "protected_person", "relationship_proposition_id", "extreme"), "danger")
            _id(danger["threat_proposition_id"])
            _maybe_id(danger["relationship_proposition_id"])
            _require(danger["protected_person"] in ("self", "warder", "sister", "bystander", "unclear"), "Invalid protected person")
            _maybe_bool(danger["extreme"])
            _require(danger["protected_person"] != "self" or danger["relationship_proposition_id"] is None, "Self needs no relationship claim")
        if details["construct"] is not None:
            _manufacture_valid(details["construct"])
            _require(details["construct"]["item_kind"] in ("construct", "unclear"), "Invalid persistent construct")
    elif kind == "circle":
        _require(not inside_circle, "Nested circle proposals are unsupported")
        _keys(details, ("joint_action",), "circle")
        _proposal_valid(details["joint_action"], inside_circle=True)
    else:
        _keys(details, (), "ordinary or unresolved action")


class _Evaluation:
    def __init__(self, actor):
        self.actor = actor
        self.beliefs = set()
        self.evidence = set()
        self.rules = set()
        self.defaults = {"HD-STATUS"}
        self.dangers = []

    def belief(self, proposition_id):
        if proposition_id is None:
            return None
        matches = [item for item in self.actor["beliefs"] if item["proposition_id"] == proposition_id]
        for item in matches:
            self.beliefs.add(item["belief_id"])
            self.evidence.update(item["evidence_ids"])
        values = {item["value"] for item in matches}
        return next(iter(values)) if len(values) == 1 else None

    def clarify(self, reason):
        self.defaults.add("HD-CLARIFY")
        return "CLARIFY", reason

    def manufacture(self, details):
        self.rules.add("OATH-2")
        self.defaults.add("HD-O06")
        if details["intended_human_killing"] is True:
            return "BLOCK", "Making an item for intended human killing is prohibited."
        if details["item_kind"] == "unclear" or details["intended_human_killing"] is None:
            return self.clarify("Clarify the manufactured item's form and intended use.")
        return "ALLOW", "The declared manufacture has no intended human killing."

    def weapon(self, details):
        shadowspawn = self.belief(details["shadowspawn_proposition_id"])
        if shadowspawn is True:
            return "ALLOW", "The actor's evidenced target belief permits this Power use."
        uncertain = details["shadowspawn_proposition_id"] is not None and shadowspawn is None
        danger = details["danger"]
        if danger is not None:
            self.defaults.add("HD-O07")
            self.dangers.append(deepcopy(danger))
            threat = self.belief(danger["threat_proposition_id"])
            person = danger["protected_person"]
            relationship = True if person == "self" else self.belief(danger["relationship_proposition_id"])
            if person in ("self", "warder", "sister"):
                if danger["extreme"] is True and threat is True and relationship is True:
                    return "ALLOW", "The actor has an evidenced extreme-defence exception for a named protected person."
                uncertain |= danger["extreme"] is None or threat is None or relationship is None
            elif person == "unclear":
                uncertain = True
        if uncertain:
            return self.clarify("Clarify the actor's relevant target belief or qualifying defence evidence.")
        return "BLOCK", "No qualifying exception permits the declared weapon use of the Power."

    def power(self, details):
        self.rules.add("OATH-3")
        manufactured = None
        if details["construct"] is not None:
            self.defaults.add("HD-CONSTRUCT")
            manufactured = self.manufacture(details["construct"])
        harmful = details["effect"] == "weapon" or details["injures"] is True or details["exposes_immediate_harm"] is True
        if harmful:
            self.defaults.add("HD-O10")
            effect = self.weapon(details)
        elif details["effect"] == "unclear" or details["injures"] is None or details["exposes_immediate_harm"] is None:
            effect = self.clarify("Clarify the Power effect and its intended harmful consequences.")
        elif details["effect"] == "restraint":
            self.defaults.add("HD-O09")
            effect = "ALLOW", "The declared restraint causes no injury or immediate harmful exposure."
        else:
            effect = "ALLOW", "The declared utility effect is not weapon use."
        # A clear prohibition remains a prohibition when another restriction is unresolved.
        if manufactured is not None:
            for result in ("BLOCK", "CLARIFY"):
                for item in (manufactured, effect):
                    if item[0] == result:
                        return item
        return effect

    def evaluate(self, proposal):
        kind, details = proposal["kind"], proposal["details"]
        if kind == "speech":
            self.rules.add("OATH-1")
            if details["literal_credible"] is not True or details["speech_act"] == "unclear":
                return self.clarify("Clarify a credible literal meaning before speaking.")
            if details["speech_act"] == "promise":
                self.defaults.add("HD-O04")
                if details["intent_to_fulfil"] is None:
                    return self.clarify("Clarify the intention behind the proposed promise.")
                if not details["intent_to_fulfil"]:
                    return "BLOCK", "The proposed promise contradicts the declared intention."
                return "ALLOW", "The promise agrees with the declared intention."
            belief = self.belief(details["proposition_id"])
            if belief is None:
                return self.clarify("The proposed statement needs a clear, evidenced belief available to the actor.")
            if belief != details["assertion"]:
                return "BLOCK", "The proposed statement contradicts the actor's established belief."
            self.defaults.update(("HD-O01", "HD-O03"))
            return "ALLOW", "The credible literal statement agrees with the actor's established belief."
        if kind == "manufacture":
            return self.manufacture(details)
        if kind == "power":
            return self.power(details)
        if kind == "circle":
            self.defaults.add("HD-O12")
            result, reason = self.evaluate(details["joint_action"])
            if result == "BLOCK":
                return result, "Circle participation would assist an act prohibited for this participant."
            if result == "CLARIFY":
                return result, "Clarify the circle's intended act before this participant joins."
            return result, "The declared joint act is permitted for this participant."
        if kind == "ordinary":
            return "ALLOW", "This classified ordinary action does not engage an Oaths restriction."
        return self.clarify("The proposed action needs a supported meaning or effect classification.")


def adjudicate(actor, proposal):
    """Return a complete private audit ruling from an actor-scoped frozen request.

    The full record contains intent and belief identifiers. Use public_view() for
    player-facing output. There is intentionally no hidden-world-state argument.
    An ALLOW result grants no learned weave, safety exception, resource or success.
    """
    _actor_valid(actor)
    _proposal_valid(proposal)
    evaluation = _Evaluation(actor)
    if actor["oaths_active"] is None or actor["oaths_source_event"] is None:
        result, reason = evaluation.clarify("Confirm the actor's recorded Oaths status before resolving this action.")
    elif actor["oaths_active"] is False:
        evaluation.defaults.add("HD-O11")
        result, reason = "ALLOW", "No active Oaths restrict this actor; ordinary rules still apply."
    else:
        result, reason = evaluation.evaluate(proposal)
    # Hash only the evidence actually used, so unrelated private facts do not
    # affect even the audit identity or appear in the ruling.
    relevant = {
        "beliefs": sorted((deepcopy(b) for b in actor["beliefs"] if b["belief_id"] in evaluation.beliefs), key=lambda b: b["belief_id"]),
        "evidence": sorted((deepcopy(e) for e in actor["evidence"] if e["evidence_id"] in evaluation.evidence), key=lambda e: e["evidence_id"]),
    }
    request = {"module_version": MODULE_VERSION, "actor_id": actor["actor_id"],
               "oaths_active": actor["oaths_active"], "oaths_source_event": actor["oaths_source_event"],
               "proposal": proposal, **relevant}
    ruling = {
        "schema": "oath-ruling-v1", "oath_ruling_id": "oath-" + digest(request)[:32],
        "module_version": MODULE_VERSION, "actor_id": actor["actor_id"],
        "oaths_active": actor["oaths_active"], "oaths_source_event": actor["oaths_source_event"],
        "proposal_id": proposal["proposal_id"], "statement_or_action": proposal["statement_or_action"],
        "intent": proposal["intent"], "proposed_action": deepcopy(proposal),
        "belief_ids": sorted(evaluation.beliefs), "evidence_ids": sorted(evaluation.evidence),
        "danger_basis": deepcopy(evaluation.dangers), "rule_ids": sorted(evaluation.rules),
        "house_default_ids": sorted(evaluation.defaults), "source_locators": [deepcopy(SOURCE_LOCATOR)],
        "result": result, "public_reason": reason, "request_hash": digest(request),
        "evidence_snapshot": relevant,
    }
    canonical(ruling)
    return ruling


def public_view(ruling):
    """Expose the generic explanation; exclude actor beliefs, intent and evidence."""
    return {key: deepcopy(ruling[key]) for key in (
        "module_version", "result", "public_reason", "rule_ids", "house_default_ids", "source_locators")}
