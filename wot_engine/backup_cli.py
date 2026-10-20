"""Safe CLI helpers. Argparse owns paths only; key bytes never enter argv."""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat
import tempfile

from .backup import (BackupError, MAX_BACKUP_BYTES, _exclusive_bytes, _sync_directory,
                     build_release_bundle, export_backup, generate_key, inspect_backup,
                     restore_backup, verify_release_bundle, require, VERSION_FIELDS)
from .contracts import canonical
from .controller import Controller
from .storage import FileRemote, atomic_json, file_lock, private_directory, read_json


def _read_file(path, maximum, *, private=False):
    path = Path(path).expanduser()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum, "The input file is invalid or exceeds its size limit.")
        if private:
            require(info.st_uid == os.getuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                    "The key must be an owner-only regular file without links.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        require(len(data) <= maximum, "The input file grew beyond its size limit.")
        return data
    finally:
        os.close(descriptor)


def read_key_file(path):
    data = _read_file(path, 32, private=True)
    require(len(data) == 32, "The key file must contain exactly 32 binary bytes.")
    return data


def create_backup_key(output_path):
    """Create one exclusive 0600 key file. Never return its contents."""
    path = Path(output_path).expanduser()
    require(not path.is_symlink() and not path.exists(), "The key output already exists.")
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, mode=0o700)
    info = parent.stat()
    require(not parent.is_symlink() and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
            "Create the key inside a private directory owned by the current user.")
    _exclusive_bytes(path, generate_key())
    _sync_directory(parent)
    return {"status": "OK", "key_file": str(path.resolve()), "key_material_displayed": False,
            "recovery_note": "Retain this key separately from encrypted backups. No external key copy was created."}


def _load_runtime(directory):
    directory = Path(directory).expanduser().resolve()
    config = read_json(directory / "runtime.json")
    require(config.get("schema") == "runtime-config-v1", "Unsupported runtime configuration.")
    if config["remote_kind"] == "file":
        remote = FileRemote(config["remote_directory"])
    elif config["remote_kind"] == "notion":
        from .notion_bridge import NotionRemote
        remote = NotionRemote(directory / "transport", config["campaign_id"], config["data_source_id"])
    else:
        raise BackupError("The configured remote is unsupported.")
    return directory, config, remote, Controller(directory / "campaign", remote)


def _finish_backup_bridge(remote, operation):
    if hasattr(remote, "bridge"):
        active = remote.bridge.meta("active")
        if active and active["operation"] == operation:
            remote.bridge.finish()


def _publish_backup(output, ciphertext):
    """Publish complete ciphertext without replacing any existing destination."""
    descriptor, temporary = tempfile.mkstemp(prefix=".wot-backup-", suffix=".pending", dir=output.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        # Both paths are on the same filesystem. A hard link publishes the
        # complete inode atomically and fails if the destination already exists.
        os.link(temporary, output, follow_symlinks=False)
        _sync_directory(output.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def backup_runtime(runtime_path, key_file, output_path):
    """Resume the same output-path job until a verified encrypted file exists."""
    key = read_key_file(key_file)
    output = Path(output_path).expanduser()
    require(not output.is_symlink(), "The backup output cannot be a symbolic link.")
    output = output.resolve()
    require(output.parent.is_dir(), "Create the backup output directory first.")
    directory, config, remote, controller = _load_runtime(runtime_path)
    operation = "backup:" + sha256(str(output).encode("utf-8")).hexdigest()
    jobs = private_directory(directory / "backup-jobs")
    job_path = jobs / (operation.split(":", 1)[1] + ".json")
    source_path = jobs / (operation.split(":", 1)[1] + ".release.json")
    try:
        with file_lock(jobs / "backup.lock"):
            if job_path.exists():
                job = read_json(job_path)
                require(job["output"] == str(output) and job["key_fingerprint"] == sha256(key).hexdigest()
                        and job["campaign_id"] == config["campaign_id"], "This backup job has different inputs.")
                bundle = _read_file(source_path, 16 * 1024 * 1024)
                require(verify_release_bundle(bundle)["bundle_hash"] == job["release_hash"], "The frozen backup source bundle differs.")
            else:
                require(not output.exists(), "The backup output already exists.")
                with controller.store.locked() as db:
                    genesis=controller.store.get(db,"genesis")
                    require(type(genesis) is dict and genesis.get("campaign_id")==config["campaign_id"],
                            "Initialize the campaign before creating its release bundle.")
                    versions={key:genesis[key] for key in VERSION_FIELDS}
                bundle = build_release_bundle(Path(__file__).resolve().parent.parent,**versions)
                release = verify_release_bundle(bundle)
                job = {"schema": "backup-job-v1", "operation": operation, "campaign_id": config["campaign_id"],
                       "output": str(output), "key_fingerprint": sha256(key).hexdigest(),
                       "release_hash": release["bundle_hash"], "status": "PENDING", "ciphertext_sha256": None, "receipt": None}
                if source_path.exists():
                    require(_read_file(source_path, 16 * 1024 * 1024) == bundle, "An orphaned source bundle differs.")
                else:
                    _exclusive_bytes(source_path, bundle)
                atomic_json(job_path, job)
            if output.exists():
                ciphertext = _read_file(output, MAX_BACKUP_BYTES)
                require(job["ciphertext_sha256"] is not None and sha256(ciphertext).hexdigest() == job["ciphertext_sha256"],
                        "An existing encrypted output differs from this backup job.")
                receipt = inspect_backup(ciphertext, key)
                require(canonical(receipt) == canonical(job["receipt"]), "The encrypted output receipt differs.")
                _finish_backup_bridge(remote, operation)
            else:
                require(job["status"] != "COMPLETE", "A completed backup output is missing.")
                if hasattr(remote, "bridge"):
                    remote.bridge.begin(operation)
                ciphertext = export_backup(controller, key, bundle)
                receipt = inspect_backup(ciphertext, key)
                require(receipt["campaign_id"] == config["campaign_id"], "The backup campaign differs from its runtime.")
                job["ciphertext_sha256"] = sha256(ciphertext).hexdigest()
                job["receipt"] = receipt
                atomic_json(job_path, job)
                _publish_backup(output, ciphertext)
                _finish_backup_bridge(remote, operation)
            job["status"] = "COMPLETE"
            atomic_json(job_path, job)
            return {"status": "OK", "backup_file": str(output), "ciphertext_sha256": job["ciphertext_sha256"],
                    "campaign_id": receipt["campaign_id"], "head_hash": receipt["head_hash"],
                    "release_hash": receipt["release_hash"], "key_material_displayed": False,
                    "independent_destination_verified": False}
    finally:
        if hasattr(remote, "bridge"):
            remote.bridge.close()


def restore_runtime(input_path, key_file, runtime_path):
    """Build a usable read-only runtime wrapper without remote calls or transfer."""
    key = read_key_file(key_file)
    ciphertext = _read_file(input_path, MAX_BACKUP_BYTES)
    receipt = inspect_backup(ciphertext, key)
    target = Path(runtime_path).expanduser()
    require(not target.is_symlink(), "The runtime destination cannot be a symbolic link.")
    target = target.resolve()
    require(not target.exists() or (target.is_dir() and not any(target.iterdir())), "Runtime restore requires an empty destination.")
    target = private_directory(target)
    campaign = target / "campaign"
    restore_backup(ciphertext, key, campaign)
    binding = receipt["remote_binding"]
    # File simulation paths are not portable. Keep the old location as inert
    # recovery evidence and use an empty local placeholder for read-only queries.
    config = {"schema": "runtime-config-v1", "campaign_id": receipt["campaign_id"],
              **{key:receipt[key] for key in VERSION_FIELDS},
              "remote_kind": binding["kind"], "remote_directory": str(target / "unverified-file-remote"),
              "data_source_id": binding.get("data_source_id"), "disposable": False,
              "maintenance_read_only": True, "recovery_remote_binding": binding}
    _exclusive_bytes(target / "runtime.json", canonical(config))
    _sync_directory(target)
    return {**receipt, "status": "OK", "runtime_path": str(target),
            "available": ["sheet", "journal", "recap", "known-facts", "training", "status"],
            "key_material_displayed": False}
