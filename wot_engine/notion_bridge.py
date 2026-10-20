"""Durable, credential-free transport through the connected Notion tools.

The local controller issues fixed requests. A Codex tool runner delivers them.
No response is trusted until its campaign, chunks, bytes, and hashes validate.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .contracts import ContractError, canonical, digest, parse_json, require, MAX_ENVELOPE_BYTES
from .storage import RemotePending

CREATE = "mcp__codex_apps__notion_notion_create_pages"
UPDATE = "mcp__codex_apps__notion_notion_update_page"
QUERY = "mcp__codex_apps__notion_query_data_sources"
ALLOWED_TOOLS = {CREATE, UPDATE, QUERY}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HISTORY_PAGE_SIZE = 25
MAX_HISTORY_ROWS = 10000
MAX_HISTORY_BYTES = 128 * 1024 * 1024
MAX_DISPATCH_ATTEMPTS = 24
MAX_DISPATCH_SECONDS = 45
HISTORY_URL_PREFIXES = ("https://www.notion.so/", "https://app.notion.com/")


def unpack_result(result):
    require(type(result) is dict, "Invalid connector result")
    require(not result.get("isError"), "Notion returned an error; inspect the private transport receipt")
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    blocks = [x["text"] for x in result.get("content", []) if x.get("type") == "text"]
    require(len(blocks) == 1, "Ambiguous connector result")
    try:
        return json.loads(blocks[0])
    except (ValueError, TypeError) as exc:
        raise ContractError("Connector result is not structured JSON") from exc


def page_id(value):
    match = re.search(r"([0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:[/?#]|$)", value)
    require(match is not None, "Invalid Notion page identifier")
    return str(uuid.UUID(match.group(1)))


class DurableBridge:
    """SQLite outbox survives processes. Unknown mutation outcomes never auto-retry."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.directory / "transport.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS requests(
            id TEXT PRIMARY KEY, cycle TEXT NOT NULL, tool TEXT NOT NULL,
            args TEXT NOT NULL, mutation INTEGER NOT NULL, status TEXT NOT NULL,
            response TEXT, applied INTEGER NOT NULL DEFAULT 0,
            started REAL, finished REAL);
        """)
        self.db.commit()
        os.chmod(self.directory / "transport.sqlite3", 0o600)

    def close(self):
        self.db.close()

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value)))

    def begin(self, operation):
        active = self.meta("active")
        if active:
            require(active["operation"] == operation, "Finish pending Notion work before another command")
            return active["id"]
        active = {"id": uuid.uuid4().hex, "operation": operation}
        self.set_meta("active", active)
        self.set_meta("generation", 0)
        self.db.commit()
        return active["id"]

    def finish(self):
        active = self.meta("active")
        if active:
            unfinished = self.db.execute("SELECT count(*) FROM requests WHERE cycle=? AND status!='COMPLETE'", (active["id"],)).fetchone()[0]
            require(unfinished == 0, "Transport requests still outstanding")
        self.set_meta("active", None)
        self.db.commit()

    def call(self, tool, args, mutation=False):
        require(tool in ALLOWED_TOOLS, "Unapproved transport tool")
        active = self.meta("active")
        require(active is not None, "No active transport cycle")
        identity = {"cycle": active["id"], "tool": tool, "args": args}
        if not mutation:
            identity["generation"] = self.meta("generation", 0)
        rid = digest(identity)
        row = self.db.execute("SELECT status,response,applied FROM requests WHERE id=?", (rid,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO requests(id,cycle,tool,args,mutation,status) VALUES(?,?,?,?,?,'QUEUED')", (rid, active["id"], tool, json.dumps(args), int(mutation)))
            self.db.commit()
            raise RemotePending("Notion request queued.", operation_id=rid)
        if row[0] != "COMPLETE":
            raise RemotePending("Notion request is pending verification.", operation_id=rid)
        result = unpack_result(json.loads(row[1]))
        if mutation and not row[2]:
            self.set_meta("generation", self.meta("generation", 0) + 1)
            self.db.execute("UPDATE requests SET applied=1 WHERE id=?", (rid,))
            self.db.commit()
        return result

    def start_dispatch(self, invocation_id):
        """Explicit continuation starts a new bounded connector invocation.

        Reusing its ID cannot reset its budget. This never requeues an
        in-flight request; uncertain mutations still require reconciliation.
        """
        require(type(invocation_id) is str and 1 <= len(invocation_id) <= 128,
                "Invalid dispatch invocation ID")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            active = self.meta("active")
            require(active is not None, "No active transport cycle")
            key = "dispatch:" + digest(invocation_id)
            prior = self.meta(key)
            if prior is not None:
                require(prior == self.meta("dispatch") and prior["cycle"] == active["id"],
                        "Dispatch invocation was superseded")
                self.db.rollback()
                return prior
            now = time.time()
            budget = {"id":invocation_id,"cycle":active["id"],"started":now,
                      "deadline":now + MAX_DISPATCH_SECONDS,"attempts":0}
            self.set_meta("dispatch", budget)
            self.set_meta(key, budget)
            self.db.commit()
            return budget
        except BaseException:
            self.db.rollback()
            raise

    def claim(self):
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT id,tool,args FROM requests WHERE status='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
        if not row:
            self.db.rollback()
            return None
        budget = self.meta("dispatch")
        now = time.time()
        active = self.meta("active")
        if active and (budget is None or budget["cycle"] != active["id"]):
            budget = {"id":uuid.uuid4().hex,"cycle":active["id"],"started":now,
                      "deadline":now + MAX_DISPATCH_SECONDS,"attempts":0}
        if (budget is None or now < budget["started"] or now >= budget["deadline"] or
                budget["attempts"] >= MAX_DISPATCH_ATTEMPTS):
            self.set_meta("dispatch_pending", {"status":"PENDING","request_id":row[0],
                          "reason":"DISPATCH_BUDGET","retry_not_before":now,
                          "requires_explicit_continuation":True})
            self.db.commit()
            raise RemotePending("Dispatch budget exhausted; explicitly start a new invocation.", operation_id=row[0])
        budget["attempts"] += 1
        self.set_meta("dispatch", budget)
        self.set_meta("dispatch:" + digest(budget["id"]), budget)
        self.set_meta("dispatch_pending", None)
        self.db.execute("UPDATE requests SET status='DISPATCHING',started=? WHERE id=?", (now, row[0]))
        self.db.commit()
        return {"id": row[0], "tool": row[1], "args": json.loads(row[2])}

    def complete(self, rid, response):
        require(type(response) is dict, "Response must be an object")
        row = self.db.execute("SELECT status,response FROM requests WHERE id=?", (rid,)).fetchone()
        require(row is not None, "Unknown transport request")
        if row[0] == "COMPLETE":
            require(json.loads(row[1]) == response, "Different response for completed transport request")
            return
        require(row[0] == "DISPATCHING", "Request was not dispatched")
        self.db.execute("UPDATE requests SET status='COMPLETE',response=?,finished=? WHERE id=?", (json.dumps(response), time.time(), rid))
        self.db.commit()

    def summary(self):
        return {"active": self.meta("active"), "requests": dict(self.db.execute("SELECT status,count(*) FROM requests GROUP BY status")),
                "dispatch":self.meta("dispatch"),"dispatch_pending":self.meta("dispatch_pending")}

    def refresh_reads(self):
        """Drop read receipts after observed query lag; never repeat a mutation."""
        require(self.meta("active") is not None, "No active transport cycle")
        pending = self.db.execute("SELECT count(*) FROM requests WHERE status!='COMPLETE'").fetchone()[0]
        require(pending == 0, "Resolve outstanding requests before refreshing reads")
        self.set_meta("generation", self.meta("generation", 0) + 1)
        self.db.commit()

    def retry_read(self, rid):
        """Explicitly retry an interrupted read; never redispatch a mutation."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT tool,mutation,status,cycle FROM requests WHERE id=?", (rid,)).fetchone()
            active = self.meta("active")
            require(row is not None and row[0] == QUERY and row[1] == 0,
                    "Only a read request can be retried")
            require(active and row[3] == active["id"], "Read belongs to another transport cycle")
            require(row[2] == "DISPATCHING", "Only an interrupted dispatched read can be retried")
            self.db.execute("UPDATE requests SET status='QUEUED',started=NULL WHERE id=?", (rid,))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return {"requeued": True, "request_id": rid, "mutations_repeated": False}

    def reconcile(self, rid):
        """Recover a lost mutation reply by proving its exact effect with a read.

        Absence is never permission to repeat the original mutation.
        """
        row = self.db.execute("SELECT tool,args,status,mutation,cycle FROM requests WHERE id=?", (rid,)).fetchone()
        require(row is not None and row[2] == "DISPATCHING" and row[3] == 1,
                "Only an uncertain dispatched mutation can be reconciled")
        active, registered = self.meta("active"), self.meta("registration")
        require(active and row[4] == active["id"] and registered, "Missing registered reconciliation scope")
        args = json.loads(row[1]); url = "collection://" + registered["data_source_id"]
        def literal(value):
            require(type(value) is str and len(value) < 256, "Invalid reconciliation index")
            return "'" + value.replace("'", "''") + "'"
        conditions = [f'"Campaign"={literal(registered["campaign_id"])}']
        if row[0] == CREATE:
            require(args.get("parent") == {"data_source_id":registered["data_source_id"]} and
                    type(args.get("pages")) is list and len(args["pages"]) == 1, "Unregistered create target")
            desired = args["pages"][0]["properties"]
            require(desired.get("Campaign") == registered["campaign_id"], "Foreign create target")
            conditions += [f'"{field}"={literal(desired[field])}' for field in ("Kind","Name")]
            if "ActionID" in desired: conditions.append(f'"ActionID"={literal(desired["ActionID"])}')
        elif row[0] == UPDATE:
            require(args.get("command") == "update_properties", "Unsupported reconciliation mutation")
            desired = args["properties"]
            pid = page_id(args["page_id"])
            conditions.append(f"replace(url,'-','') LIKE '%{pid.replace('-','')}%'")
        else:
            raise ContractError("Unsupported reconciliation tool")
        query = f'SELECT * FROM "{url}" WHERE ' + " AND ".join(conditions) + ' ORDER BY url LIMIT 10'
        result = self.call(QUERY,{"data":{"mode":"sql","data_source_urls":[url],"query":query}})
        rows = result.get("results")
        require(type(rows) is list and result.get("has_more") is False and len(rows) < 10,
                "Reconciliation query is incomplete")
        require(all(type(r) is dict and r.get("Campaign") == registered["campaign_id"] for r in rows), "Foreign reconciliation result")
        matches = [r for r in rows if all((r.get(k) or "") == v if v == "" else r.get(k) == v
                                          for k,v in desired.items())]
        if row[0] == CREATE:
            require(len(matches) == len(rows), "Conflicting remote record requires manual review")
        if not matches:
            self.set_meta("generation", self.meta("generation", 0) + 1)
            self.db.commit()
            raise RemotePending("The mutation effect is not yet observed; the original write remains paused.", operation_id=rid)
        if row[0] == CREATE:
            require(len(matches) == 1 or desired.get("Kind") == "event", "Duplicate managed record requires review")
            chosen = min(page_id(r["url"]) for r in matches)
            recovered = {"pages":[{"id":chosen}]}
        else:
            require(len(matches) == 1 and page_id(matches[0]["url"]) == pid, "Wrong update reconciliation target")
            recovered = {"page_id":pid}
        receipt = {"structuredContent":recovered,"_meta":{"reconciled":True,"method":"exact registered query readback"}}
        self.complete(rid,receipt)
        return {"reconciled":True,"request_id":rid,"mutations_repeated":False}


def encode_payload(value):
    raw = canonical(value)
    require(len(raw) <= MAX_ENVELOPE_BYTES, "Remote record exceeds 32 KiB")
    encoded = base64.b64encode(raw).decode("ascii")
    chunks = [encoded[i:i+1800] for i in range(0, len(encoded), 1800)]
    require(len(chunks) <= 25, "Too many payload chunks")
    props = {f"Payload{i:02}": chunks[i] if i < len(chunks) else "" for i in range(25)}
    return {**props, "ChunkCount": len(chunks), "ByteLength": len(raw), "PayloadHash": sha256(raw).hexdigest()}


def decode_payload(row):
    count, length = row.get("ChunkCount"), row.get("ByteLength")
    require(type(count) in (int,float) and count == int(count) and 1 <= count <= 25, "Invalid chunk count")
    require(type(length) in (int,float) and length == int(length) and 0 < length <= MAX_ENVELOPE_BYTES, "Invalid payload length")
    chunks = []
    for i in range(25):
        value = row.get(f"Payload{i:02}") or ""
        require(type(value) is str and len(value) <= 1800, "Invalid payload chunk")
        if i < count:
            require(bool(value), "Missing payload chunk")
            chunks.append(value)
        else:
            require(not value, "Unexpected payload tail")
    try:
        raw = base64.b64decode("".join(chunks), validate=True)
        value = parse_json(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ContractError("Invalid remote payload encoding") from exc
    require(len(raw) == length and sha256(raw).hexdigest() == row.get("PayloadHash"), "Remote payload hash mismatch")
    require(canonical(value) == raw, "Noncanonical payload")
    return value


class NotionRemote:
    def __init__(self, directory, campaign_id, data_source_id):
        require(UUID.fullmatch(data_source_id) is not None, "Invalid data-source identifier")
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", campaign_id) is not None, "Invalid campaign identifier")
        self.bridge = DurableBridge(directory)
        self.campaign_id = campaign_id
        self.data_source_id = data_source_id
        self.url = "collection://" + data_source_id
        registered = self.bridge.meta("registration")
        identity = {"campaign_id": campaign_id, "data_source_id": data_source_id}
        require(registered in (None, identity), "Transport belongs to another campaign")
        self.bridge.set_meta("registration", identity)
        self.bridge.db.commit()

    def _query(self, where="1=1", fields="*", limit=100):
        query = f'SELECT {fields} FROM "{self.url}" WHERE "Campaign"=\'{self.campaign_id}\' AND ({where}) ORDER BY url LIMIT {limit}'
        result = self.bridge.call(QUERY, {"data": {"mode": "sql", "data_source_urls": [self.url], "query": query}})
        require(type(result.get("results")) is list and result.get("has_more") is False, "Incomplete Notion query")
        require(len(result["results"]) < limit, "Notion query reached its safety limit; complete history is unverified")
        return result["results"]

    def _record(self, row, kind, name=None):
        require(row.get("Campaign") == self.campaign_id and row.get("Kind") == kind,
                "Cross-campaign or wrong-kind target")
        require(row.get("Status") == "COMMITTED", "Record is not committed")
        if name is not None:
            require(row.get("Name") == name, "Wrong projection or genesis identity")
        payload = decode_payload(row)
        require(type(payload) is dict and payload.get("campaign_id") == self.campaign_id,
                "Remote payload belongs to another campaign")
        return payload

    def _read(self, pid):
        pid = page_id(pid)
        # SQLite URLs use canonical https://www.notion.so/<32 hex> in this connector.
        rows = self._query(f"replace(replace(url,'-',''),'https://www.notion.so/','') LIKE '%{pid.replace('-','')}%'", limit=2)
        require(len(rows) == 1 and page_id(rows[0]["url"]) == pid, "Remote record missing or ambiguous")
        return rows[0]

    def _create(self, kind, name, payload, **extra):
        properties = {"Name": name, "Campaign": self.campaign_id, "Kind": kind,
                      "Status": "PREPARED", **encode_payload(payload), **extra}
        result = self.bridge.call(CREATE, {"parent": {"data_source_id": self.data_source_id}, "allow_async": False,
                                  "pages": [{"properties": properties}]}, mutation=True)
        require(type(result.get("pages")) is list and len(result["pages"]) == 1, "Unexpected create result")
        return page_id(result["pages"][0]["id"])

    def put_genesis(self, genesis):
        require(genesis.get("campaign_id") == self.campaign_id, "Cross-campaign genesis")
        rows = self._query('"Kind"=\'genesis\'')
        if rows:
            require(len(rows) == 1 and canonical(self._record(rows[0], "genesis", "GM genesis")) == canonical(genesis), "Conflicting genesis")
            return
        pid = self._create("genesis", "GM genesis", genesis, Status="COMMITTED")
        require(canonical(self._record(self._read(pid), "genesis", "GM genesis")) == canonical(genesis), "Genesis readback differs")

    def get_genesis(self):
        rows = self._query('"Kind"=\'genesis\'')
        require(len(rows) == 1 and rows[0].get("Status") == "COMMITTED", "Missing or conflicting genesis")
        return self._record(rows[0], "genesis", "GM genesis")

    def list_candidates(self):
        """Return two matching complete observations, never a partial inventory.

        SQL has no snapshot token. These scans detect observed indexing drift;
        they cannot prove that Notion has exposed every stored record. The
        controller still verifies trusted history, head, and projections.
        """
        active = self.bridge.meta("active")
        require(active is not None, "No active transport cycle")
        scope = (active["id"], self.bridge.meta("generation", 0))
        candidates = self._history_scan(1, scope)
        self._history_scan(2, scope, expected=candidates)
        return candidates

    def _history_scope(self, scope):
        active = self.bridge.meta("active")
        require(active is not None and (active["id"], self.bridge.meta("generation", 0)) == scope,
                "Notion history read generation changed; restart the complete scan")

    def _history_scan(self, observation, scope, expected=None):
        # Fixed comments give the observations distinct durable request IDs.
        # Every page otherwise has the same campaign scope and keyset order.
        require(observation in (1, 2), "Invalid history observation")
        require(type(HISTORY_PAGE_SIZE) is int and 1 <= HISTORY_PAGE_SIZE <= 100,
                "Invalid history page size")
        after, count, byte_count = "", 0, 0
        candidates, seen = [], set()
        page_budget = MAX_HISTORY_ROWS // HISTORY_PAGE_SIZE + 1
        for _ in range(page_budget):
            self._history_scope(scope)
            query = (f'SELECT * FROM "{self.url}" WHERE "Campaign"=? AND "Kind"=? '
                     'AND url COLLATE BINARY > ? ORDER BY url COLLATE BINARY LIMIT ? '
                     f'/* complete-history-v1 observation-{observation} */')
            result = self.bridge.call(QUERY, {"data": {"mode": "sql", "data_source_urls": [self.url],
                                      "query": query, "params": [self.campaign_id, "event", after, HISTORY_PAGE_SIZE]}})
            self._history_scope(scope)
            rows = result.get("results")
            require(type(rows) is list and result.get("has_more") is False and len(rows) <= HISTORY_PAGE_SIZE,
                    "Incomplete Notion history page")
            for row in rows:
                require(type(row) is dict and type(row.get("url")) is str,
                        "Invalid Notion history row")
                pid = page_id(row["url"])
                require(row["url"] in {prefix + pid.replace("-", "") for prefix in HISTORY_URL_PREFIXES} and
                        row["url"] > after and pid not in seen,
                        "Notion history pages overlap or are not in canonical order")
                candidate = self._candidate(row)
                count += 1
                byte_count += len(canonical(candidate))
                require(count <= MAX_HISTORY_ROWS and byte_count <= MAX_HISTORY_BYTES,
                        "Notion history exceeds its bounded scan budget; complete history is unverified")
                if expected is None:
                    candidates.append(candidate)
                else:
                    require(count <= len(expected) and canonical(candidate) == canonical(expected[count - 1]),
                            "Notion history observations differ; refresh reads and retry")
                seen.add(pid)
                after = row["url"]
            if len(rows) < HISTORY_PAGE_SIZE:
                require(expected is None or count == len(expected),
                        "Notion history observations differ; refresh reads and retry")
                return candidates
        raise ContractError("Notion history page budget exhausted; complete history is unverified")

    def _candidate(self, row):
        require(row.get("Campaign") == self.campaign_id and row.get("Kind") == "event", "Cross-campaign or wrong-kind target")
        envelope = decode_payload(row)
        require(envelope["event"]["campaign_id"] == self.campaign_id and
                envelope["accepted_action"]["campaign_id"] == self.campaign_id, "Cross-campaign envelope")
        require(row.get("EventHash") == envelope["event"]["event_hash"] and row.get("EnvelopeHash") == envelope["envelope_hash"], "Candidate index hashes differ")
        require(row.get("ActionID") == envelope["event"]["action_id"] and row.get("Sequence") == envelope["event"]["sequence"], "Candidate index identity differs")
        require(row.get("Status") in ("PREPARED", "COMMITTED"), "Invalid candidate status")
        return {"page_id": page_id(row["url"]), "status": row["Status"], "envelope": envelope}

    def create_prepared(self, envelope):
        event = envelope["event"]
        require(event["campaign_id"] == self.campaign_id, "Cross-campaign event")
        return self._create("event", "Event " + event["action_id"], envelope, ActionID=event["action_id"],
                            Sequence=event["sequence"], EventHash=event["event_hash"], EnvelopeHash=envelope["envelope_hash"])

    def read_candidate(self, pid):
        return self._candidate(self._read(pid))

    def commit(self, pid):
        candidate = self.read_candidate(pid)
        if candidate["status"] == "COMMITTED":
            return
        self.bridge.call(UPDATE, {"page_id": page_id(pid), "command": "update_properties", "properties": {"Status": "COMMITTED"}}, mutation=True)

    def write_projection(self, kind, data):
        require(kind in ("player", "world"), "Unknown projection kind")
        require(data.get("campaign_id") == self.campaign_id, "Cross-campaign projection")
        rows = self._query(f'"Kind"=\'projection\' AND "Name"=\'{kind}\'')
        require(len(rows) <= 1, "Duplicate projection")
        if not rows:
            self._create("projection", kind, data, Status="COMMITTED")
        elif canonical(self._record(rows[0], "projection", kind)) != canonical(data):
            self.bridge.call(UPDATE, {"page_id": page_id(rows[0]["url"]), "command": "update_properties", "properties": encode_payload(data)}, mutation=True)

    def read_projection(self, kind):
        require(kind in ("player", "world"), "Unknown projection kind")
        rows = self._query(f'"Kind"=\'projection\' AND "Name"=\'{kind}\'')
        require(len(rows) <= 1, "Duplicate projection")
        return self._record(rows[0], "projection", kind) if rows else None
