"""One PostgreSQL authority for sessions, immutable turns, and checkpoints."""
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import rules


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
CREATE INDEX IF NOT EXISTS mobile_campaign_owner ON mobile_campaigns(player_id, updated_at);
"""


class Store:
    def __init__(self, url):
        if not url:
            raise RuntimeError("DATABASE_URL is required; there is no local-file fallback")
        self.url = url

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

    def new_session(self, recovery_code=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        returned_code = None
        with self.connect() as db:
            if recovery_code is None:
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
        return {"token": token, "csrf_token": csrf, "recovery_code": returned_code}

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
            rows = db.execute("SELECT id,name,revision,updated_at FROM mobile_campaigns WHERE player_id=%s ORDER BY updated_at DESC LIMIT 20",
                              (player,)).fetchall()
        return [{**r, "id": str(r["id"]), "updated_at": r["updated_at"].isoformat()} for r in rows]

    def create(self, player, request_id):
        identifier(request_id)
        with self.connect() as db:
            # Serialize creation for one owner, including retries after lost replies.
            db.execute("SELECT id FROM mobile_players WHERE id=%s FOR UPDATE", (player,))
            old = db.execute("SELECT * FROM mobile_campaigns WHERE player_id=%s AND creation_request=%s",
                             (player, request_id)).fetchone()
            if old:
                return self._packet(db, old)
            count = db.execute("SELECT count(*) AS n FROM mobile_campaigns WHERE player_id=%s", (player,)).fetchone()["n"]
            if count >= 20:
                raise Problem(429, "SAMPLE_LIMIT", "Your 20 sample campaigns are saved. Resume one of them.")
            state, campaign = rules.initial_state(), str(uuid.uuid4())
            head = digest({"campaign_id": campaign, "revision": 0, "state": state})
            row = db.execute("""INSERT INTO mobile_campaigns(id,player_id,creation_request,name,state,seed,head)
                 VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                 (campaign, player, request_id, "Elin — disposable rehearsal", Jsonb(state), secrets.token_bytes(32), head)).fetchone()
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
        return {"id": str(row["id"]), "revision": row["revision"], "head": row["head"],
                "state": public, "events": events,
                "disposable": True, "capabilities": {"freeform": False, "import_live_campaign": False}}

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
                      "exported_at": datetime.now(timezone.utc).isoformat(),
                      "note": "Portable audit export; keep your recovery code to resume the cloud campaign. No live campaign import is enabled."}
            result["sha256"] = digest(result)
        return result
