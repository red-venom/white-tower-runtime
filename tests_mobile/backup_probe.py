#!/usr/bin/env python3
"""Rehearse a complete PostgreSQL backup/restore using local disposable data.

Requires a running local PostgreSQL cluster and a role allowed to create DBs.
Both fixed disposable database names must be supplied explicitly; existing
databases are never cleared, dropped, or overwritten. No production database
URL is accepted. The custom-format backup contains credentials and private
dice seeds and therefore must be written beneath .runtime with mode 600.

Example from the repository parent:
  PYTHONPATH=mobile-runtime .venv-mobile/bin/python \
    mobile-runtime/tests_mobile/backup_probe.py \
    --source-database mobile_pilot_backup_source \
    --restore-database mobile_pilot_backup_restore \
    --backup-file .runtime/mobile-pilot-backup.dump
"""
import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from mobile_game import rules
from mobile_game.gm import RESERVATION_MICRO_USD
from mobile_game.store import Store, Problem, digest


SOURCE_DB = "mobile_pilot_backup_source"
RESTORE_DB = "mobile_pilot_backup_restore"
TABLES = ("mobile_players", "mobile_sessions", "mobile_campaigns", "mobile_actions", "mobile_rate_limits",
          "mobile_gm_budget", "mobile_gm_requests")


class ProbeFailure(Exception):
    """Fixed safe diagnostic labels, never database errors or credential data."""


def require(condition, label):
    if not condition:
        raise ProbeFailure(label)


def normalize(value):
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"postgres_bytea_hex": bytes(value).hex()}
    if isinstance(value, (datetime, date)):
        return {"postgres_timestamp": value.isoformat()}
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    return value


def encoded(value):
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def snapshot(store, expected_database):
    with store.connect() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        target = connection.execute("SELECT current_database() AS name, host(inet_server_addr()) AS address").fetchone()
        require(target["name"] == expected_database and target["address"] in ("127.0.0.1", "::1"),
                "explicit_local_disposable_database_verified")
        names = connection.execute("""SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
              AND left(table_name,7)='mobile_'""").fetchall()
        require({row["table_name"] for row in names} == set(TABLES),
                "all_mobile_tables_must_be_explicitly_covered")
        result = {}
        for table in TABLES:
            rows = connection.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))).fetchall()
            normalized = [normalize(row) for row in rows]
            result[table] = sorted(normalized, key=encoded)
        # A data-only comparison would miss a restored schema lacking the
        # unique revision constraint, a foreign key, a default, or an index.
        result["table_schema"] = {
            "columns": connection.execute("""SELECT table_name,column_name,ordinal_position,
                data_type,udt_schema,udt_name,is_nullable,column_default,
                character_maximum_length,numeric_precision,numeric_scale
                FROM information_schema.columns WHERE table_schema='public'
                  AND table_name=ANY(%s) ORDER BY table_name,ordinal_position""", (list(TABLES),)).fetchall(),
            "constraints": connection.execute("""SELECT t.relname AS table_name,c.conname AS name,
                c.contype AS type,pg_get_constraintdef(c.oid,true) AS definition
                FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname='public' AND t.relname=ANY(%s)
                ORDER BY t.relname,c.conname""", (list(TABLES),)).fetchall(),
            "indexes": connection.execute("""SELECT tablename,indexname,indexdef
                FROM pg_indexes WHERE schemaname='public' AND tablename=ANY(%s)
                ORDER BY tablename,indexname""", (list(TABLES),)).fetchall(),
            "triggers": connection.execute("""SELECT t.relname AS table_name,g.tgname AS name,
                pg_get_triggerdef(g.oid,true) AS definition
                FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE NOT g.tgisinternal AND n.nspname='public' AND t.relname=ANY(%s)
                ORDER BY t.relname,g.tgname""", (list(TABLES),)).fetchall(),
        }
        return result


def private_backup_path(value):
    supplied = Path(value).expanduser().absolute()
    require(not supplied.is_symlink(), "backup_must_not_be_symlink")
    path = supplied.resolve(strict=False)
    require(".runtime" in path.parts, "backup_must_be_under_runtime")
    require(path.parent.is_dir(), "backup_parent_must_exist")
    require(not path.exists(), "backup_file_must_be_new")
    return path


def new_report_path(value, backup_file):
    supplied = Path(value).expanduser().absolute()
    require(not supplied.is_symlink(), "report_must_not_be_symlink")
    path = supplied.resolve(strict=False)
    require(path != Path(backup_file).expanduser().resolve(strict=False), "report_must_not_replace_backup")
    require(not path.exists(), "report_file_must_be_new")
    return path


def request_for(packet, choice_id):
    require(packet.get("disposable") is True, "only_disposable_campaign_supported")
    candidates = [choice for choice in packet["state"]["choices"] if choice["id"] == choice_id]
    require(len(candidates) == 1, "sample_choice_available")
    return {"action_id": str(uuid.uuid4()), "expected_revision": packet["revision"],
            "choice_id": choice_id, "choice_hash": candidates[0]["choice_hash"]}


def run(args, report):
    backup = private_backup_path(args.backup_file)
    dump_program, restore_program = shutil.which("pg_dump"), shutil.which("pg_restore")
    require(bool(dump_program and restore_program), "postgresql_backup_utilities_available")
    require(args.source_database == SOURCE_DB and args.restore_database == RESTORE_DB,
            "explicit_disposable_database_names_required")
    require(args.host in ("127.0.0.1", "::1"), "only_literal_loopback_hosts_allowed")
    common = {"host": args.host, "hostaddr": args.host, "port": args.port, "user": args.user,
              "connect_timeout": 10, "sslmode": "disable", "options": "-c client_encoding=UTF8"}
    with psycopg.connect(make_conninfo(dbname="postgres", **common),
                         row_factory=dict_row, autocommit=True) as admin:
        address = admin.execute("SELECT host(inet_server_addr()) AS address").fetchone()["address"]
        require(address in ("127.0.0.1", "::1"), "admin_connection_is_local")
        existing = admin.execute("SELECT datname FROM pg_database WHERE datname = ANY(%s)",
                                 ([SOURCE_DB, RESTORE_DB],)).fetchall()
        require(not existing, "refusing_to_replace_existing_disposable_database")
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(SOURCE_DB)))
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(RESTORE_DB)))
    report["checks_passed"].append("new_local_disposable_source_and_restore_databases")
    policy = {"max_requests": 2, "budget_micro_usd": 2 * RESERVATION_MICRO_USD,
              "reservation_micro_usd": RESERVATION_MICRO_USD}
    source = Store(make_conninfo(dbname=SOURCE_DB, **common), gm_policy=policy)
    restored = Store(make_conninfo(dbname=RESTORE_DB, **common), gm_policy=policy)
    source.initialize()
    credentials = source.new_session()
    identity = source.session(credentials["token"])
    owner = identity["player_id"]
    packet = source.create(owner, str(uuid.uuid4()))
    fixture = rules.initial_state()
    fixture["backup_fixture_extension"] = {"version": 1, "nested": [None, False, 0, "Cairhien — é", {"value": [1, 2, 3]}]}
    fixture["world"]["private_fixture"] = {"label": "disposable backup continuity only"}
    with source.connect() as connection:
        connection.execute("UPDATE mobile_campaigns SET state=%s,head=%s WHERE id=%s",
                           (Jsonb(fixture), digest({"campaign_id": packet["id"], "revision": 0, "state": fixture}), packet["id"]))
    packet = source.read(owner, packet["id"])
    for choice in ("accept_task", "prepare_grip"):
        packet = source.act(owner, packet["id"], request_for(packet, choice))
    original_request = request_for(packet, "cross_courtyard")
    original_response = source.act(owner, packet["id"], original_request)
    require(original_response["events"][-1]["roll"] is not None, "fixture_contains_real_server_roll")
    packet = original_response
    if not packet["state"]["completed"]:
        packet = source.act(owner, packet["id"], request_for(packet, "covered_route"))
    packet = source.act(owner, packet["id"], request_for(packet, "quiet_interval"))
    require(packet["state"]["completed"], "fixture_episode_complete")
    # Exercise completed and uncertain interpreter reservations using strictly
    # local functions. No API key, network provider, or paid calls are involved.
    def fixture_interpreter(public, prompt):
        require("world" not in public and "private_fixture" not in public,
                "interpreter_receives_public_projection_only")
        return {"kind": "answer", "choice_id": None, "message": "The optional task is complete.",
                "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}
    gm_completed_request = {"request_id": str(uuid.uuid4()), "expected_revision": packet["revision"],
                            "prompt": "Is the optional task complete?"}
    gm_completed = source.gm_request(owner, packet["id"], gm_completed_request, fixture_interpreter)
    require(gm_completed["status"] == "completed", "completed_gm_fixture_saved")
    gm_unknown_request = {**gm_completed_request, "request_id": str(uuid.uuid4())}
    def crash_after_provider(point):
        if point == "after_provider":
            raise ProbeFailure("intentional_disposable_worker_crash")
    try:
        source.gm_request(owner, packet["id"], gm_unknown_request, fixture_interpreter, fault=crash_after_provider)
    except ProbeFailure as exc:
        require(str(exc) == "intentional_disposable_worker_crash", "expected_fixture_crash")
    with source.connect() as connection:
        connection.execute("UPDATE mobile_gm_requests SET expires_at=now()-interval '1 second' WHERE request_id=%s",
                           (gm_unknown_request["request_id"],))
    gm_unknown = source.gm_status(owner, packet["id"], gm_unknown_request["request_id"])
    require(gm_unknown["status"] == "unknown", "uncertain_gm_fixture_is_terminal")
    checkpoint = source.read(owner, packet["id"])
    exported = source.export(owner, packet["id"])
    adventure_packet = source.create(owner, str(uuid.uuid4()), "gallery-letter-v1")
    for choice in ("look_gallery", "air_letter", "study_block"):
        adventure_packet = source.act(owner, adventure_packet["id"], request_for(adventure_packet, choice))
    require(adventure_packet["companion"]["last_cast"]["strain_paid"] == 1,
            "adventure_fixture_has_channeling_and_learning")
    source.rate_limit("disposable-backup-fixture", 100, 60)
    # A second pre-existing session demonstrates all session rows survive.
    second_session = source.new_session(credentials["recovery_code"])
    source.notes(owner, adventure_packet["id"], (0, "Disposable notebook: remember the completed lesson."))
    for choice in ("next_chapter", "garden_listen", "garden_welcome", "garden_finish"):
        adventure_packet = source.act(owner, adventure_packet["id"], request_for(adventure_packet, choice))
    source_snapshot = snapshot(source, SOURCE_DB)
    require(all(source_snapshot[table] for table in TABLES), "all_mobile_tables_populated")
    report["checks_passed"].append("full_disposable_fixture_with_private_seed_and_sessions")
    cli_connection = ["--host", args.host, "--port", str(args.port), "--username", args.user, "--no-password"]
    # Explicit hostaddr prevents ambient libpq service/host-address settings
    # redirecting a utility away from the literal loopback target.
    child_environment = {key: value for key, value in os.environ.items()
                         if key not in ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR")}
    child_environment["PGHOSTADDR"] = args.host
    # pg_dump writes directly to the exclusively created private file, never to
    # a captured tool output or a temporary public file.
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        result = subprocess.run([dump_program, *cli_connection, "--dbname", SOURCE_DB,
                                 "--format=custom", "--no-owner", "--no-acl"],
                                stdout=stream, stderr=subprocess.PIPE, check=False, timeout=120,
                                env=child_environment)
        stream.flush()
        os.fsync(stream.fileno())
    require(result.returncode == 0, "pg_dump_succeeded")
    require(backup.stat().st_mode & 0o777 == 0o600, "backup_file_mode_600")
    with backup.open("rb") as stream:
        require(stream.read(5) == b"PGDMP", "postgresql_custom_backup_format")
    report["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    report["checks_passed"].append("pg_dump_custom_backup_created_with_mode_600")
    result = subprocess.run([restore_program, *cli_connection, "--dbname", RESTORE_DB,
                             "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction", str(backup)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=120,
                            env=child_environment)
    require(result.returncode == 0, "pg_restore_succeeded")
    restored_snapshot = snapshot(restored, RESTORE_DB)
    require(restored_snapshot == source_snapshot, "all_restored_mobile_rows_match_exactly")
    report["source_tables_sha256"] = hashlib.sha256(encoded(source_snapshot)).hexdigest()
    report["restored_tables_sha256"] = hashlib.sha256(encoded(restored_snapshot)).hexdigest()
    report["checks_passed"].append("every_mobile_table_restored_exactly_including_private_seed_and_sessions")
    report["checks_passed"].append("table_columns_constraints_indexes_and_triggers_match")
    def must_not_call(*args):
        raise ProbeFailure("restored_request_must_not_recall_provider")
    for original, expected in ((gm_completed_request, gm_completed), (gm_unknown_request, gm_unknown)):
        require(restored.gm_request(owner, packet["id"], original, must_not_call) == expected,
                "gm_result_and_terminal_uncertainty_survive_restore")
    try:
        restored.gm_request(owner, packet["id"], {**gm_completed_request, "request_id": str(uuid.uuid4())}, must_not_call)
        raise ProbeFailure("restored_budget_must_remain_exhausted")
    except Problem as exc:
        require(exc.code == "GM_BUDGET_EXHAUSTED", "restored_budget_remains_exhausted")
    report["checks_passed"].append("gm_responses_uncertain_requests_and_lifetime_spending_cap_restored_without_provider_calls")
    require(restored.session(credentials["token"]) == identity, "original_session_restored")
    require(restored.session(second_session["token"])["player_id"] == owner, "second_session_restored")
    require(restored.read(owner, packet["id"]) == checkpoint, "checkpoint_and_history_restored")
    require(restored.read(owner, adventure_packet["id"]) == {k:v for k,v in adventure_packet.items() if k != "replayed"},
            "adventure_character_relationships_learning_and_cast_receipt_restored")
    report["checks_passed"].append("adventure_character_relationships_learning_and_cast_receipt_restored")
    require(restored.notes(owner, adventure_packet["id"]) == source.notes(owner, adventure_packet["id"]), "personal_notebook_restored")
    report["checks_passed"].append("personal_notebook_restored")
    replay = restored.act(owner, packet["id"], original_request)
    require(replay == {**original_response, "replayed": True}, "exact_original_roll_response_restored")
    require(restored.read(owner, packet["id"]) == checkpoint, "retry_keeps_latest_checkpoint")
    report["checks_passed"].append("original_committed_dice_and_exact_retry_survive_restore")
    restored_export = restored.export(owner, packet["id"])
    ignored = {"exported_at", "sha256"}
    require({key: value for key, value in restored_export.items() if key not in ignored} ==
            {key: value for key, value in exported.items() if key not in ignored},
            "complete_export_state_and_events_restored")
    for database, expected_name in ((source, SOURCE_DB), (restored, RESTORE_DB)):
        with database.connect() as connection:
            row = connection.execute("SELECT seed FROM mobile_campaigns WHERE id=%s", (packet["id"],)).fetchone()
        # The exact private seed was compared in the table snapshot. A stable
        # hypothetical next action confirms the restored dice function uses it.
        future_dice = database.dice(row["seed"], packet["id"], "00000000-0000-4000-8000-000000000001")
        if expected_name == SOURCE_DB:
            expected_future_dice = future_dice
        else:
            require(future_dice == expected_future_dice, "future_dice_stream_continuity")
    recovered = restored.new_session(credentials["recovery_code"])
    require(restored.session(recovered["token"])["player_id"] == owner, "recovery_code_restored")
    require(restored.read(owner, packet["id"]) == checkpoint, "recovered_owner_has_exact_game")
    report["checks_passed"].append("session_and_recovery_code_resume_same_saved_game")
    report["checks_passed"].append("complete_export_unknown_fields_and_dice_stream_preserved")
    report["status"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", required=True, choices=(SOURCE_DB,))
    parser.add_argument("--restore-database", required=True, choices=(RESTORE_DB,))
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--user", default="mobile_test")
    parser.add_argument("--backup-file", required=True)
    parser.add_argument("--report-file")
    args = parser.parse_args()
    report = {"status": "failed", "checks_passed": [],
              "scope": "local_disposable_pg_dump_pg_restore_capability",
              "hosted_scheduled_backups_verified": False}
    report_target = None
    try:
        if args.report_file:
            report_target = new_report_path(args.report_file, args.backup_file)
        run(args, report)
    except Exception as exc:
        # Suppress subprocess stderr, DB exception details, fixture contents,
        # seeds, session tokens, and recovery codes even when a check fails.
        report["failure"] = str(exc) if isinstance(exc, ProbeFailure) else type(exc).__name__
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if report_target is not None:
        try:
            report_target.parent.mkdir(parents=True, exist_ok=True)
            with report_target.open("x", encoding="utf-8") as stream:
                stream.write(output)
        except Exception:
            report.update(status="failed", failure="report_write_failed")
            output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    print(output, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
