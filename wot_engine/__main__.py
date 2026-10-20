"""Command interface. Public output never includes the campaign seed or Potential."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys

from . import __version__
from .contracts import ContractError, canonical, digest, require
from .storage import atomic_json, read_json, FileRemote, RemotePending
from .backup import BackupError


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_runtime(directory):
    directory = Path(directory).resolve()
    config = read_json(directory / "runtime.json")
    if config["remote_kind"] == "file":
        remote = FileRemote(config["remote_directory"])
    else:
        from .notion_bridge import NotionRemote
        remote = NotionRemote(directory / "transport", config["campaign_id"], config["data_source_id"])
    from .controller import Controller
    return directory, config, remote, Controller(directory / "campaign", remote)


def drive(directory):
    directory, config, remote, controller = load_runtime(directory)
    job = read_json(directory / "current-job.json")
    if hasattr(remote, "bridge"):
        remote.bridge.begin(job["id"])
    try:
        if job["kind"] == "initialize":
            data = read_json(directory / "initialization.json")
            result = controller.initialize(config["campaign_id"], data["state"], bytes.fromhex(data["seed_hex"]),
                                           **data.get("versions", {}))
        elif job["kind"] == "action":
            result = controller.execute(job["action"], job["narrations"])
        else:
            result = controller.recover()
    except RuntimeError as exc:
        # A completed connector read can lag behind its acknowledged write.
        # Discard read receipts only; mutation receipts keep their exact identity.
        if hasattr(remote,"bridge") and getattr(exc,"code",None) in ("REMOTE_UNCERTAIN","PROJECTION_PENDING"):
            remote.bridge.refresh_reads()
            result = controller._pending_response(config["campaign_id"],job.get("action",{}).get("action_id"))
        else:
            raise
    if result.get("status") == "OK":
        if hasattr(remote, "bridge"):
            remote.bridge.finish()
        job["complete"] = True
        atomic_json(directory / "current-job.json", job)
    emit(result)
    return 0


def create_job(directory, job):
    path = Path(directory) / "current-job.json"
    if path.exists():
        old = read_json(path)
        if not old.get("complete"):
            require(old["id"] == job["id"] and canonical({k:v for k,v in old.items() if k!='complete'}) == canonical(job),
                    "Finish the pending job before starting another action")
            return
    atomic_json(path, job)


def initialize(args):
    from .rulesets import get_rules, LEGACY, FULL
    version = FULL if args.ruleset == "full" else LEGACY
    engine = get_rules(*version)
    directory = Path(args.path).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = directory / "runtime.json"
    if config_path.exists():
        existing = read_json(config_path)
        require(existing["campaign_id"] == args.campaign, "Directory belongs to another campaign")
        require(existing.get("ruleset", "initial-six") == args.ruleset, "Existing campaign uses another ruleset")
        return drive(directory)
    require(args.remote != "notion" or args.data_source is not None, "Notion data source is required")
    config = {"schema":"runtime-config-v1", "campaign_id":args.campaign, "remote_kind":args.remote,
              "remote_directory":str(Path(args.remote_path or str(directory)+"-remote").resolve()),
              "data_source_id":args.data_source, "disposable":True, "ruleset":args.ruleset}
    seed = secrets.token_bytes(32)
    extra = {}
    if args.character:
        require(args.ruleset == "full", "Character choices require the full ruleset")
        extra['character'] = read_json(args.character)
    state = engine.initial_state(name="Test novice", seed=seed, campaign_id=args.campaign, **extra)
    atomic_json(config_path, config)
    atomic_json(directory / "initialization.json", {"seed_hex":seed.hex(),"state":state,
                "versions":dict(zip(("rules_version","content_version","engine_version"),version))})
    create_job(directory, {"id":"initialize:"+args.campaign,"kind":"initialize"})
    drive(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="white-tower", description="White Tower game controller")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("character-template", help="Print blank identity choices and legal example ratings")
    sub.add_parser("check-character", help="Validate creation choices without creating a campaign").add_argument("--input", required=True)
    key_command=sub.add_parser("backup-key",help="Create a private recovery key file; never prints the key")
    key_command.add_argument("--output",required=True)
    backup_command=sub.add_parser("backup",help="Export an authenticated encrypted backup at a verified boundary")
    backup_command.add_argument("--path",required=True)
    backup_command.add_argument("--key-file",required=True)
    backup_command.add_argument("--output",required=True)
    restore_command=sub.add_parser("restore",help="Restore into an empty runtime as read-only maintenance")
    restore_command.add_argument("--path",required=True)
    restore_command.add_argument("--key-file",required=True)
    restore_command.add_argument("--input",required=True)
    init = sub.add_parser("init-demo", help="Initialize a disposable test character")
    init.add_argument("--path",required=True); init.add_argument("--campaign",required=True)
    init.add_argument("--remote",choices=("file","notion"),default="file")
    init.add_argument("--remote-path"); init.add_argument("--data-source")
    init.add_argument("--character",help="Validated character-v1 JSON choices for a disposable full-game rehearsal")
    init.add_argument("--ruleset",choices=("initial-six","full"),default="initial-six",
                      help="Full is the experimental expansion; both choices create disposable campaigns only")
    player_commands = ("sheet","recap","known-facts","training","journal","show-roll","pause","choices","weaves")
    sub.add_parser('play',help='Open the interactive rehearsal player console').add_argument('--path',required=True)
    course=sub.add_parser('course',help='Read complete course details at the verified public save')
    course.add_argument('--path',required=True)
    course.add_argument('--course-id',required=True)
    for command in ("continue","status","packet","recover",*player_commands):
        sub.add_parser(command).add_argument("--path",required=True)
    offer = sub.add_parser("offer",help="Preview the stakes before accepting an action")
    offer.add_argument("--path",required=True); offer.add_argument("--intent",required=True)
    offer.add_argument("--action-id",required=True); offer.add_argument("--output",required=True)
    choose = sub.add_parser("choose",help="Preview a current choice without writing an intent file")
    choose.add_argument("--path",required=True); choose.add_argument("--choice",required=True)
    choose.add_argument("--action-id",required=True); choose.add_argument("--output",required=True)
    skip = sub.add_parser("skip-time",help="Preview safe waiting; scheduled events and ordinary rules still apply")
    skip.add_argument("--path",required=True); skip.add_argument("--seconds",type=int,required=True)
    skip.add_argument("--action-id",required=True); skip.add_argument("--output",required=True)
    stakes = sub.add_parser("stakes",help="Read the concise view of a frozen offer")
    stakes.add_argument("--offer",required=True)
    correct = sub.add_parser("correct",help="Record a correction request without changing history or dice")
    correct.add_argument("--path",required=True); correct.add_argument("--action-id",required=True)
    correct.add_argument("--text",required=True)
    dashboard = sub.add_parser("dashboard",help="Export the released public scene, sheet, training and journal")
    dashboard.add_argument("--path",required=True); dashboard.add_argument("--output",required=True)
    accept = sub.add_parser("accept",help="Resolve a previously shown offer")
    accept.add_argument("--path",required=True); accept.add_argument("--offer",required=True)
    accept.add_argument("--acceptance-ref",required=True)
    bridge = sub.add_parser("bridge",help="Private controller-to-Notion transport; never show payloads in narration")
    bridge.add_argument("operation",choices=("claim","complete","status","refresh-reads","reconcile","retry-read","start-dispatch"))
    bridge.add_argument("--path",required=True); bridge.add_argument("--request-id")
    bridge.add_argument("--response-file")
    bridge.add_argument("--invocation-id")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            emit({"engine":__version__,"python":sys.version.split()[0],"python_supported":sys.version_info[:2]==(3,13),
                  "sqlite":sqlite3.sqlite_version,"storage":"SQLite WAL/FULL; process lock", "live_release":False})
        elif args.command == "character-template":
            from .creation import template
            emit(template())
        elif args.command == "check-character":
            from .creation import validate
            profile = read_json(args.input)
            validate(profile)
            emit({"valid":True,"name":profile['name'],"campaign_created":False})
        elif args.command == "stakes":
            from .player import readable_stakes
            proposal = read_json(args.offer)
            require(digest(proposal['stakes'])==proposal['stakes_hash'], 'Offer hash mismatch')
            emit(readable_stakes(proposal['stakes']))
        elif args.command == 'course':
            _,_,_,controller=load_runtime(args.path)
            emit(controller.public_course(args.course_id))
        elif args.command == 'play':
            from .console import run
            return run(args.path)
        elif args.command == "init-demo": initialize(args)
        elif args.command == "backup-key":
            from .backup_cli import create_backup_key
            emit(create_backup_key(args.output))
        elif args.command == "backup":
            from .backup_cli import backup_runtime
            emit(backup_runtime(args.path,args.key_file,args.output))
        elif args.command == "restore":
            from .backup_cli import restore_runtime
            emit(restore_runtime(args.input,args.key_file,args.path))
        elif args.command == "bridge":
            from .notion_bridge import DurableBridge
            queue = DurableBridge(Path(args.path)/"transport")
            try:
                if args.operation == "claim": emit(queue.claim())
                elif args.operation == "start-dispatch": emit(queue.start_dispatch(args.invocation_id))
                elif args.operation == "status": emit(queue.summary())
                elif args.operation == "refresh-reads":
                    queue.refresh_reads()
                    emit({"refreshed":True,"mutations_repeated":False})
                elif args.operation == "retry-read":
                    require(bool(args.request_id),"Request ID is required")
                    emit(queue.retry_read(args.request_id))
                elif args.operation == "reconcile":
                    require(bool(args.request_id),"Request ID is required")
                    emit(queue.reconcile(args.request_id))
                else:
                    require(bool(args.request_id and args.response_file),"Request and response file are required")
                    queue.complete(args.request_id,json.loads(Path(args.response_file).read_text()))
                    emit({"recorded":True,"request_id":args.request_id})
            finally: queue.close()
        elif args.command == "continue": drive(args.path)
        else:
            directory, config, remote, controller = load_runtime(args.path)
            if args.command == "status": emit(controller.public_status())
            elif args.command == "packet": emit(controller.public_packet())
            elif args.command in player_commands:
                from .player import query
                emit(query(controller,args.command))
            elif args.command == "correct":
                from .player import correction_request
                emit(correction_request(controller,directory,args.action_id,args.text))
            elif args.command == "dashboard":
                from .dashboard import render
                from .backup import _exclusive_bytes
                output=Path(args.output)
                require(not output.exists(),"Choose a new dashboard output file")
                _exclusive_bytes(output,render(controller).encode('utf-8'))
                emit({"dashboard":str(output.resolve()),"head_hash":controller.public_packet()['head_hash'],"fictional_time_advanced":False})
            elif args.command == "recover":
                create_job(directory,{"id":"recover:"+secrets.token_hex(8),"kind":"recover"})
                drive(directory)
            elif args.command in ("offer", "choose", "skip-time"):
                build_action = controller.rules_engine().build_action
                job_path = directory/"current-job.json"
                require(not job_path.exists() or read_json(job_path).get("complete"),"Finish pending work before a new offer")
                if args.command == "skip-time":
                    intent = {"verb":"wait", "seconds":args.seconds}
                elif args.command == "choose":
                    from .player import select_choice
                    intent = select_choice(controller,args.choice)
                else:
                    intent = json.loads(Path(args.intent).read_text())
                head = controller.public_packet()["head_hash"]
                action = build_action(controller.trusted_state(),head,config["campaign_id"],args.action_id,intent,"preview-only")
                proposal = {"campaign_id":config["campaign_id"],"action_id":args.action_id,"head_hash":head,
                            "intent":intent,"stakes_hash":action["stakes_hash"],"stakes":action["stakes"]}
                atomic_json(Path(args.output),proposal)
                from .player import readable_stakes
                emit({"action_id":args.action_id,"stakes":readable_stakes(action["stakes"]),"offer_file":str(Path(args.output).resolve())})
            elif args.command == "accept":
                build_action = controller.rules_engine().build_action
                proposal = json.loads(Path(args.offer).read_text())
                require(proposal["campaign_id"]==config["campaign_id"],"Offer belongs to another campaign")
                require(digest(proposal["stakes"])==proposal["stakes_hash"],"Offer stakes do not match the preview hash")
                job_path = directory/"current-job.json"
                old = read_json(job_path) if job_path.exists() else {}
                job_id = "action:"+proposal["action_id"]
                if old.get("id")==job_id:
                    require(old["action"]["acceptance_ref"]==args.acceptance_ref,"Different acceptance for existing action")
                    require(canonical(proposal["intent"])==old["action"]["intent_text"].encode("utf-8") and
                            proposal["head_hash"]==old["action"]["expected_head_hash"] and
                            proposal["stakes_hash"]==old["action"]["stakes_hash"],
                            "Different offer for existing action")
                    return drive(directory)
                require(proposal["head_hash"]==controller.public_packet()["head_hash"],
                        "Offer is stale; request a new offer before accepting")
                action = build_action(controller.trusted_state(),proposal["head_hash"],config["campaign_id"],proposal["action_id"],proposal["intent"],args.acceptance_ref)
                require(action["stakes_hash"]==proposal["stakes_hash"],"Stakes changed; request a new offer")
                # Conservative text: only the selected validated mechanical result.
                narrations = {key:value["summary"] for key,value in action["stakes"]["bands"].items()}
                narrations["routine"] = narrations["clean"]
                create_job(directory,{"id":job_id,"kind":"action","action":action,"narrations":narrations})
                drive(directory)
    except RemotePending as exc:
        emit({"status":"PENDING","message":"Notion work is queued; no new outcome is released.","request_id":exc.operation_id})
    except ContractError as exc:
        emit({"status":"ERROR","code":"VALIDATION_FAILED","message":str(exc)})
        return 2
    except BackupError as exc:
        emit({"status":"ERROR","code":"BACKUP_FAILED","message":str(exc)})
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        emit({"status":"ERROR","code":"INVALID_INPUT","message":"The command input or runtime file is invalid; inspect the local setup."})
        return 2
    except RuntimeError as exc:
        if hasattr(exc,"code"):
            emit({"status":"ERROR","code":exc.code,"message":str(exc)})
            return 2
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
