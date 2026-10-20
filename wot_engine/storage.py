"""Durable local sequencing and an explicitly local remote-service simulator."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

from .contracts import canonical, parse_json


class RemotePending(RuntimeError):
    """The transport has not established the outcome of an operation."""

    def __init__(self, message="Remote operation pending.", operation_id=None):
        super().__init__(message)
        self.operation_id = operation_id


class WriterBusy(RuntimeError):
    pass


def private_directory(path):
    path = Path(path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


@contextmanager
def file_lock(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterBusy("Another controller owns this campaign.") from exc
        yield
    finally:
        os.close(descriptor)


def atomic_json(path, value):
    """Replace one file durably. This is not a multi-file transaction."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    return parse_json(Path(path).read_bytes())


class CampaignStore:
    """Every access uses the campaign lock; each write uses a short transaction."""

    def __init__(self, directory):
        self.directory = private_directory(directory)
        self.path = self.directory / "campaign.sqlite3"
        self.lock_path = self.directory / "writer.lock"

    @contextmanager
    def locked(self):
        with file_lock(self.lock_path):
            connection = sqlite3.connect(self.path, timeout=2, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=2000")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("Local database integrity check failed.")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS actions (
                        action_id TEXT PRIMARY KEY,
                        action_hash TEXT NOT NULL,
                        sequence INTEGER NOT NULL UNIQUE,
                        action_json TEXT NOT NULL,
                        narrations_json TEXT NOT NULL,
                        context_json TEXT NOT NULL,
                        envelope_json TEXT,
                        phase TEXT NOT NULL,
                        selected_page_id TEXT,
                        receipt_id TEXT NOT NULL);
                """)
                os.chmod(self.path, 0o600)
                yield connection
            finally:
                connection.close()

    @staticmethod
    @contextmanager
    def transaction(connection):
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    @staticmethod
    def get(connection, key, default=None):
        row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return default if row is None else parse_json(row[0])

    @staticmethod
    def set(connection, key, value):
        connection.execute("INSERT INTO metadata(key,value) VALUES(?,?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (key, canonical(value).decode("utf-8")))


class FileRemote:
    """Synchronous local service simulator, never a Notion durability claim.

    Keep this directory separate from the controller directory. Atomic files
    survive controller restarts, but both directories may share one physical host.
    """

    def __init__(self, directory):
        self.directory = private_directory(directory)
        self.events = private_directory(self.directory / "events")
        self.projections = private_directory(self.directory / "projections")
        self.trace = []

    def _event_path(self, page_id):
        if not isinstance(page_id, str) or len(page_id) != 32 or any(c not in "0123456789abcdef" for c in page_id):
            raise ValueError("Invalid simulator page ID.")
        return self.events / (page_id + ".json")

    def put_genesis(self, genesis):
        self.trace.append("put_genesis")
        with file_lock(self.directory / "remote.lock"):
            path = self.directory / "genesis.json"
            if path.exists():
                if canonical(read_json(path)) != canonical(genesis):
                    raise ValueError("Remote genesis already differs.")
                return
            atomic_json(path, genesis)

    def get_genesis(self):
        self.trace.append("get_genesis")
        return read_json(self.directory / "genesis.json")

    def list_candidates(self):
        self.trace.append("list_candidates")
        return [read_json(path) for path in sorted(self.events.glob("*.json"))]

    def create_prepared(self, envelope):
        self.trace.append("create_prepared")
        page_id = uuid.uuid4().hex
        with file_lock(self.directory / "remote.lock"):
            atomic_json(self._event_path(page_id),
                        {"page_id": page_id, "status": "PREPARED", "envelope": envelope})
        return page_id

    def read_candidate(self, page_id):
        self.trace.append("read_candidate")
        return read_json(self._event_path(page_id))

    def commit(self, page_id):
        self.trace.append("commit")
        with file_lock(self.directory / "remote.lock"):
            path = self._event_path(page_id)
            candidate = read_json(path)
            if candidate["status"] not in ("PREPARED", "COMMITTED"):
                raise ValueError("Invalid candidate status.")
            candidate["status"] = "COMMITTED"
            atomic_json(path, candidate)

    def write_projection(self, kind, data):
        self.trace.append("write_projection:" + kind)
        if kind not in ("player", "world"):
            raise ValueError("Unknown projection kind.")
        with file_lock(self.directory / "remote.lock"):
            atomic_json(self.projections / (kind + ".json"), data)

    def read_projection(self, kind):
        self.trace.append("read_projection:" + kind)
        if kind not in ("player", "world"):
            raise ValueError("Unknown projection kind.")
        path = self.projections / (kind + ".json")
        return read_json(path) if path.exists() else None
