"""One PostgreSQL authority for sessions, immutable turns, and checkpoints."""
import hashlib
import hmac
import json
import secrets
import uuid
from copy import deepcopy
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import rules

_NEW_SESSION = object()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def secret_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str):
        raise Problem(422, "INVALID_ID", "This request needs a valid identifier.")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise Problem(422, "INVALID_ID", "This request needs a valid identifier.") from None
    if str(parsed) != value:
        raise Problem(422, "INVALID_ID", "This request needs a canonical identifier.")
    return value


class Problem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_players (
    id uuid PRIMARY KEY, recovery_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS mobile_sessions (
    token_hash text PRIMARY KEY, player_id uuid NOT NULL REFERENCES mobile_players(id),
    csrf_token text NOT NULL, expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days'
);
CREATE TABLE IF NOT EXISTS mobile_campaigns (
    id uuid PRIMARY KEY, player_id uuid NOT NULL REFERENCES mobile_players(id),
    creation_request uuid NOT NULL, name text NOT NULL, state jsonb NOT NULL,
    seed bytea NOT NULL, revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    head text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(player_id, creation_request)
);
ALTER TABLE mobile_campaigns ADD COLUMN IF NOT EXISTS player_notes text NOT NULL DEFAULT '';
ALTER TABLE mobile_campaigns ADD COLUMN IF NOT EXISTS notes_version bigint NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS mobile_actions (
    campaign_id uuid NOT NULL REFERENCES mobile_campaigns(id), action_id uuid NOT NULL,
    revision bigint NOT NULL CHECK (revision > 0), request_hash text NOT NULL,
    event jsonb NOT NULL, response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(campaign_id, action_id), UNIQUE(campaign_id, revision)
);
CREATE TABLE IF NOT EXISTS mobile_rate_limits (
    bucket text PRIMARY KEY, starts_at timestamptz NOT NULL DEFAULT now(), count integer NOT NULL
);
CREATE TABLE IF NOT EXISTS mobile_gm_budget (
    id text PRIMARY KEY CHECK (id = 'bounded-pilot-v1'),
    reserved_requests bigint NOT NULL CHECK (reserved_requests >= 0),
    reserved_micro_usd bigint NOT NULL CHECK (reserved_micro_usd >= 0)
);
CREATE TABLE IF NOT EXISTS mobile_gm_requests (
    campaign_id uuid NOT NULL REFERENCES mobile_campaigns(id), request_id uuid NOT NULL,
    expected_revision bigint NOT NULL CHECK (expected_revision >= 0),
    request_hash text NOT NULL, prompt text NOT NULL, public_state jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('prepared','completed','failed','unknown')),
    reserved_micro_usd bigint NOT NULL CHECK (reserved_micro_usd > 0),
    result jsonb, usage jsonb, error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '45 seconds',
    finished_at timestamptz,
    PRIMARY KEY(campaign_id, request_id)
);
ALTER TABLE mobile_gm_requests ADD COLUMN IF NOT EXISTS error_code text;
CREATE INDEX IF NOT EXISTS mobile_campaign_owner ON mobile_campaigns(player_id, updated_at);
"""


class Store:
    def __init__(self, url, *, gm_policy=None):
        if not url:
            raise RuntimeError("DATABASE_URL is required; there is no local-file fallback")
        self.url = url
        if gm_policy is not None and (
                type(gm_policy) is not dict or set(gm_policy) != {"max_requests", "budget_micro_usd", "reservation_micro_usd"} or
                any(type(value) is not int or not 1 <= value <= 2**53-1 for value in gm_policy.values())):
            raise ValueError("Invalid bounded GM policy")
        self.gm_policy = deepcopy(gm_policy)

    def connect(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10,
                              options="-c statement_timeout=15000 -c lock_timeout=5000")

    def initialize(self):
        with self.connect() as db:
            # Serialize first deployment when several workers boot together.
            db.execute("SELECT pg_advisory_xact_lock(873024104)")
            db.execute(SCHEMA)

    def health(self):
        with self.connect() as db:
            return db.execute("SELECT 1 AS ready").fetchone()["ready"] == 1

    def rate_limit(self, bucket, maximum, seconds):
        with self.connect() as db:
            row = db.execute("""
                INSERT INTO mobile_rate_limits(bucket,count) VALUES (%s,1)
                ON CONFLICT(bucket) DO UPDATE SET
                  count = CASE WHEN mobile_rate_limits.starts_at < now() - (%s * interval '1 second')
                               THEN 1 ELSE mobile_rate_limits.count + 1 END,
                  starts_at = CASE WHEN mobile_rate_limits.starts_at < now() - (%s * interval '1 second')
                                  THEN now() ELSE mobile_rate_limits.starts_at END
                RETURNING count
            """, (bucket, seconds, seconds)).fetchone()
        if row["count"] > maximum:
            raise Problem(429, "PLEASE_WAIT", "Please wait a moment before trying again.")

    def session(self, token):
        if not isinstance(token, str) or len(token) > 128:
            return None
        with self.connect() as db:
            return db.execute("SELECT player_id, csrf_token FROM mobile_sessions WHERE token_hash=%s AND expires_at>now()",
                              (secret_hash(token),)).fetchone()

    def new_session(self, recovery_code=_NEW_SESSION):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        returned_code = None
        with self.connect() as db:
            if recovery_code is _NEW_SESSION:
                player = str(uuid.uuid4())
                returned_code = secrets.token_urlsafe(32)
                db.execute("INSERT INTO mobile_players(id,recovery_hash) VALUES(%s,%s)",
                           (player, secret_hash(returned_code)))
            else:
                if not isinstance(recovery_code, str) or not 40 <= len(recovery_code) <= 128:
                    raise Problem(401, "INVALID_RECOVERY", "That recovery code was not recognised.")
                row = db.execute("SELECT id FROM mobile_players WHERE recovery_hash=%s",
                                 (secret_hash(recovery_code),)).fetchone()
                if not row:
                    raise Problem(401, "INVALID_RECOVERY", "That recovery code was not recognised.")
                player = str(row["id"])
            db.execute("INSERT INTO mobile_sessions(token_hash,player_id,csrf_token) VALUES(%s,%s,%s)",
                       (secret_hash(token), player, csrf))
        return {"token": token, "csrf_token": csrf, "recovery_code": returned_code, "player_id": player}

    def rotate_recovery(self, player):
        code = secrets.token_urlsafe(32)
        with self.connect() as db:
            row = db.execute("UPDATE mobile_players SET recovery_hash=%s WHERE id=%s RETURNING id",
                             (secret_hash(code), player)).fetchone()
            if not row:
                raise Problem(401, "SESSION_REQUIRED", "Reconnect before replacing your recovery code.")
        return code

    def campaigns(self, player):
        with self.connect() as db:
            rows = db.execute("SELECT id,name,revision,updated_at,state->'world'->>'scene' AS chapter FROM mobile_campaigns WHERE player_id=%s ORDER BY updated_at DESC LIMIT 20",
                              (player,)).fetchall()
        return [{**r, "id": str(r["id"]), "updated_at": r["updated_at"].isoformat()} for r in rows]

    def create(self, player, request_id, episode_id=None):
        identifier(request_id)
        try:
            initial = rules.initial_state(episode_id)
        except ValueError as exc:
            raise Problem(422, "UNKNOWN_EPISODE", str(exc)) from None
        with self.connect() as db:
            # Serialize creation for one owner, including retries after lost replies.
            db.execute("SELECT id FROM mobile_players WHERE id=%s FOR UPDATE", (player,))
            old = db.execute("SELECT * FROM mobile_campaigns WHERE player_id=%s AND creation_request=%s",
                             (player, request_id)).fetchone()
            if old:
                if old["state"]["world"]["episode"]["id"] != initial["world"]["episode"]["id"]:
                    raise Problem(409, "CREATION_CONFLICT", "This request already created a different episode.")
                return self._packet(db, old)
            count = db.execute("SELECT count(*) AS n FROM mobile_campaigns WHERE player_id=%s", (player,)).fetchone()["n"]
            if count >= 20:
                raise Problem(429, "SAMPLE_LIMIT", "Your 20 sample campaigns are saved. Resume one of them.")
            state, campaign = initial, str(uuid.uuid4())
            head = digest({"campaign_id": campaign, "revision": 0, "state": state})
            row = db.execute("""INSERT INTO mobile_campaigns(id,player_id,creation_request,name,state,seed,head)
                 VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                 (campaign, player, request_id, rules.view(state)["title"], Jsonb(state), secrets.token_bytes(32), head)).fetchone()
            result = self._packet(db, row)
        return result

    def _owned(self, db, player, campaign, lock=False):
        identifier(campaign)
        row = db.execute("SELECT * FROM mobile_campaigns WHERE id=%s AND player_id=%s" + (" FOR UPDATE" if lock else ""),
                         (campaign, player)).fetchone()
        if not row:
            raise Problem(404, "CAMPAIGN_NOT_FOUND", "This campaign is not available to this connection.")
        return row

    def _packet(self, db, row):
        turns = db.execute("SELECT event,created_at FROM mobile_actions WHERE campaign_id=%s ORDER BY revision DESC LIMIT 15",
                           (row["id"],)).fetchall()
        events = [{"action_id": t["event"]["action_id"], "revision": t["event"]["revision"],
                   "narration": t["event"]["narration"], "roll": t["event"]["roll"],
                   "created_at": t["created_at"].isoformat()} for t in reversed(turns)]
        public = rules.view(row["state"])
        public["choices"] = [{**c, "choice_hash": digest(c)} for c in public["choices"]]
        from . import adventure
        authored = public["episode_id"] == adventure.EPISODE_ID
        return {"id": str(row["id"]), "revision": row["revision"], "head": row["head"],
                "state": public, "events": events,
                "companion": adventure.companion(row["state"]) if authored else None,
                "disposable": True, "capabilities": {"freeform": False, "import_live_campaign": False,
                                                      "typed_intents": authored,
                                                      "gm_assistant": self.gm_policy is not None and not authored}}

    def interpret_intent(self, player, campaign, expected_revision, prompt):
        from . import adventure
        with self.connect() as db:
            row = self._owned(db, player, campaign)
            if type(expected_revision) is not int or expected_revision != row["revision"]:
                raise Problem(409, "STALE_REVISION", "The story changed. Refresh before choosing your approach.")
            if row["state"]["world"]["episode"]["id"] != adventure.EPISODE_ID:
                raise Problem(422, "UNSUPPORTED_EPISODE", "Use the listed approaches for this episode.")
            try:
                result = adventure.interpret(row["state"], prompt)
            except (ValueError, UnicodeError) as exc:
                raise Problem(422, "INVALID_INTENT", "Use a valid message of at most 2,000 characters.") from None
            choices = {c["id"]: c for c in rules.view(row["state"])["choices"]}
            choice = choices.get(result["choice_id"])
            return {**result, "expected_revision": expected_revision,
                    "choice": {**choice, "choice_hash": digest(choice)} if choice else None}

    def notes(self, player, campaign, update=None):
        if update is not None:
            version, content = update
            if type(version) is not int or not 0 <= version < 2**53-1 or type(content) is not str or len(content) > 10000 or "\x00" in content:
                raise Problem(422, "INVALID_NOTES", "Use notes of at most 10,000 characters.")
            try:
                content.encode("utf-8")
            except UnicodeError:
                raise Problem(422, "INVALID_NOTES", "Use valid text for your notes.") from None
        with self.connect() as db:
            row = self._owned(db, player, campaign, lock=update is not None)
            if update is not None:
                # A lost response may safely retry the same save. A stale different
                # edit never overwrites another device's work.
                if content != row["player_notes"]:
                    if version != row["notes_version"]:
                        raise Problem(409, "NOTES_CONFLICT", "Your notes changed on another device. Review the saved copy before saving again.")
                    row = db.execute("UPDATE mobile_campaigns SET player_notes=%s, notes_version=notes_version+1 WHERE id=%s RETURNING *",
                                     (content, campaign)).fetchone()
            return {"text": row["player_notes"], "version": row["notes_version"]}

    def journal(self, player, campaign, before, query):
        if type(before) is not int or not 1 <= before <= 2**53-1 or type(query) is not str or len(query) > 200 or "\x00" in query:
            raise Problem(422, "INVALID_JOURNAL_QUERY", "Use a short journal search.")
        with self.connect() as db:
            self._owned(db, player, campaign)
            rows = db.execute("""SELECT revision,event->>'narration' AS narration,event->'roll' AS roll
                FROM mobile_actions WHERE campaign_id=%s AND revision<%s
                AND position(lower(%s) in lower(event->>'narration'))>0 ORDER BY revision DESC LIMIT 31""",
                (campaign, before, query)).fetchall()
            page = rows[:30]
            return {"entries": page, "next_before": page[-1]["revision"] if len(rows)>30 else None}

    def read(self, player, campaign):
        with self.connect() as db:
            # Snapshot consistency between checkpoint and event journal.
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return self._packet(db, self._owned(db, player, campaign))

    @staticmethod
    def dice(seed, campaign, action):
        # Rejection sampling avoids modulo bias. The seed never leaves the server.
        result = []
        for index in range(2):
            counter = 0
            while True:
                value = int.from_bytes(hmac.new(bytes(seed), canonical([campaign, action, index, counter]), "sha256").digest(), "big")
                if value < 2**256 - (2**256 % 10):
                    result.append(value % 10 + 1)
                    break
                counter += 1
        return result

    def act(self, player, campaign, request, fault=None):
        if not isinstance(request, dict) or set(request) != {"action_id", "expected_revision", "choice_id", "choice_hash"}:
            raise Problem(422, "INVALID_ACTION", "Choose one of the available actions.")
        action = identifier(request["action_id"])
        expected, choice = request["expected_revision"], request["choice_id"]
        if type(expected) is not int or expected < 0 or not isinstance(choice, str) or not 1 <= len(choice) <= 80:
            raise Problem(422, "INVALID_ACTION", "Choose one of the available actions.")
        request_hash = digest(request)
        with self.connect() as db:
            row = self._owned(db, player, campaign, lock=True)
            old = db.execute("SELECT request_hash,response FROM mobile_actions WHERE campaign_id=%s AND action_id=%s",
                             (campaign, action)).fetchone()
            if old:
                if not hmac.compare_digest(old["request_hash"], request_hash):
                    raise Problem(409, "ACTION_ID_CONFLICT", "This action identifier already belongs to a different choice. Refresh the saved campaign.")
                # Return the exact original committed result, never resolve or roll again.
                return {**old["response"], "replayed": True}
            if row["revision"] != expected:
                raise Problem(409, "STALE_REVISION", "Another action has already been saved. Refresh before choosing again.")
            choices = {c["id"]: c for c in rules.view(row["state"])["choices"]}
            if choice not in choices:
                raise Problem(422, "CHOICE_UNAVAILABLE", "That choice is no longer available. Refresh the scene.")
            if request["choice_hash"] != digest(choices[choice]):
                raise Problem(409, "STAKES_CHANGED", "The displayed stakes have changed. Refresh and review them before deciding.")
            dice = self.dice(row["seed"], campaign, action) if choices[choice]["requires_roll"] else None
            try:
                resolved = rules.resolve(row["state"], choice, dice)
            except ValueError as exc:
                raise Problem(422, "CHOICE_UNAVAILABLE", str(exc)) from None
            revision = expected + 1
            event = {"schema": "white-tower-mobile-turn-v1", "campaign_id": campaign, "action_id": action,
                     "revision": revision, "request": request, "request_sha256": request_hash,
                     "predecessor_head": row["head"], "pre_state": row["state"], "post_state": resolved["state"],
                     "narration": resolved["narration"], "roll": resolved["roll"],
                     "elapsed_seconds": resolved["elapsed_seconds"], "rules_edition": "notion-manual-v2"}
            event["head"] = digest(event)
            db.execute("INSERT INTO mobile_actions(campaign_id,action_id,revision,request_hash,event,response) VALUES(%s,%s,%s,%s,%s,%s)",
                       (campaign, action, revision, request_hash, Jsonb(event), Jsonb({})))
            if fault:
                fault("after_event_insert")  # injected only by local tests, never HTTP
            updated = db.execute("UPDATE mobile_campaigns SET state=%s,revision=%s,head=%s,updated_at=now() WHERE id=%s RETURNING *",
                                 (Jsonb(resolved["state"]), revision, event["head"], campaign)).fetchone()
            result = {**self._packet(db, updated), "replayed": False}
            db.execute("UPDATE mobile_actions SET response=%s WHERE campaign_id=%s AND action_id=%s",
                       (Jsonb(result), campaign, action))
            if fault:
                fault("before_commit")
        # Commit is complete before a caller can display 'saved'.
        return result

    def export(self, player, campaign):
        with self.connect() as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            row = self._owned(db, player, campaign)
            turns = db.execute("SELECT event FROM mobile_actions WHERE campaign_id=%s ORDER BY revision", (campaign,)).fetchall()
            result = {"schema": "white-tower-mobile-export-v1", "disposable": True,
                      "campaign_id": campaign, "rules_edition": "notion-manual-v2",
                      "revision": row["revision"], "head": row["head"], "state": row["state"],
                      "events": [t["event"] for t in turns],
                      "player_notes": {"text": row["player_notes"], "version": row["notes_version"]},
                      "exported_at": datetime.now(timezone.utc).isoformat(),
                      "note": "Portable audit export; keep your recovery code to resume the cloud campaign. No live campaign import is enabled."}
            result["sha256"] = digest(result)
        return result

    @staticmethod
    def _gm_packet(row):
        status = row["status"]
        error = None
        if status == "failed":
            error = {"code": "GM_UNAVAILABLE", "message": "The interpretation could not start. Your campaign did not advance."}
        elif status == "unknown":
            error = {"code": "GM_UNCERTAIN", "message": "The provider result could not be confirmed. This request will not be sent again. Your campaign did not advance."}
        if status in ("failed", "unknown") and row.get("error_code"):
            from .gm import GMError
            safe = GMError(row["error_code"])
            error = {"code": safe.code, "message": safe.message + " This request will not be sent again."}
        return {"request_id": str(row["request_id"]), "expected_revision": row["expected_revision"],
                "status": status, "result": deepcopy(row["result"]) if status == "completed" else None,
                "error": error}

    @staticmethod
    def _gm_find(db, campaign, request_id):
        # A worker may have died before, during, or after its one provider call.
        # Expiration closes the reservation; it never authorizes another call.
        db.execute("""UPDATE mobile_gm_requests SET status='unknown',finished_at=now()
                      WHERE campaign_id=%s AND request_id=%s AND status='prepared' AND expires_at<=now()""",
                   (campaign, request_id))
        return db.execute("SELECT * FROM mobile_gm_requests WHERE campaign_id=%s AND request_id=%s",
                          (campaign, request_id)).fetchone()

    def gm_status(self, player, campaign, request_id):
        identifier(request_id)
        with self.connect() as db:
            self._owned(db, player, campaign)
            row = self._gm_find(db, campaign, request_id)
            if row is None:
                raise Problem(404, "GM_REQUEST_NOT_FOUND", "This interpretation request is not available.")
            return self._gm_packet(row)

    @staticmethod
    def _gm_result(value, public):
        from .gm import MAX_MESSAGE_CHARS
        if type(value) is not dict or set(value) != {"kind", "choice_id", "message", "usage"}:
            raise ValueError("Invalid bounded GM result")
        kind, choice_id, message = value["kind"], value["choice_id"], value["message"]
        if kind not in ("proposal", "answer", "clarify") or type(message) is not str or not 1 <= len(message) <= MAX_MESSAGE_CHARS or not message.strip() or "\x00" in message:
            raise ValueError("Invalid bounded GM result")
        canonical(message)  # Reject invalid Unicode before the PostgreSQL write.
        choice_hash = None
        if kind == "proposal":
            choices = {choice["id"]: choice for choice in public["choices"]}
            if type(choice_id) is not str or choice_id not in choices:
                raise ValueError("Unsupported GM proposal")
            choice_hash = digest(choices[choice_id])
        elif choice_id is not None:
            raise ValueError("Non-proposals cannot select actions")
        usage = value["usage"]
        if type(usage) is not dict or set(usage) != {"input_tokens", "output_tokens", "total_tokens"} or any(
                v is not None and (type(v) is not int or not 0 <= v <= 2**53-1) for v in usage.values()):
            raise ValueError("Invalid GM usage")
        return {"kind": kind, "choice_id": choice_id, "choice_hash": choice_hash, "message": message}, usage

    def gm_request(self, player, campaign, request, interpreter, *, fault=None):
        """Reserve once, call outside all transactions, then persist a safe result.

        Reservations are lifetime, global, and never refunded. Neither retries
        nor expired workers can spend again under an existing request ID.
        """
        if type(request) is not dict or set(request) != {"request_id", "expected_revision", "prompt"}:
            raise Problem(422, "INVALID_GM_REQUEST", "Provide one bounded interpretation request.")
        from .gm import MAX_PROMPT_CHARS, MAX_PROMPT_BYTES
        request_id = identifier(request["request_id"])
        expected, prompt = request["expected_revision"], request["prompt"]
        if type(expected) is not int or not 0 <= expected <= 2**53-1 or type(prompt) is not str or not 1 <= len(prompt) <= MAX_PROMPT_CHARS or not prompt.strip() or "\x00" in prompt:
            raise Problem(422, "INVALID_GM_REQUEST", f"Use a message of at most {MAX_PROMPT_CHARS} characters and the current revision.")
        try:
            if len(canonical(prompt)) > MAX_PROMPT_BYTES + 2:
                raise ValueError()
        except (UnicodeError, ValueError):
            raise Problem(422, "INVALID_GM_REQUEST", "The message is not valid bounded text.") from None
        request_hash = digest(request)
        with self.connect() as db:
            campaign_row = self._owned(db, player, campaign, lock=True)
            old = self._gm_find(db, campaign, request_id)
            if old:
                if not hmac.compare_digest(old["request_hash"], request_hash):
                    raise Problem(409, "GM_REQUEST_ID_CONFLICT", "This request identifier belongs to different input.")
                return self._gm_packet(old)
            policy = self.gm_policy
            if policy is None or not callable(interpreter):
                raise Problem(503, "GM_DISABLED", "The sample interpreter is not enabled. Use the listed choices.")
            if campaign_row["state"].get("disposable") is not True:
                raise Problem(422, "GM_DISPOSABLE_ONLY", "This interpreter supports only the disposable sample.")
            if campaign_row["state"]["world"]["episode"]["id"] != rules.EPISODE_ID:
                raise Problem(422, "GM_UNSUPPORTED_EPISODE", "This adventure uses its local authored interpreter.")
            if campaign_row["revision"] != expected:
                raise Problem(409, "STALE_REVISION", "The campaign changed. Refresh before requesting an interpretation.")
            public = rules.view(campaign_row["state"])
            db.execute("""INSERT INTO mobile_gm_budget(id,reserved_requests,reserved_micro_usd)
                          VALUES('bounded-pilot-v1',0,0) ON CONFLICT(id) DO NOTHING""")
            budget = db.execute("SELECT * FROM mobile_gm_budget WHERE id='bounded-pilot-v1' FOR UPDATE").fetchone()
            reservation = policy["reservation_micro_usd"]
            if budget["reserved_requests"] >= policy["max_requests"] or budget["reserved_micro_usd"] + reservation > policy["budget_micro_usd"]:
                raise Problem(429, "GM_BUDGET_EXHAUSTED", "The configured sample interpretation allowance has been used. Listed choices remain available.")
            db.execute("""UPDATE mobile_gm_budget SET reserved_requests=reserved_requests+1,
                          reserved_micro_usd=reserved_micro_usd+%s WHERE id='bounded-pilot-v1'""", (reservation,))
            db.execute("""INSERT INTO mobile_gm_requests(campaign_id,request_id,expected_revision,request_hash,prompt,public_state,status,reserved_micro_usd)
                          VALUES(%s,%s,%s,%s,%s,%s,'prepared',%s)""",
                       (campaign, request_id, expected, request_hash, prompt, Jsonb(public), reservation))
        if fault:
            fault("after_reservation")
        status, result, usage, error_code = "unknown", None, None, None
        try:
            value = interpreter(deepcopy(public), prompt)
            result, usage = self._gm_result(value, public)
            status = "completed"
        except Exception as exc:
            # Only the adapter's typed, definitely-not-started error may use
            # failed. Every other error is uncertain; none permits a retry.
            from .gm import GMError
            status = "failed" if isinstance(exc, GMError) and exc.attempted is False else "unknown"
            if isinstance(exc, GMError):
                safe = GMError(exc.code, usage=exc.usage)
                error_code, usage = safe.code, safe.usage
        if fault:
            fault("after_provider")
        with self.connect() as db:
            self._owned(db, player, campaign)
            self._gm_find(db, campaign, request_id)
            db.execute("""UPDATE mobile_gm_requests SET status=%s,result=%s,usage=%s,error_code=%s,finished_at=now()
                          WHERE campaign_id=%s AND request_id=%s AND status='prepared' AND expires_at>now()""",
                       (status, Jsonb(result), Jsonb(usage), error_code, campaign, request_id))
            row = db.execute("SELECT * FROM mobile_gm_requests WHERE campaign_id=%s AND request_id=%s",
                             (campaign, request_id)).fetchone()
            return self._gm_packet(row)
