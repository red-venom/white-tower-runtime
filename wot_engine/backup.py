"""Bounded authenticated backup API. Keys never enter arguments or logs here.

The optional cryptography extra is required. Restores are maintenance readers,
not writer transfers. Release source is retained as an inert JSON bundle.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import secrets
import sqlite3
import sys
import unicodedata
import re

from .contracts import canonical, digest, die, envelope_valid, hashed_record, parse_json
from .controller import Controller, RULES_VERSION, CONTENT_VERSION, ENGINE_VERSION, ZERO_HASH
from .rulesets import get_rules, FULL
from .storage import CampaignStore, FileRemote, private_directory

MAGIC = b"WOTBACKUP1\x00"
# A measured 964-action route occupies about 57 MiB of SQLite reservations.
# Bound the uncompressed database and complete authenticated container; never
# truncate history. Base64 and the pinned source bundle fit within 160 MiB.
MAX_BACKUP_BYTES = 160 * 1024 * 1024
MAX_DATABASE_BYTES = 96 * 1024 * 1024
MAX_RELEASE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 128
CRYPTOGRAPHY_VERSION = "50.0.1"
# Minimum supported bundle, not the limit of source verification. Every
# installed top-level runtime Python file must also appear and match bytewise.
CRITICAL_FILES = frozenset({"wot_engine/__init__.py", "wot_engine/contracts.py",
                            "wot_engine/controller.py", "wot_engine/storage.py",
                            "wot_engine/rules.py", "wot_engine/backup.py"})
CONTENT_FILES = ("mechanics.md", "weave-catalogue.md", "curriculum.md", "lore-and-oaths.md")
VERSION_FIELDS = ("rules_version", "content_version", "engine_version")


class BackupError(ValueError):
    """All messages are public templates, without plaintext or key material."""


def require(condition, message):
    if not condition:
        raise BackupError(message)


def _aesgcm():
    try:
        import cryptography
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise BackupError("Install the pinned optional backup dependency.") from exc
    require(cryptography.__version__ == CRYPTOGRAPHY_VERSION, "The backup encryption dependency does not match its pinned version.")
    return AESGCM


def generate_key():
    """Return a new private key. The caller must securely retain it separately."""
    return _aesgcm().generate_key(bit_length=256)


def _key(key):
    require(type(key) is bytes and len(key) == 32, "A 32-byte backup key is required.")
    return key


def _binding_valid(binding, campaign_id):
    require(type(binding) is dict and binding.get("campaign_id") == campaign_id, "The backup remote binding differs from its campaign.")
    if binding.get("kind") == "file":
        require(set(binding) == {"kind", "campaign_id", "remote_directory"} and
                type(binding["remote_directory"]) is str and Path(binding["remote_directory"]).is_absolute(),
                "Invalid file-service recovery binding.")
    elif binding.get("kind") == "notion":
        require(set(binding) == {"kind", "campaign_id", "data_source_id"} and
                type(binding["data_source_id"]) is str and
                re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", binding["data_source_id"]) is not None,
                "Invalid Notion recovery binding.")
    else:
        raise BackupError("The backup remote type is unsupported.")
    return binding


def _remote_binding(remote, campaign_id):
    if isinstance(remote, FileRemote):
        return _binding_valid({"kind": "file", "campaign_id": campaign_id,
                               "remote_directory": str(remote.directory)}, campaign_id)
    from .notion_bridge import NotionRemote
    require(isinstance(remote, NotionRemote), "The backup remote type is unsupported.")
    return _binding_valid({"kind": "notion", "campaign_id": remote.campaign_id,
                           "data_source_id": remote.data_source_id}, campaign_id)


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _unb64(text, maximum):
    require(type(text) is str and len(text) <= 4 * ((maximum + 2) // 3), "Encoded backup data exceeds its limit.")
    try:
        data = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise BackupError("Invalid encoded backup data.") from exc
    require(len(data) <= maximum, "Decoded backup data exceeds its limit.")
    return data


def _json(data, maximum):
    require(type(data) is bytes and len(data) <= maximum, "The backup record exceeds its byte limit.")
    try:
        value = parse_json(data.decode("utf-8"))
        require(canonical(value) == data, "The backup record is not canonical JSON.")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BackupError("The backup record is invalid.") from exc


def _safe_relative(path):
    require(type(path) is str and 1 <= len(path) <= 240 and "\\" not in path and "\x00" not in path,
            "Invalid release source path.")
    value = PurePosixPath(path)
    require(not value.is_absolute() and str(value) == path and all(part not in (".", "..") for part in value.parts)
            and unicodedata.normalize("NFC", path) == path,
            "Invalid release source path.")
    return path


def build_release_bundle(source_root, *, rules_version=RULES_VERSION,
                         content_version=CONTENT_VERSION, engine_version=ENGINE_VERSION):
    """Collect only runtime Python files, project metadata, and named rule texts."""
    _supported_rules((rules_version,content_version,engine_version))
    root = Path(source_root).resolve()
    paths = {path.relative_to(root).as_posix() for path in (root / "wot_engine").glob("*.py")}
    paths.add("pyproject.toml")
    paths.update(path for path in CONTENT_FILES if (root / path).is_file())
    require(CRITICAL_FILES <= paths and len(paths) <= MAX_FILES, "The release source bundle is incomplete or too large.")
    records, files = [], []
    source_bytes = 0
    for relative in sorted(paths):
        _safe_relative(relative)
        path = root / relative
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), "Release sources must be ordinary files inside the source root.")
        require(path.stat().st_size <= MAX_FILE_BYTES, "A release source file exceeds its byte limit.")
        data = path.read_bytes()
        require(len(data) <= MAX_FILE_BYTES, "A release source file exceeds its byte limit.")
        source_bytes += len(data)
        require(source_bytes <= MAX_RELEASE_BYTES * 3 // 4, "The release source bundle exceeds its byte limit.")
        records.append({"path": relative, "size": len(data), "sha256": sha256(data).hexdigest()})
        files.append({"path": relative, "data_b64": _b64(data)})
    manifest = {"schema": "release-manifest-v1", "engine_version": engine_version,
                "rules_version": rules_version, "content_version": content_version,
                "python_version": sys.version.split()[0], "unicode_version": unicodedata.unidata_version,
                "backup_dependency": "cryptography==" + CRYPTOGRAPHY_VERSION, "files": records}
    bundle = {"schema": "release-bundle-v1", "manifest": manifest, "files": files}
    bundle["bundle_hash"] = hashed_record(bundle, "bundle_hash")
    data = canonical(bundle)
    verify_release_bundle(data)
    return data


def _supported_rules(versions):
    try:
        return get_rules(*versions)
    except (ValueError,TypeError,ImportError) as exc:
        raise BackupError("The release versions are unsupported.") from exc


def _versions(record):
    return tuple(record[key] for key in VERSION_FIELDS)


def _match_campaign_release(genesis, release):
    require(_versions(genesis)==_versions(release["manifest"]),
            "The release manifest differs from the campaign's pinned versions.")


def verify_release_bundle(data, *, match_installed=True):
    bundle = _json(data, MAX_RELEASE_BYTES)
    require(type(bundle) is dict and set(bundle) == {"schema", "manifest", "files", "bundle_hash"}
            and bundle["schema"] == "release-bundle-v1", "Unsupported release bundle.")
    require(bundle["bundle_hash"] == hashed_record(bundle, "bundle_hash"), "Release bundle hash mismatch.")
    manifest = bundle["manifest"]
    fields = {"schema", "engine_version", "rules_version", "content_version", "python_version",
              "unicode_version", "backup_dependency", "files"}
    require(type(manifest) is dict and set(manifest) == fields and manifest["schema"] == "release-manifest-v1",
            "Unsupported release manifest.")
    _supported_rules(_versions(manifest))
    require(manifest["python_version"] == sys.version.split()[0] and
            manifest["unicode_version"] == unicodedata.unidata_version and
            manifest["backup_dependency"] == "cryptography==" + CRYPTOGRAPHY_VERSION,
            "The release runtime dependencies differ.")
    require(type(manifest["files"]) is list and type(bundle["files"]) is list and
            len(manifest["files"]) == len(bundle["files"]) <= MAX_FILES,
            "Invalid release file inventory.")
    entries = {}
    for record in manifest["files"]:
        require(type(record) is dict and set(record) == {"path", "size", "sha256"}, "Invalid release manifest entry.")
        path = _safe_relative(record["path"])
        require(path not in entries and type(record["size"]) is int and 0 <= record["size"] <= MAX_FILE_BYTES,
                "Duplicate or oversized release source.")
        entries[path] = record
    require(CRITICAL_FILES <= set(entries), "The release lacks required runtime sources.")
    if _versions(manifest)==FULL:
        require({"wot_engine/"+name+".py" for name in
                 ("rulesets","full_rules","catalogue","magic","progression","regional","combat",
                  "knowledge","oaths","story","life","scenes","creation")} <= set(entries),
                "The full campaign release lacks required runtime sources.")
    seen = set()
    installed = Path(__file__).resolve().parent.parent
    recorded_runtime = {path for path in entries if PurePosixPath(path).parent == PurePosixPath("wot_engine") and path.endswith(".py")}
    if match_installed:
        installed_runtime = {path.relative_to(installed).as_posix() for path in (installed / "wot_engine").glob("*.py")}
        require(recorded_runtime == installed_runtime, "The installed runtime source inventory differs.")
    for item in bundle["files"]:
        require(type(item) is dict and set(item) == {"path", "data_b64"}, "Invalid release source entry.")
        path = _safe_relative(item["path"])
        require(path in entries and path not in seen, "Release source inventory mismatch.")
        seen.add(path)
        raw = _unb64(item["data_b64"], MAX_FILE_BYTES)
        record = entries[path]
        require(len(raw) == record["size"] and sha256(raw).hexdigest() == record["sha256"], "Release source hash mismatch.")
        if match_installed and path in recorded_runtime:
            current = installed / path
            require(current.is_file() and sha256(current.read_bytes()).hexdigest() == record["sha256"],
                    "The installed runtime differs from the backed-up sources. Source execution is never automatic.")
    return bundle


def _exclusive_bytes(path, data):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_release_bundle(directory, bundle_bytes):
    """Create a content-addressed release file, refusing conflicting replacement."""
    bundle = verify_release_bundle(bundle_bytes)
    directory = private_directory(directory)
    path = directory / (bundle["bundle_hash"] + ".release.json")
    if path.exists():
        require(not path.is_symlink() and path.read_bytes() == bundle_bytes, "An existing release artifact differs.")
    else:
        _exclusive_bytes(path, bundle_bytes)
        _sync_directory(directory)
    return path


def _memory_database(raw):
    require(type(raw) is bytes and len(raw) <= MAX_DATABASE_BYTES, "The SQLite snapshot exceeds its byte limit.")
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.deserialize(raw)
        db.execute("PRAGMA trusted_schema=OFF")
        if hasattr(db, "setconfig"):
            db.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "The SQLite snapshot failed integrity validation.")
        objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        require({(row["name"], row["type"]) for row in objects} == {("metadata", "table"), ("actions", "table")},
                "The snapshot has unsupported tables, views, or triggers.")
        return db
    except (sqlite3.DatabaseError, BackupError):
        db.close()
        raise BackupError("The SQLite snapshot is invalid.") from None


def _validate_snapshot(db):
    metadata = {row["key"]: parse_json(row["value"]) for row in db.execute("SELECT key,value FROM metadata")}
    require(metadata.get("initialized") is True and not metadata.get("recovery_blocked", False),
            "Only initialized, reconciled snapshots can be restored.")
    genesis, current = metadata.get("genesis"), metadata.get("current")
    genesis_fields = {"schema", "campaign_id", "rules_version", "content_version", "engine_version", "origin_epoch",
                      "seed_hex", "state", "private_npc_fields", "genesis_hash"}
    require(type(genesis) is dict and set(genesis) == genesis_fields and genesis.get("genesis_hash") == hashed_record(genesis, "genesis_hash"),
            "The snapshot genesis hash differs.")
    require(genesis.get("schema") == "genesis-v1" and genesis.get("origin_epoch") == 1,
            "The snapshot uses unsupported administration.")
    engine=_supported_rules(_versions(genesis))
    seed = bytes.fromhex(genesis["seed_hex"])
    require(len(seed) == 32, "The snapshot seed is invalid.")
    require(type(genesis["private_npc_fields"]) is list, "The snapshot private registry is invalid.")
    for pair in genesis["private_npc_fields"]:
        require(type(pair) is list and len(pair) == 2 and all(type(value) is str for value in pair) and
                pair[0].startswith("npc-") and pair[1].startswith("private_") and pair[0] in genesis["state"] and
                pair[1] in genesis["state"][pair[0]], "The snapshot private registry is invalid.")
    engine.validate_state(genesis["state"])
    potential, counter, _ = die(seed, genesis["campaign_id"], "genesis", "potential/die-0", 3)
    require(genesis["state"]["pc"]["potential"] == potential + 7 and
            genesis["state"]["pc"]["potential_die"] == {"value": potential, "rejection_counter": counter},
            "The snapshot genesis roll does not replay.")
    state = deepcopy(genesis["state"])
    head, sequence = ZERO_HASH, 0
    for row in db.execute("SELECT * FROM actions ORDER BY sequence"):
        require(row["phase"] == "DELIVERED", "A pending action prevents a quiescent backup.")
        action, envelope = parse_json(row["action_json"]), parse_json(row["envelope_json"])
        require(row["action_id"] == action["action_id"] and row["action_hash"] == digest(action) and
                row["receipt_id"] == "receipt-" + digest(action)[:32] and
                row["sequence"] == sequence + 1 and
                canonical(parse_json(row["context_json"])) == canonical({"state": state, "head_hash": head, "sequence": sequence}),
                "The snapshot action reservation differs from replay.")
        context = {"campaign_id": genesis["campaign_id"], **{key:genesis[key] for key in VERSION_FIELDS},
                   "origin_epoch": 1, "seed": seed, "state": state,
                   "head_hash": head, "sequence": sequence,
                   "private_npc_fields": {tuple(pair) for pair in genesis["private_npc_fields"]}}
        engine.validate_action(action, state, head)
        require(canonical(envelope["accepted_action"]) == canonical(action), "The snapshot accepted action differs.")
        state = envelope_valid(envelope, context)
        band = "clean" if envelope["event"]["outcome"] == "routine" else envelope["event"]["outcome"]
        require(envelope["event"]["public_narration"] == action["stakes"]["bands"][band]["summary"],
                "The snapshot narration differs from the validated outcome.")
        sequence += 1
        head = envelope["event"]["event_hash"]
    require(canonical(current) == canonical({"state": state, "head_hash": head, "sequence": sequence}),
            "The snapshot current state differs from its history.")
    return genesis, current


def export_backup(controller, key, release_bundle, *, label=""):
    """Return ciphertext only. Remote uncertainty aborts without producing a backup."""
    _key(key)
    require(type(label) is str and len(label) <= 256, "The backup label is too long.")
    release = verify_release_bundle(release_bundle)
    with controller.store.locked() as db:
        require(controller.store.get(db, "initialized", False) and
                not controller.store.get(db, "recovery_blocked", False) and controller._pending(db) is None,
                "Complete pending initialization, actions, and recovery before exporting.")
        controller._context(db)
        _match_campaign_release(controller.store.get(db,"genesis"),release)
        controller._check_boundary(db)
        pages=db.execute("PRAGMA page_count").fetchone()[0]
        page_size=db.execute("PRAGMA page_size").fetchone()[0]
        require(pages*page_size <= MAX_DATABASE_BYTES,"The SQLite snapshot exceeds its byte limit.")
        snapshot = sqlite3.connect(":memory:")
        try:
            db.backup(snapshot)
            raw = snapshot.serialize()
            # SQLite documents this conversion for deserializing a WAL snapshot.
            # The backup API already copied a complete, consistent database.
            # https://sqlite.org/c3ref/deserialize.html
            require(raw.startswith(b"SQLite format 3\x00") and len(raw) >= 100,
                    "The SQLite backup has an invalid header.")
            raw = raw[:18] + b"\x01\x01" + raw[20:]
        finally:
            snapshot.close()
    validated = _memory_database(raw)
    try:
        genesis, current = _validate_snapshot(validated)
    finally:
        validated.close()
    payload = {"schema": "backup-payload-v1", "created_at": datetime.now(timezone.utc).isoformat(),
               "label": label, "campaign_id": genesis["campaign_id"], "head_hash": current["head_hash"],
               "sequence": current["sequence"], "state_hash": digest(current["state"]), "genesis_hash": genesis["genesis_hash"],
               "sqlite_b64": _b64(raw), "sqlite_sha256": sha256(raw).hexdigest(), "release_b64": _b64(release_bundle),
               "release_hash": release["bundle_hash"], "remote_binding": _remote_binding(controller.remote, genesis["campaign_id"])}
    plaintext = canonical(payload)
    require(len(plaintext) + 4096 <= MAX_BACKUP_BYTES, "The complete backup exceeds its byte limit.")
    nonce = secrets.token_bytes(12)
    header = canonical({"schema": "encrypted-backup-v1", "cipher": "AES-256-GCM", "nonce_b64": _b64(nonce)})
    aad = MAGIC + len(header).to_bytes(4, "big") + header
    return aad + _aesgcm()(_key(key)).encrypt(nonce, plaintext, aad)


def _decrypt(ciphertext, key):
    _key(key)
    require(type(ciphertext) is bytes and len(MAGIC) + 4 + 16 < len(ciphertext) <= MAX_BACKUP_BYTES
            and ciphertext.startswith(MAGIC), "Invalid encrypted backup container.")
    offset = len(MAGIC) + 4
    length = int.from_bytes(ciphertext[len(MAGIC):offset], "big")
    require(1 <= length <= 4096 and offset + length + 16 < len(ciphertext), "Invalid encrypted backup header.")
    header = _json(ciphertext[offset:offset + length], 4096)
    require(type(header) is dict and set(header) == {"schema", "cipher", "nonce_b64"} and
            header["schema"] == "encrypted-backup-v1" and header["cipher"] == "AES-256-GCM",
            "Unsupported backup encryption format.")
    nonce = _unb64(header["nonce_b64"], 12)
    require(len(nonce) == 12, "Invalid encryption nonce.")
    aad = ciphertext[:offset + length]
    cipher = _aesgcm()(_key(key))
    from cryptography.exceptions import InvalidTag
    try:
        plaintext = cipher.decrypt(nonce, ciphertext[len(aad):], aad)
    except InvalidTag as exc:
        # cryptography InvalidTag deliberately does not distinguish key/tamper.
        raise BackupError("Backup authentication failed. Check the key and file integrity.") from exc
    return _json(plaintext, MAX_BACKUP_BYTES)


def _validated_backup(ciphertext, key):
    payload = _decrypt(ciphertext, key)
    fields = {"schema", "created_at", "label", "campaign_id", "head_hash", "sequence", "state_hash",
              "genesis_hash", "sqlite_b64", "sqlite_sha256", "release_b64", "release_hash", "remote_binding"}
    require(type(payload) is dict and set(payload) == fields and payload["schema"] == "backup-payload-v1",
            "Unsupported backup payload.")
    require(type(payload["created_at"]) is str and type(payload["label"]) is str and len(payload["label"]) <= 256 and
            type(payload["campaign_id"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", payload["campaign_id"]) is not None and
            type(payload["sequence"]) is int and 0 <= payload["sequence"] <= 2**53 - 1 and
            all(type(payload[field]) is str and re.fullmatch(r"[0-9a-f]{64}", payload[field]) is not None
                for field in ("head_hash", "state_hash", "genesis_hash", "sqlite_sha256", "release_hash")),
            "The backup receipt fields are invalid.")
    _binding_valid(payload["remote_binding"], payload["campaign_id"])
    release_bytes = _unb64(payload["release_b64"], MAX_RELEASE_BYTES)
    release = verify_release_bundle(release_bytes)
    require(release["bundle_hash"] == payload["release_hash"], "The backed-up release hash differs.")
    raw = _unb64(payload["sqlite_b64"], MAX_DATABASE_BYTES)
    require(sha256(raw).hexdigest() == payload["sqlite_sha256"], "The SQLite snapshot hash differs.")
    db = _memory_database(raw)
    try:
        try:
            genesis, current = _validate_snapshot(db)
        except (KeyError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            raise BackupError("The snapshot history failed validation.") from exc
        _match_campaign_release(genesis,release)
        require((payload["campaign_id"], payload["head_hash"], payload["sequence"], payload["state_hash"], payload["genesis_hash"]) ==
                (genesis["campaign_id"], current["head_hash"], current["sequence"], digest(current["state"]), genesis["genesis_hash"]),
                "The backup receipt differs from its database.")
        return payload, db, genesis, current, release_bytes, release
    except BaseException:
        db.close()
        raise


def _receipt(payload, genesis):
    return {"schema": "backup-restore-receipt-v1", "campaign_id": payload["campaign_id"],
            "head_hash": payload["head_hash"], "sequence": payload["sequence"],
            "release_hash": payload["release_hash"], "remote_binding": deepcopy(payload["remote_binding"]),
            **{key:genesis[key] for key in VERSION_FIELDS},
            "mode": "read-only-maintenance", "network_verification": "not-performed", "writer_transfer": "unsupported"}


def inspect_backup(ciphertext, key):
    """Authenticate and replay an encrypted artifact without writing files."""
    payload, db, genesis, _, _, _ = _validated_backup(ciphertext, key)
    db.close()
    return _receipt(payload,genesis)


def restore_backup(ciphertext, key, destination):
    """Restore a verified database as read-only maintenance. No network calls."""
    payload, db, genesis, current, release_bytes, release = _validated_backup(ciphertext, key)
    try:
        target = Path(destination).expanduser()
        require(not target.is_symlink(), "The restore destination cannot be a symbolic link.")
        target = target.resolve()
        require(not target.exists() or (target.is_dir() and not any(target.iterdir())), "Restore requires an empty destination.")
        # Derive public fields again. Never trust a stored public cache during restore.
        context = {**current, "campaign_id": genesis["campaign_id"],
                   **{key:genesis[key] for key in VERSION_FIELDS}}
        CampaignStore.set(db, "registration_path", str(target))
        CampaignStore.set(db, "maintenance_read_only", True)
        CampaignStore.set(db, "recovery_blocked", False)
        CampaignStore.set(db, "public", Controller._projections(context))
        CampaignStore.set(db, "restored_release_hash", release["bundle_hash"])
        db.commit()
        restored_bytes = db.serialize()
    finally:
        db.close()
    target = private_directory(target)
    created = []
    try:
        # Publish the usable database last. No archive member is extracted.
        bundle_path = target / "release-bundle.json"
        _exclusive_bytes(bundle_path, release_bytes)
        created.append(bundle_path)
        database_path = target / "campaign.sqlite3"
        _exclusive_bytes(database_path, restored_bytes)
        created.append(database_path)
        _sync_directory(target)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return _receipt(payload,genesis)
