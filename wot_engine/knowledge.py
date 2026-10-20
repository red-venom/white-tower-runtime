"""Deterministic knowledge packets and bounded NPC-proposal validation.

This module is independent of the live scene/controller path. Callers supply a
trusted fact catalogue, source access registry, current history boundary, and
rule policy. None may be copied from a model's candidate proposal.

Fact statements and decision prose remain data. They do not define rules,
permissions, tools, or executable commands. These checks do not establish prose
truth, secret-free prose, process isolation, or a secure history loader.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from . import contracts as c

MAX_CATALOG_FACTS = 4096
MAX_SOURCE_DEPTH = 64
ACCESS = {"visibility": c.enum("public", "npc", "gm"), "audience_ids": c.array(c.ID)}
OPTION = {"rule_id": c.ID, "npc_id": c.ID, "required_evidence_ids": c.array(c.ID),
          "changes": c.array(c.CHANGE), "scope": c.enum("private_npc", "public_stakes")}
POLICY = {"schema": c.enum("npc-policy-v1"), "campaign_id": c.ID, "head_hash": c.HASH,
          "npc_id": c.ID, "not_before_second": c.NAT, "expires_at_second": c.NAT,
          "options": c.array(OPTION)}
# Game-state proposals cannot change the controller's authority or configuration.
AUTHORITY_FIELDS = frozenset((
    "tool_permissions", "tools", "capabilities", "permissions", "rule_registry",
    "rules_version", "content_version", "engine_version", "seed", "seed_hex",
    "writer_epoch", "origin_epoch", "private_npc_fields", "credentials", "system_prompt",
))


class KnowledgeError(c.ContractError):
    pass


def _require(condition, message):
    if not condition:
        raise KnowledgeError(message)


def _shape(value, specification):
    try:
        c.shape(value, specification)
    except c.ContractError as exc:
        raise KnowledgeError(str(exc)) from exc


def _unique(values, label):
    _require(len(values) == len(set(values)), "Duplicate " + label + ".")


def _access_valid(record):
    _shape({key: record[key] for key in ACCESS}, ACCESS)
    _unique(record["audience_ids"], "audience ID")
    if record["visibility"] == "npc":
        _require(bool(record["audience_ids"]), "NPC-specific material needs an audience.")
    else:
        _require(not record["audience_ids"], "Public and GM material cannot have a conflicting audience list.")


def _can_access(record, role, recipient_id):
    if role == "steward":
        return True
    return record["visibility"] == "public" or (
        role == "npc" and record["visibility"] == "npc" and recipient_id in record["audience_ids"]
    )


def _catalogue(facts, sources):
    """Validate trusted input, resolve provenance, and reject cyclic derivations."""
    _require(type(facts) is list and len(facts) <= MAX_CATALOG_FACTS, "Fact catalogue exceeds its bound.")
    _require(type(sources) is dict and len(sources) <= MAX_CATALOG_FACTS, "Invalid source registry.")
    records, source_records = {}, {}
    for raw in facts:
        fact = c.normalize(deepcopy(raw))
        _shape(fact, c.FACT)
        _access_valid(fact)
        _unique(fact["source_ids"], "source ID")
        _require(fact["fact_id"] not in records, "Duplicate fact ID.")
        if fact["basis"] == "gm":
            _require(fact["visibility"] == "gm", "GM knowledge cannot be relabelled as an actor observation.")
        else:
            _require(bool(fact["source_ids"]), "An observation, message, or inference needs a source.")
        fact["source_ids"] = sorted(fact["source_ids"])
        fact["audience_ids"] = sorted(fact["audience_ids"])
        records[fact["fact_id"]] = fact
    for source_id, raw in sources.items():
        _shape(source_id, c.ID)
        source = c.normalize(deepcopy(raw))
        _shape(source, ACCESS)
        _access_valid(source)
        _require(source_id not in records, "Fact and source identifiers cannot collide.")
        source["audience_ids"] = sorted(source["audience_ids"])
        source_records[source_id] = source
    for fact in records.values():
        _require(all(s in records or s in source_records for s in fact["source_ids"]), "Unknown provenance source.")
    # Validate the complete dependency graph without recursion. A completed
    # node's longest path still counts when it is reused by a later fact.
    from collections import deque
    dependents = {key: [] for key in records}
    remaining, depths = {}, {}
    for fact_id, fact in records.items():
        dependencies = [key for key in fact["source_ids"] if key in records]
        remaining[fact_id] = len(dependencies)
        for source_id in dependencies:
            dependents[source_id].append(fact_id)
    ready = deque(key for key, count in remaining.items() if count == 0)
    while ready:
        fact_id = ready.popleft()
        depth = 1 + max((depths[key] for key in records[fact_id]["source_ids"] if key in records), default=0)
        _require(depth <= MAX_SOURCE_DEPTH, "Fact provenance exceeds its depth bound.")
        depths[fact_id] = depth
        for dependent in dependents[fact_id]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    _require(len(depths) == len(records), "Cyclic fact provenance.")
    return records, source_records


def build_packet(*, campaign_id, head_hash, recipient_role, recipient_id, facts,
                 sources, requested_ids=None):
    """Build packet-v1 using only accessible facts and accessible provenance.

    ``facts``, ``sources``, and optional ``requested_ids`` are controller inputs.
    A source registry entry gives access to a verified event/document identifier;
    it does not grant a tool capability. Requested inference sources are included
    as facts when applicable. Oversized packets fail instead of truncating.
    """
    _shape(campaign_id, c.ID)
    _shape(head_hash, c.HASH)
    _shape(recipient_role, c.enum("player", "npc", "steward"))
    _shape(recipient_id, c.ID)
    records, source_records = _catalogue(facts, sources)
    accessible = {}

    def visible(fact_id):
        if fact_id in accessible:
            return accessible[fact_id]
        fact = records[fact_id]
        result = _can_access(fact, recipient_role, recipient_id)
        if result:
            result = all(visible(source_id) if source_id in records else
                         _can_access(source_records[source_id], recipient_role, recipient_id)
                         for source_id in fact["source_ids"])
        accessible[fact_id] = result
        return result

    if requested_ids is None:
        requested = set(records)
    else:
        _shape(requested_ids, c.array(c.ID, MAX_CATALOG_FACTS))
        _unique(requested_ids, "requested fact ID")
        _require(set(requested_ids) <= set(records), "Unknown requested fact.")
        requested = set(requested_ids)
    selected = set()

    def include(fact_id):
        if fact_id in selected or not visible(fact_id):
            return
        selected.add(fact_id)
        for source_id in records[fact_id]["source_ids"]:
            if source_id in records:
                include(source_id)

    for fact_id in sorted(requested):
        include(fact_id)
    _require(len(selected) <= 256, "Knowledge packet exceeds 256 facts; use a trusted narrower selection.")
    packet = {"schema": "packet-v1", "campaign_id": campaign_id,
              "recipient_role": recipient_role, "recipient_id": recipient_id,
              "head_hash": head_hash, "facts": [deepcopy(records[key]) for key in sorted(selected)]}
    packet["packet_hash"] = c.hashed_record(packet, "packet_hash")
    c.packet_valid(packet)
    return packet


def validate_issued_packet(packet, *, campaign_id, head_hash, recipient_role,
                           recipient_id, facts, sources, requested_ids=None):
    """Rebuild a candidate against independent current context and selection.

    Do not derive these keyword arguments from the candidate packet. A valid
    self-hash is insufficient: the complete issued content must match.
    """
    c.packet_valid(packet)
    expected = build_packet(campaign_id=campaign_id, head_hash=head_hash,
                            recipient_role=recipient_role, recipient_id=recipient_id,
                            facts=facts, sources=sources, requested_ids=requested_ids)
    _require(c.canonical(packet) == c.canonical(expected), "Packet differs from independently issued knowledge.")
    return deepcopy(expected)


@dataclass(frozen=True)
class ProposalReview:
    """Immutable review inputs, not a commit, consent receipt, or tool token."""
    proposal_bytes: bytes
    option_bytes: bytes
    requires_public_stakes: bool

    def as_data(self):
        proposal = c.parse_json(self.proposal_bytes.decode("utf-8"))
        option = c.parse_json(self.option_bytes.decode("utf-8"))
        return {
            "schema": "npc-proposal-review-v1",
            "proposal_id": proposal["proposal_id"], "proposal_hash": c.digest(proposal),
            "packet_hash": proposal["packet_hash"], "npc_id": proposal["npc_id"],
            "rule_id": option["rule_id"], "evidence_ids": deepcopy(proposal["evidence_ids"]),
            "untrusted_decision": proposal["decision"],
            "validated_changes": deepcopy(option["changes"]),
            "requires_public_stakes": self.requires_public_stakes,
            "grants_tool_access": False,
        }


def _policy_valid(policy, campaign_id, head_hash, npc_id, now_seconds):
    _shape(policy, POLICY)
    _require(policy["campaign_id"] == campaign_id and policy["head_hash"] == head_hash,
             "Rule policy belongs to another campaign or history boundary.")
    _require(policy["npc_id"] == npc_id, "Rule policy belongs to another actor.")
    _require(policy["not_before_second"] <= now_seconds <= policy["expires_at_second"], "Rule policy is outside its trusted time window.")
    _unique([option["rule_id"] for option in policy["options"]], "policy rule ID")
    for option in policy["options"]:
        _require(option["npc_id"] == npc_id, "Rule option belongs to another actor.")
        _unique(option["required_evidence_ids"], "required evidence ID")
        _unique([(x["record_id"], x["field_id"]) for x in option["changes"]], "rule effect target")
        _require(all(change["field_id"] not in AUTHORITY_FIELDS for change in option["changes"]),
                 "NPC policies cannot change controller authority or configuration.")


def validate_proposal(proposal, issued_packet, *, campaign_id, head_hash,
                      now_seconds, state, policy, private_npc_fields=()):
    """Validate a model proposal against a trusted packet and finite rule policy.

    The caller retains the immutable issued packet and independently supplies
    current context. Each policy option must come from the deterministic rules,
    not model prose. Exactly one option is selected. Exact effects and current
    field preconditions must match. This function changes no state.

    Public effects must later enter accepted public stakes. Private effects are
    restricted to the proposing NPC's trusted private-field allowlist. Neither
    path executes a proposal or creates any tool/rule authority.
    """
    proposal, policy = c.normalize(deepcopy(proposal)), c.normalize(deepcopy(policy))
    _shape(campaign_id, c.ID)
    _shape(head_hash, c.HASH)
    _shape(now_seconds, c.NAT)
    _require(type(state) is dict and type(state.get("world")) is dict
             and "time_seconds" in state["world"], "Trusted state needs the canonical world clock.")
    _shape(state["world"]["time_seconds"], c.NAT)
    _require(state["world"]["time_seconds"] == now_seconds, "Proposal clock differs from trusted state.")
    c.packet_valid(issued_packet)
    _require(issued_packet["campaign_id"] == campaign_id and issued_packet["head_hash"] == head_hash,
             "Issued packet is not at the current trusted history boundary.")
    c.proposal_valid(proposal, issued_packet, now_seconds)
    _unique(proposal["evidence_ids"], "proposal evidence ID")
    _unique(proposal["rule_ids"], "proposal rule ID")
    _require(len(proposal["rule_ids"]) == 1, "Select exactly one trusted rule option.")
    _require(bool(proposal["evidence_ids"]), "An NPC proposal needs actor-accessible evidence.")
    npc_id = issued_packet["recipient_id"]
    _require(npc_id in state, "The proposing actor is absent from trusted state.")
    _policy_valid(policy, campaign_id, head_hash, npc_id, now_seconds)
    _require(proposal["valid_until_second"] <= policy["expires_at_second"], "Proposal extends beyond its trusted time window.")
    option = next((x for x in policy["options"] if x["rule_id"] == proposal["rule_ids"][0]), None)
    _require(option is not None, "Unknown or unauthorized rule option.")
    _require(set(option["required_evidence_ids"]) <= set(proposal["evidence_ids"]), "Required rule evidence is missing.")
    _require(c.canonical(proposal["proposed_changes"]) == c.canonical(option["changes"]),
             "Proposed effects differ from the trusted rule option.")
    fields = set()
    for pair in private_npc_fields:
        _require(type(pair) in (tuple, list) and len(pair) == 2, "Invalid private field registry.")
        _shape(pair[0], c.ID)
        _shape(pair[1], c.ID)
        _require(pair[0].startswith("npc-") and pair[1].startswith("private_"), "Private fields need an NPC owner and private prefix.")
        fields.add(tuple(pair))
    if option["scope"] == "private_npc":
        for change in option["changes"]:
            _require(change["record_id"] == npc_id, "A private proposal cannot change another actor.")
            _require((change["record_id"], change["field_id"]) in fields, "Private effect is not allowlisted.")
    # Exact canonical preconditions also distinguish booleans from integers.
    c.apply_changes(state, option["changes"])
    return ProposalReview(c.canonical(proposal), c.canonical(option), option["scope"] == "public_stakes")
