"""Single-host campaign controller with durable, resumable publication."""
from __future__ import annotations

from copy import deepcopy
import sqlite3

from .contracts import (ContractError, action_valid, canonical, compose_changes,
                        die, digest, envelope_valid, hashed_record, normalize,
                        parse_json, precommit_envelope_valid, MAX_ENVELOPE_BYTES)
from .storage import CampaignStore, FileRemote, RemotePending, WriterBusy
from .rules import PUBLIC_PC_FIELDS, PUBLIC_WORLD_FIELDS, PUBLIC_NPC_FIELDS
from .rulesets import get_rules, for_context


RULES_VERSION = "rules-v1"
CONTENT_VERSION = "content-initial-six-v1"
ENGINE_VERSION = "engine-v1"
ZERO_HASH = "0" * 64


class ControllerError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise ControllerError(code, message)


def encoded(value):
    return canonical(value).decode("utf-8")


class Controller:
    """The normal action validator is the rules engine, never generated prose.

    action_validator and fault_hook are explicit dependency-injection points for
    tests. Runtime callers must retain the default rules validator.
    """

    def __init__(self, path, remote, *, action_validator=None, fault_hook=None):
        self.store = CampaignStore(path)
        self.remote = remote
        self.action_validator = action_validator
        self.fault_hook = fault_hook
        if isinstance(remote, FileRemote):
            local, other = self.store.directory, remote.directory
            require(local != other and local not in other.parents and other not in local.parents,
                    "INVALID_SCHEMA", "Local and simulated remote stores must be separate.")

    def _fault(self, phase):
        if self.fault_hook:
            self.fault_hook(phase)

    def _validate_action(self, action, context):
        try:
            action_valid(action)
            if self.action_validator is not None:
                self.action_validator(action, context["state"], context["head_hash"])
            else:
                require(all(action[key] == context[key] for key in
                            ("rules_version", "content_version", "engine_version")),
                        "UNSUPPORTED_VERSION", "The action belongs to another rules version.")
                for_context(context).validate_action(action, context["state"], context["head_hash"])
        except (ContractError, ValueError, KeyError, TypeError) as exc:
            raise ControllerError("INVALID_SCHEMA", "The action does not match the validated rules.") from exc

    def _genesis(self, db):
        return self.store.get(db, "genesis")

    def _context(self, db, snapshot=None):
        genesis = self._genesis(db)
        require(genesis is not None, "RECOVERY_REQUIRED", "The campaign needs initialization or recovery.")
        require(self.store.get(db, "registration_path") == str(self.store.directory),
                "WRITER_FENCED", "This database belongs to another registered controller path.")
        snapshot = snapshot or self.store.get(db, "current")
        return {**deepcopy(snapshot), "campaign_id": genesis["campaign_id"],
                "rules_version": genesis["rules_version"], "content_version": genesis["content_version"],
                "engine_version": genesis["engine_version"], "origin_epoch": genesis["origin_epoch"],
                "seed": bytes.fromhex(genesis["seed_hex"]),
                "private_npc_fields": {tuple(pair) for pair in genesis["private_npc_fields"]}}

    def _validate_genesis(self, genesis):
        require(len(canonical(genesis)) <= MAX_ENVELOPE_BYTES,
                "INVALID_SCHEMA", "Genesis exceeds the 32 KiB remote record limit.")
        expected = {"schema", "campaign_id", "rules_version", "content_version", "engine_version",
                    "origin_epoch", "seed_hex", "state", "private_npc_fields", "genesis_hash"}
        require(isinstance(genesis, dict) and set(genesis) == expected,
                "INVALID_SCHEMA", "The genesis record is incomplete or unsupported.")
        require(genesis["schema"] == "genesis-v1" and genesis["origin_epoch"] == 1,
                "UNSUPPORTED_VERSION", "Genesis administration is unsupported.")
        try:
            engine = get_rules(genesis["rules_version"], genesis["content_version"], genesis["engine_version"])
        except (ContractError, ImportError) as exc:
            raise ControllerError("UNSUPPORTED_VERSION", "The required campaign source version is unavailable.") from exc
        require(genesis["genesis_hash"] == hashed_record(genesis, "genesis_hash"),
                "HASH_MISMATCH", "The genesis hash does not match.")
        try:
            seed = bytes.fromhex(genesis["seed_hex"])
        except (ValueError, TypeError) as exc:
            raise ControllerError("INVALID_SCHEMA", "The campaign seed is invalid.") from exc
        require(len(seed) == 32 and len(genesis["seed_hex"]) == 64,
                "INVALID_SCHEMA", "The campaign seed is invalid.")
        require(isinstance(genesis["state"], dict) and
                all(isinstance(genesis["state"].get(k), dict) for k in ("pc", "world")),
                "INVALID_SCHEMA", "The initial campaign state is incomplete.")
        clock = genesis["state"]["world"].get("time_seconds")
        require(type(clock) is int and clock >= 0, "INVALID_SCHEMA", "The fictional clock is invalid.")
        for pair in genesis["private_npc_fields"]:
            require(isinstance(pair, list) and len(pair) == 2 and
                    all(isinstance(item, str) for item in pair) and pair[0].startswith("npc-") and
                    pair[1].startswith("private_") and pair[0] in genesis["state"] and
                    pair[1] in genesis["state"][pair[0]],
                    "INVALID_SCHEMA", "The private NPC field registry is invalid.")
        if self.action_validator is None:
            try:
                engine.validate_state(genesis["state"])
                potential, counter, _ = die(seed, genesis["campaign_id"], "genesis", "potential/die-0", 3)
                require(genesis["state"]["pc"]["potential"] == potential + 7 and
                        genesis["state"]["pc"]["potential_die"] == {"value": potential, "rejection_counter": counter},
                        "HASH_MISMATCH", "The hidden genesis roll does not replay.")
            except (ContractError, KeyError, TypeError) as exc:
                raise ControllerError("INVALID_SCHEMA", "The initial state violates the pinned rules.") from exc

    def initialize(self, campaign_id, state, seed, *, rules_version=RULES_VERSION,
                   content_version=CONTENT_VERSION, engine_version=ENGINE_VERSION,
                   private_npc_fields=None):
        require(type(seed) is bytes and len(seed) == 32, "INVALID_SCHEMA", "A 32-byte campaign seed is required.")
        if private_npc_fields is None:
            engine = get_rules(rules_version, content_version, engine_version)
            private_npc_fields = tuple(pair for pair in getattr(engine, "PRIVATE_NPC_FIELDS", ())
                                       if pair[0] in state and pair[1] in state[pair[0]])
        genesis = normalize({"schema": "genesis-v1", "campaign_id": campaign_id,
                             "rules_version": rules_version, "content_version": content_version,
                             "engine_version": engine_version, "origin_epoch": 1, "seed_hex": seed.hex(),
                             "state": deepcopy(state), "private_npc_fields": [list(p) for p in sorted(private_npc_fields)]})
        genesis["genesis_hash"] = hashed_record(genesis, "genesis_hash")
        self._validate_genesis(genesis)
        try:
            with self.store.locked() as db:
                existing = self._genesis(db)
                require(existing is None or canonical(existing) == canonical(genesis),
                        "ACTION_CONFLICT", "This local campaign already has different genesis data.")
                if existing is not None:
                    self._context(db)
                if existing is None:
                    with self.store.transaction(db):
                        self.store.set(db, "registration_path", str(self.store.directory))
                        self.store.set(db, "genesis", genesis)
                        self.store.set(db, "current", {"sequence": 0, "head_hash": ZERO_HASH, "state": state})
                        self.store.set(db, "initialized", False)
                if not self.store.get(db, "initialized", False):
                    self._publish_genesis(db)
                return self._status(db)
        except (RemotePending, WriterBusy):
            return self._pending_response(campaign_id)

    def _publish_genesis(self, db):
        genesis = self._genesis(db)
        self.remote.put_genesis(genesis)
        require(canonical(self.remote.get_genesis()) == canonical(genesis),
                "HASH_MISMATCH", "Remote genesis verification failed.")
        projections = self._projections(self._context(db))
        for kind, data in projections.items():
            self.remote.write_projection(kind, data)
            require(canonical(self.remote.read_projection(kind)) == canonical(data),
                    "PROJECTION_PENDING", "An initial projection did not verify.")
        with self.store.transaction(db):
            self.store.set(db, "initialized", True)
            self.store.set(db, "public", projections)

    def _row(self, db, action_id):
        return db.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()

    def _pending(self, db):
        rows = db.execute("SELECT * FROM actions WHERE phase!='DELIVERED' ORDER BY sequence").fetchall()
        require(len(rows) <= 1, "RECOVERY_REQUIRED", "Multiple local pending actions require review.")
        return rows[0] if rows else None

    def _set_phase(self, db, action_id, phase, **values):
        allowed = {"envelope_json", "selected_page_id"}
        require(set(values) <= allowed, "INVALID_SCHEMA", "Unsupported local phase update.")
        fields = {"phase": phase, **values}
        with self.store.transaction(db):
            db.execute("UPDATE actions SET " + ",".join(k + "=?" for k in fields) + " WHERE action_id=?",
                       (*fields.values(), action_id))
        self._fault(phase)

    def _check_boundary(self, db):
        require(canonical(self.remote.get_genesis()) == canonical(self._genesis(db)),
                "HASH_MISMATCH", "Remote genesis differs from the registered campaign.")
        rows = {row["action_id"]: row for row in db.execute("SELECT * FROM actions")}
        committed_ids = set()
        for candidate in self.remote.list_candidates():
            self._candidate_shape(candidate)
            envelope = candidate["envelope"]
            action_id = envelope["event"].get("action_id")
            require(action_id in rows and rows[action_id]["envelope_json"] is not None and
                    canonical(envelope) == canonical(parse_json(rows[action_id]["envelope_json"])),
                    "FORK_DETECTED", "Remote history differs from local verified history.")
            if candidate["status"] == "COMMITTED":
                committed_ids.add(action_id)
        expected = {key for key, row in rows.items() if row["phase"] in
                    ("COMMITTED", "PROJECTING", "READY", "DELIVERED")}
        require(expected <= committed_ids, "RECOVERY_REQUIRED", "Remote history is incomplete.")
        projections = self.store.get(db, "public")
        for kind, data in projections.items():
            require(canonical(self.remote.read_projection(kind)) == canonical(data),
                    "PRECONDITION_FAILED", "A managed projection changed outside the controller.")

    def execute(self, action, narrations):
        try:
            action = normalize(action)
            with self.store.locked() as db:
                require(self.store.get(db, "initialized", False), "RECOVERY_REQUIRED", "Initialize or recover the campaign first.")
                require(not self.store.get(db, "maintenance_read_only", False),
                        "WRITER_FENCED", "Reconstructed campaigns are read-only until a supported fencing and transfer procedure exists.")
                require(not self.store.get(db, "recovery_blocked", False),
                        "RECOVERY_REQUIRED", "Unresolved remote preparation requires operator review.")
                action_valid(action)
                context = self._context(db)
                existing = self._row(db, action["action_id"])
                if existing is not None:
                    require(existing["action_hash"] == digest(action), "ACTION_CONFLICT", "This action ID already has different accepted input.")
                    if existing["phase"] == "DELIVERED":
                        self._check_boundary(db)
                        return self._result(db, existing, narration=True)
                    return self._advance(db, existing)
                pending = self._pending(db)
                require(pending is None, "RECOVERY_REQUIRED", "Finish the pending action before accepting another.")
                require(action["campaign_id"] == context["campaign_id"] and
                        action["expected_head_hash"] == context["head_hash"],
                        "STALE_HEAD", "The action belongs to a different campaign boundary.")
                self._validate_action(action, context)
                require(isinstance(narrations, dict) and narrations and
                        set(narrations) <= {"clean", "costly", "setback", "routine"} and
                        all(isinstance(v, str) and 1 <= len(v) <= 12000 for v in narrations.values()),
                        "INVALID_SCHEMA", "Provide bounded narration for each possible outcome.")
                required_bands = {"routine"} if action["stakes"]["check"] is None else {"clean", "costly", "setback"}
                require(required_bands <= set(narrations), "INVALID_SCHEMA", "Narration is missing a required outcome band.")
                if self.action_validator is None:
                    require(all(text == action["stakes"]["bands"]["clean" if band == "routine" else band]["summary"]
                                for band, text in narrations.items()),
                            "INVALID_SCHEMA", "This runtime releases only the validated outcome summaries.")
                self._check_boundary(db)
                snapshot = self.store.get(db, "current")
                with self.store.transaction(db):
                    db.execute("INSERT INTO actions(action_id,action_hash,sequence,action_json,narrations_json,"
                               "context_json,phase,receipt_id) VALUES(?,?,?,?,?,?,?,?)",
                               (action["action_id"], digest(action), context["sequence"] + 1, encoded(action),
                                encoded(narrations), encoded(snapshot), "ACCEPTED", "receipt-" + digest(action)[:32]))
                self._fault("ACCEPTED")
                return self._advance(db, self._row(db, action["action_id"]))
        except (RemotePending, WriterBusy):
            return self._pending_response(action.get("campaign_id"), action.get("action_id"))
        except ContractError as exc:
            raise ControllerError("INVALID_SCHEMA", "The action or event failed contract validation.") from exc

    def _resolve(self, db, row):
        action = parse_json(row["action_json"])
        context = self._context(db, parse_json(row["context_json"]))
        self._validate_action(action, context)
        dice = []
        for request in action["stakes"]["rolls"]:
            value, counter, _ = die(context["seed"], action["campaign_id"], action["action_id"], request["key"], request["sides"])
            dice.append({**request, "value": value, "rejection_counter": counter})
        check = action["stakes"]["check"]
        outcome = "routine"
        if check:
            gap = check["difficulty"] - (sum(r["value"] for r in dice) + check["attribute_rating"] + check["skill_rating"] + check["modifier"])
            outcome = "clean" if gap <= 0 else "costly" if gap <= 3 else "setback"
        narrations = parse_json(row["narrations_json"])
        require(outcome in narrations, "INVALID_SCHEMA", "The resolved outcome lacks stored narration.")
        band = action["stakes"]["bands"]["clean" if outcome == "routine" else outcome]
        changes = compose_changes(action["stakes"]["upfront_changes"], band["changes"], action["auxiliary_changes"])
        from .contracts import apply_changes
        after = apply_changes(context["state"], changes)
        event = {"schema": "event-v1", "campaign_id": action["campaign_id"], "action_id": action["action_id"],
                 "sequence": row["sequence"], "origin_epoch": context["origin_epoch"], "parent_hash": context["head_hash"],
                 "rules_version": context["rules_version"], "content_version": context["content_version"],
                 "engine_version": context["engine_version"], "accepted_action_hash": digest(action),
                 "stakes_hash": action["stakes_hash"], "before_state_hash": digest(context["state"]),
                 "after_state_hash": digest(after), "dice": dice, "outcome": outcome, "changes": changes,
                 "npc_proposal_hashes": action["npc_proposal_hashes"], "public_narration": narrations[outcome],
                 "revealed_fact_ids": []}
        event["event_hash"] = hashed_record(event, "event_hash")
        envelope = {"schema": "remote-envelope-v1", "accepted_action": action, "event": event}
        envelope["envelope_hash"] = hashed_record(envelope, "envelope_hash")
        precommit_envelope_valid(envelope, action, context)
        self._set_phase(db, row["action_id"], "RESOLVED", envelope_json=encoded(envelope))

    def _candidate_shape(self, candidate):
        require(isinstance(candidate, dict) and set(candidate) == {"page_id", "status", "envelope"} and
                isinstance(candidate["page_id"], str) and candidate["status"] in ("PREPARED", "COMMITTED") and
                isinstance(candidate["envelope"], dict) and isinstance(candidate["envelope"].get("event"), dict),
                "INVALID_SCHEMA", "A remote candidate is incomplete.")

    def _verify_candidate(self, candidate, row, context, *, committed=False):
        self._candidate_shape(candidate)
        expected = parse_json(row["envelope_json"])
        require(candidate["page_id"] == row["selected_page_id"], "ACTION_CONFLICT", "The remote response identifies a different page.")
        require(canonical(candidate["envelope"]) == canonical(expected),
                "HASH_MISMATCH", "The selected remote envelope changed.")
        if committed:
            require(candidate["status"] == "COMMITTED", "REMOTE_UNCERTAIN", "The selected marker is not verified.")
        self._validate_release(candidate["envelope"])
        return precommit_envelope_valid(candidate["envelope"], parse_json(row["action_json"]), context)

    def _validate_release(self, envelope):
        if self.action_validator is None:
            event, action = envelope["event"], envelope["accepted_action"]
            band = "clean" if event["outcome"] == "routine" else event["outcome"]
            require(event["public_narration"] == action["stakes"]["bands"][band]["summary"],
                    "INVALID_SCHEMA", "Stored narration differs from the validated outcome summary.")

    def _advance(self, db, row):
        action_id = row["action_id"]
        if row["phase"] == "ACCEPTED":
            self._resolve(db, row)
            row = self._row(db, action_id)
        context = self._context(db, parse_json(row["context_json"]))
        envelope = parse_json(row["envelope_json"])
        precommit_envelope_valid(envelope, parse_json(row["action_json"]), context)
        self._validate_release(envelope)
        if row["phase"] == "RESOLVED":
            matches = []
            for candidate in self.remote.list_candidates():
                self._candidate_shape(candidate)
                if candidate["envelope"]["event"].get("action_id") == action_id:
                    require(canonical(candidate["envelope"]) == canonical(envelope),
                            "ACTION_CONFLICT", "This action has conflicting remote candidates.")
                    matches.append(candidate)
            committed = [c for c in matches if c["status"] == "COMMITTED"]
            chosen = sorted(committed or matches, key=lambda c: c["page_id"])
            page_id = chosen[0]["page_id"] if chosen else self.remote.create_prepared(envelope)
            self._set_phase(db, action_id, "PREPARED", selected_page_id=page_id)
            row = self._row(db, action_id)
        if row["phase"] == "PREPARED":
            self._verify_candidate(self.remote.read_candidate(row["selected_page_id"]), row, context)
            self._set_phase(db, action_id, "SELECTED")
            row = self._row(db, action_id)
        if row["phase"] in ("SELECTED", "COMMIT_UNCERTAIN"):
            candidate = self.remote.read_candidate(row["selected_page_id"])
            self._verify_candidate(candidate, row, context)
            if candidate["status"] != "COMMITTED":
                self._set_phase(db, action_id, "COMMIT_UNCERTAIN")
                self.remote.commit(row["selected_page_id"])
                candidate = self.remote.read_candidate(row["selected_page_id"])
            after = self._verify_candidate(candidate, row, context, committed=True)
            current = self.store.get(db, "current")
            require(current["head_hash"] == context["head_hash"], "STALE_HEAD", "Local state advanced unexpectedly.")
            with self.store.transaction(db):
                self.store.set(db, "current", {"sequence": envelope["event"]["sequence"],
                                               "head_hash": envelope["event"]["event_hash"], "state": after})
                db.execute("UPDATE actions SET phase='COMMITTED' WHERE action_id=?", (action_id,))
            self._fault("COMMITTED")
            row = self._row(db, action_id)
        if row["phase"] in ("COMMITTED", "PROJECTING"):
            self._set_phase(db, action_id, "PROJECTING")
            projections = self._projections(self._context(db))
            for kind, data in projections.items():
                if not self.store.get(db, "maintenance_read_only", False):
                    self.remote.write_projection(kind, data)
                require(canonical(self.remote.read_projection(kind)) == canonical(data),
                        "PROJECTION_PENDING", "A saved projection has not verified.")
                self._fault("PROJECTED_" + kind.upper())
            with self.store.transaction(db):
                self.store.set(db, "public", projections)
                db.execute("UPDATE actions SET phase='READY' WHERE action_id=?", (action_id,))
            self._fault("READY")
            row = self._row(db, action_id)
        if row["phase"] == "READY":
            self._set_phase(db, action_id, "DELIVERED")
            row = self._row(db, action_id)
        require(row["phase"] == "DELIVERED", "RECOVERY_REQUIRED", "The action phase requires review.")
        return self._result(db, row, narration=True)

    @staticmethod
    def _projections(context):
        result = {}
        engine = for_context(context)
        view = engine.public_state(context["state"]) if hasattr(engine, "public_state") else None
        for kind, record, allowlist in (("player", "pc", PUBLIC_PC_FIELDS), ("world", "world", PUBLIC_WORLD_FIELDS)):
            fields = deepcopy(view[record]) if view is not None else {
                k: deepcopy(v) for k, v in context["state"][record].items() if k in allowlist}
            data = {"campaign_id": context["campaign_id"], "revision": context["head_hash"],
                    "sequence": context["sequence"], "fields": fields}
            data["projection_hash"] = digest(data)
            result[kind] = data
        public_npcs = deepcopy(view["npcs"]) if view is not None else {
            key: {field: deepcopy(value) for field, value in record.items() if field in PUBLIC_NPC_FIELDS}
            for key, record in context["state"].items() if key.startswith("npc-")}
        result["world"]["npcs"] = public_npcs
        result["world"]["projection_hash"] = hashed_record(result["world"], "projection_hash")
        return result

    def _restore(self, db):
        genesis = self.remote.get_genesis()
        self._validate_genesis(genesis)
        candidates = self.remote.list_candidates()
        for candidate in candidates:
            self._candidate_shape(candidate)
        committed = [c for c in candidates if c["status"] == "COMMITTED"]
        by_sequence = {}
        for candidate in committed:
            sequence = candidate["envelope"]["event"].get("sequence")
            require(type(sequence) is int and sequence >= 1, "INVALID_SCHEMA", "A remote sequence is invalid.")
            by_sequence.setdefault(sequence, []).append(candidate)
        snapshot = {"sequence": 0, "head_hash": ZERO_HASH, "state": deepcopy(genesis["state"])}
        restored = []
        seen_actions = set()
        # Nothing is adopted until the complete returned history has validated.
        with self.store.transaction(db):
            self.store.set(db, "registration_path", str(self.store.directory))
            self.store.set(db, "genesis", genesis)
            for sequence in sorted(by_sequence):
                copies = by_sequence[sequence]
                first = copies[0]
                envelope = first["envelope"]
                require(all(canonical(c["envelope"]) == canonical(envelope) for c in copies),
                        "FORK_DETECTED", "Conflicting remote successors require review.")
                action = envelope.get("accepted_action")
                require(isinstance(action, dict), "INVALID_SCHEMA", "Remote history lacks its accepted action.")
                require(action.get("action_id") not in seen_actions, "ACTION_CONFLICT", "A remote action ID occurs at multiple boundaries.")
                context = self._context(db, snapshot)
                self._validate_action(action, context)
                after = envelope_valid(envelope, context)
                self._validate_release(envelope)
                seen_actions.add(action["action_id"])
                restored.append((action, envelope, deepcopy(snapshot), first["page_id"]))
                snapshot = {"sequence": sequence, "head_hash": envelope["event"]["event_hash"], "state": after}
            unresolved = []
            known = {action["action_id"]: envelope for action, envelope, _, _ in restored}
            for candidate in candidates:
                if candidate["status"] == "PREPARED":
                    envelope = candidate["envelope"]
                    action_id = envelope["event"].get("action_id")
                    if action_id in known:
                        require(canonical(envelope) == canonical(known[action_id]),
                                "ACTION_CONFLICT", "A prepared copy conflicts with committed history.")
                    else:
                        unresolved.append(candidate)
            for index, (action, envelope, before, page_id) in enumerate(restored):
                phase = "COMMITTED" if index == len(restored) - 1 else "DELIVERED"
                db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (action["action_id"], digest(action), envelope["event"]["sequence"], encoded(action),
                            encoded({envelope["event"]["outcome"]: envelope["event"]["public_narration"]}),
                            encoded(before), encoded(envelope), phase, page_id, "receipt-" + digest(action)[:32]))
            self.store.set(db, "current", snapshot)
            self.store.set(db, "initialized", True)
            self.store.set(db, "maintenance_read_only", True)
            self.store.set(db, "recovery_blocked", bool(unresolved))
            # Last released state is unknown. Expose only the genesis until projections verify.
            initial = {"sequence": 0, "head_hash": ZERO_HASH, "state": genesis["state"]}
            self.store.set(db, "public", self._projections(self._context(db, initial)))
        require(not unresolved, "RECOVERY_REQUIRED", "Unresolved remote preparation requires operator review and fencing.")
        if not restored:
            for kind, data in self._projections(self._context(db)).items():
                require(canonical(self.remote.read_projection(kind)) == canonical(data),
                        "PROJECTION_PENDING", "The recovered public projection has not verified.")

    def recover(self):
        try:
            with self.store.locked() as db:
                if self._genesis(db) is None:
                    self._restore(db)
                elif not self.store.get(db, "initialized", False):
                    self._context(db)
                    self._publish_genesis(db)
                self._context(db)
                require(not self.store.get(db, "recovery_blocked", False),
                        "RECOVERY_REQUIRED", "Unresolved remote preparation requires operator review and fencing.")
                row = self._pending(db)
                if row is not None:
                    return self._advance(db, row)
                self._check_boundary(db)
                return self._status(db, narration=True)
        except (RemotePending, WriterBusy):
            return self._pending_response()
        except ContractError as exc:
            raise ControllerError("HASH_MISMATCH", "Remote replay failed validation.") from exc

    def _result(self, db, row, *, narration=False):
        envelope = parse_json(row["envelope_json"]) if row["envelope_json"] else None
        ready = row["phase"] in ("READY", "DELIVERED")
        return {"schema": "response-v1", "status": "OK" if ready else "PENDING",
                "campaign_id": self._genesis(db)["campaign_id"], "action_id": row["action_id"],
                "phase": row["phase"], "event_hash": envelope["event"]["event_hash"] if envelope else None,
                "narration": envelope["event"]["public_narration"] if ready and narration else None,
                "receipt_id": row["receipt_id"] if ready else None,
                "error": None if ready else {"code": "PROJECTION_PENDING" if row["phase"] in ("COMMITTED", "PROJECTING") else "REMOTE_UNCERTAIN",
                                              "public_message": "The action is saved locally and awaits verified publication.",
                                              "retryable": True, "retry_at_ms": None}}

    def _status(self, db, *, narration=False):
        genesis = self._genesis(db)
        if self.store.get(db, "recovery_blocked", False):
            return {"schema": "response-v1", "status": "BLOCKED", "campaign_id": genesis["campaign_id"],
                    "action_id": None, "phase": None, "event_hash": None, "narration": None, "receipt_id": None,
                    "error": {"code": "RECOVERY_REQUIRED", "public_message": "Unresolved remote preparation requires operator review and fencing.",
                              "retryable": False, "retry_at_ms": None}}
        row = self._pending(db)
        if row is None:
            row = db.execute("SELECT * FROM actions ORDER BY sequence DESC LIMIT 1").fetchone()
        if row is not None:
            response = self._result(db, row, narration=narration)
            if not narration and self.store.get(db, "maintenance_read_only", False):
                response.update(status="BLOCKED", narration=None,
                                error={"code": "WRITER_FENCED", "public_message": "Reconstructed campaign: read-only maintenance. Writer transfer is unsupported.",
                                       "retryable": False, "retry_at_ms": None})
            return response
        if genesis and (not self.store.get(db, "initialized", False) or self.store.get(db, "recovery_blocked", False)):
            return {"schema": "response-v1", "status": "BLOCKED" if self.store.get(db, "recovery_blocked", False) else "PENDING",
                    "campaign_id": genesis["campaign_id"], "action_id": None, "phase": None,
                    "event_hash": None, "narration": None, "receipt_id": None,
                    "error": {"code": "RECOVERY_REQUIRED" if self.store.get(db, "recovery_blocked", False) else "REMOTE_UNCERTAIN",
                              "public_message": "Initialization or recovery needs completion.",
                              "retryable": not self.store.get(db, "recovery_blocked", False), "retry_at_ms": None}}
        if self.store.get(db, "maintenance_read_only", False):
            return {"schema": "response-v1", "status": "BLOCKED", "campaign_id": genesis["campaign_id"],
                    "action_id": None, "phase": None, "event_hash": None, "narration": None, "receipt_id": None,
                    "error": {"code": "WRITER_FENCED", "public_message": "Reconstructed campaign: read-only maintenance. Writer transfer is unsupported.",
                              "retryable": False, "retry_at_ms": None}}
        return {"schema": "response-v1", "status": "OK", "campaign_id": genesis["campaign_id"] if genesis else "uninitialized",
                "action_id": None, "phase": None, "event_hash": None, "narration": None, "receipt_id": None, "error": None}

    def _pending_response(self, campaign_id=None, action_id=None):
        try:
            with self.store.locked() as db:
                status = self._status(db)
                if status["status"] == "PENDING":
                    return status
                campaign_id = campaign_id or status["campaign_id"]
        except WriterBusy:
            pass
        return {"schema": "response-v1", "status": "PENDING", "campaign_id": campaign_id or "uninitialized",
                "action_id": action_id, "phase": None, "event_hash": None, "narration": None, "receipt_id": None,
                "error": {"code": "REMOTE_UNCERTAIN", "public_message": "The operation awaits verified completion.",
                          "retryable": True, "retry_at_ms": None}}

    def public_status(self):
        try:
            with self.store.locked() as db:
                return self._status(db)
        except WriterBusy:
            return self._pending_response()

    def public_packet(self):
        with self.store.locked() as db:
            public = self.store.get(db, "public")
            require(public is not None, "RECOVERY_REQUIRED", "No verified public packet is available.")
            return {"campaign_id": self._genesis(db)["campaign_id"], "head_hash": public["player"]["revision"],
                    "sequence": public['player']['sequence'],
                    "player": public["player"]["fields"], "world": public["world"]["fields"],
                    "npcs": public["world"].get("npcs", {}),
                    "status": self._status(db)}

    def public_course(self, course_id):
        """Read details at the verified public head, including during a pending save."""
        from . import progression
        with self.store.locked() as db:
            public=self.store.get(db,'public')
            require(public is not None,'RECOVERY_REQUIRED','No verified public record is available.')
            snapshot=self.store.get(db,'current')
            if snapshot['head_hash'] != public['player']['revision']:
                row=self._pending(db)
                require(row is not None,'RECOVERY_REQUIRED','The public course boundary needs recovery.')
                snapshot=parse_json(row['context_json'])
            require(snapshot['head_hash']==public['player']['revision'],'RECOVERY_REQUIRED','The public course boundary differs.')
            require('progression' in snapshot['state'],'INVALID_SCHEMA','Course details require the full ruleset.')
            return {'campaign_id':self._genesis(db)['campaign_id'],'head_hash':snapshot['head_hash'],
                    'sequence':snapshot['sequence'],'time_seconds':snapshot['state']['world']['time_seconds'],
                    'course':progression.course_detail(snapshot['state'],course_id)}

    def trusted_state(self):
        """Private engine input. Never print this value in a public CLI response."""
        with self.store.locked() as db:
            return deepcopy(self._context(db)["state"])

    def rules_engine(self):
        """Return the installed engine pinned by this campaign's genesis."""
        with self.store.locked() as db:
            return for_context(self._context(db))
