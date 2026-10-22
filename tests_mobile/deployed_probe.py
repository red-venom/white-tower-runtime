#!/usr/bin/env python3
"""Two-phase HTTPS acceptance probe using only generated disposable accounts.

Prepare, restart the Railway application, then verify with a fresh cookie jar:
  python tests_mobile/deployed_probe.py prepare --state-file ../.runtime/pilot-probe.json
  python tests_mobile/deployed_probe.py verify --state-file ../.runtime/pilot-probe.json

The state file contains credentials and is restricted to mode 600. Standard
output contains only check names and timing summaries, never credentials,
campaign content, database connection strings, or HTTP response bodies.
"""
import argparse
import copy
import hashlib
import http.cookiejar
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.parse
import urllib.request
import uuid


DEFAULT_BASE = "https://white-tower-mobile-production.up.railway.app"
SCHEMA = "white-tower-deployed-disposable-probe-v1"
COOKIE = "wt_mobile_session"


class CheckFailed(Exception):
    """Only fixed diagnostic labels are allowed in this exception."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, label):
    if not condition:
        raise CheckFailed(label)


def normalized_base(value):
    parsed = urllib.parse.urlsplit(value)
    require(parsed.scheme == "https" and bool(parsed.hostname), "base_url_requires_https")
    require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            "base_url_must_not_contain_credentials_or_query")
    require(parsed.path in ("", "/"), "base_url_must_be_an_origin")
    return value.rstrip("/")


def private_path(value):
    supplied = Path(value).expanduser().absolute()
    require(not supplied.is_symlink(), "state_file_must_not_be_a_symlink")
    path = supplied.resolve(strict=False)
    require(".runtime" in path.parts, "state_file_must_be_under_runtime")
    require(path.parent.is_dir(), "state_file_parent_must_exist")
    return path


def write_private(path, value):
    # Same-directory atomic replacement keeps each committed local probe record
    # complete, including after a terminated script. NamedTemporaryFile is 600.
    with tempfile.NamedTemporaryFile("wb", prefix=".pilot-probe-", dir=path.parent,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    require(path.stat().st_mode & 0o777 == 0o600, "state_file_permissions")


def read_private(path):
    require(path.exists(), "prepare_state_file_is_required")
    require(path.stat().st_mode & 0o777 == 0o600, "state_file_permissions")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict) and value.get("schema") == SCHEMA,
            "unsupported_probe_state")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward a recovery code or a CSRF header to a redirected host.
        raise urllib.error.HTTPError(req.full_url, code, "redirect rejected", headers, fp)


class Client:
    def __init__(self, probe, cookies=None, csrf=None):
        self.probe = probe
        self.cookies = http.cookiejar.CookieJar()
        for cookie in cookies or ():
            self.cookies.set_cookie(copy.copy(cookie))
        self.opener = urllib.request.build_opener(NoRedirect(),
                                                  urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = csrf

    def clone(self):
        return Client(self.probe, list(self.cookies), self.csrf)

    def request(self, method, path, body=None, label="request", expected=200):
        require(path.startswith("/") and not path.startswith("//"), "relative_api_path_required")
        headers = {"Accept": "application/json", "User-Agent": "WhiteTowerDisposableAcceptance/1"}
        data = None
        if body is not None:
            data = canonical(body)
            headers.update({"Content-Type": "application/json", "Origin": self.probe.base})
        if self.csrf and method != "GET":
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.probe.base + path, data=data,
                                         headers=headers, method=method)
        started = time.perf_counter()
        try:
            try:
                response = self.opener.open(request, timeout=30)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status, raw = response.code, response.read()
                response_headers = dict(response.headers.items())
        except Exception:
            self.probe.timing(label, time.perf_counter() - started, "network_error")
            raise
        self.probe.timing(label, time.perf_counter() - started, status)
        require(status in expected if isinstance(expected, tuple) else status == expected,
                label + "_http_status")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise CheckFailed(label + "_json_response_required") from None
        require(isinstance(value, dict), label + "_object_response_required")
        return value, response_headers, status

    def session(self, recovery_code=None):
        path = "/api/session" if recovery_code is None else "/api/session/recover"
        body = {} if recovery_code is None else {"recovery_code": recovery_code}
        value, headers, _ = self.request("POST", path, body, label="session")
        require(isinstance(value.get("csrf_token"), str), "session_csrf_present")
        self.csrf = value["csrf_token"]
        cookies = [c for c in self.cookies if c.name == COOKIE]
        require(len(cookies) == 1 and cookies[0].secure, "secure_session_cookie")
        require(any(k.lower() == "httponly" for k in cookies[0]._rest), "http_only_session_cookie")
        return value

    def private_session(self):
        return {"csrf_token": self.csrf,
                "cookies": [{"name": c.name, "value": c.value, "domain": c.domain,
                             "path": c.path, "secure": c.secure, "expires": c.expires}
                            for c in self.cookies]}


class Probe:
    def __init__(self, phase, base, path, state):
        self.phase, self.base, self.path, self.state = phase, base, path, state
        self.started = time.perf_counter()
        self.checks, self.timings = [], []
        self.lock = threading.Lock()

    def timing(self, label, seconds, status):
        with self.lock:
            self.timings.append({"operation": label, "seconds": round(seconds, 6), "status": status})

    def passed(self, label):
        self.checks.append(label)

    def save(self):
        write_private(self.path, self.state)

    def report(self, status, failure=None):
        def distribution(rows):
            values = sorted(r["seconds"] for r in rows)
            if not values:
                return {"count": 0}
            return {"count": len(values), "minimum": round(values[0], 3),
                    "median": round(statistics.median(values), 3),
                    "p95_nearest_rank": round(values[max(0, math.ceil(0.95 * len(values)) - 1)], 3),
                    "maximum": round(values[-1], 3)}
        report = {"phase": self.phase, "status": status, "checks_passed": self.checks,
                  "timing_seconds": {
                      "all_http_requests": distribution(self.timings),
                      "committed_game_actions": distribution([r for r in self.timings if r["operation"] == "action" and r["status"] == 200]),
                      "reads": distribution([r for r in self.timings if r["operation"] == "read" and r["status"] == 200]),
                      "elapsed": round(time.perf_counter() - self.started, 3)}}
        if failure:
            report["failure"] = failure
        self.state.setdefault("reports", []).append({**report, "requests": self.timings})
        self.save()
        print(json.dumps(report, sort_keys=True))


def action_request(packet, choice_id):
    require(packet.get("disposable") is True, "disposable_campaign_required")
    choices = [c for c in packet["state"]["choices"] if c["id"] == choice_id]
    require(len(choices) == 1, "expected_sample_choice_available")
    return {"action_id": str(uuid.uuid4()), "expected_revision": packet["revision"],
            "choice_id": choice_id, "choice_hash": choices[0]["choice_hash"]}


def campaign_path(packet):
    identifier = str(uuid.UUID(packet["id"]))
    require(identifier == packet["id"], "campaign_identifier_valid")
    return "/api/campaigns/" + identifier


def create_campaign(client):
    request = {"request_id": str(uuid.uuid4())}
    packet, _, _ = client.request("POST", "/api/campaigns", request, label="create")
    require(packet.get("disposable") is True and packet["state"].get("disposable") is True,
            "new_campaign_is_disposable")
    require(packet.get("capabilities", {}).get("import_live_campaign") is False,
            "live_import_disabled")
    return packet, request


def do_action(client, packet, choice):
    request = action_request(packet, choice)
    result, _, _ = client.request("POST", campaign_path(packet) + "/actions", request, label="action")
    require(result["revision"] == packet["revision"] + 1 and result.get("replayed") is False,
            "single_action_commit")
    return result, request


def validate_export(value, expected_packet):
    require(value.get("schema") == "white-tower-mobile-export-v1" and value.get("disposable") is True,
            "export_disposable_schema")
    require(value["campaign_id"] == expected_packet["id"] and value["revision"] == expected_packet["revision"]
            and value["head"] == expected_packet["head"], "export_checkpoint_matches_public_save")
    require(value["sha256"] == digest({k: v for k, v in value.items() if k != "sha256"}),
            "export_integrity_hash")
    events = value["events"]
    require(len(events) == value["revision"], "export_has_complete_event_journal")
    previous_state, previous_head = None, None
    for number, event in enumerate(events, 1):
        require(event["revision"] == number, "export_revisions_are_contiguous")
        require(event["request_sha256"] == digest(event["request"]), "export_request_integrity")
        require(event["head"] == digest({k: v for k, v in event.items() if k != "head"}),
                "export_event_integrity")
        require(event["post_state"]["clock"]["fictional_seconds"] - event["pre_state"]["clock"]["fictional_seconds"] == event["elapsed_seconds"],
                "export_elapsed_time_matches_state")
        if previous_state is None:
            previous_head = digest({"campaign_id": value["campaign_id"], "revision": 0, "state": event["pre_state"]})
        else:
            require(event["pre_state"] == previous_state, "export_full_state_continuity")
        require(event["predecessor_head"] == previous_head, "export_head_chain")
        previous_state, previous_head = event["post_state"], event["head"]
    if events:
        require(value["state"] == previous_state and value["head"] == previous_head,
                "export_full_checkpoint_matches_final_event")

    def keys(nested):
        if isinstance(nested, dict):
            for key, item in nested.items():
                yield key
                yield from keys(item)
        elif isinstance(nested, list):
            for item in nested:
                yield from keys(item)
    require(not ({"seed", "token", "token_hash", "csrf_token", "recovery_hash", "recovery_code"} & set(keys(value))),
            "export_excludes_authentication_and_future_dice_seed")


def prepare(probe):
    owner = Client(probe)
    health, _, _ = owner.request("GET", "/health", label="health")
    require(health.get("database") == "postgresql" and health.get("live_import") is False,
            "postgresql_disposable_service_ready")
    probe.passed("postgresql_disposable_service_ready")
    credentials = owner.session()
    require(isinstance(credentials.get("recovery_code"), str), "new_recovery_code_present")
    probe.state["owner"] = {"recovery_code": credentials["recovery_code"], **owner.private_session()}
    probe.save()
    packet, creation = create_campaign(owner)
    probe.state["main"] = {"creation_request": creation, "initial": packet}
    probe.save()
    # A repeated creation request must recover the same initially created game.
    duplicate_create, _, _ = owner.request("POST", "/api/campaigns", creation, label="creation_retry")
    require(duplicate_create == packet, "creation_retry_returns_same_campaign")
    probe.passed("creation_retry_returns_same_campaign")
    for choice in ("accept_task", "prepare_grip"):
        packet, _ = do_action(owner, packet, choice)
    packet, roll_request = do_action(owner, packet, "cross_courtyard")
    roll_response = copy.deepcopy(packet)
    require(packet["events"][-1].get("roll") is not None, "actual_uncertain_action_rolled")
    probe.state["main"].update(roll_request=roll_request, roll_response=roll_response)
    probe.save()
    replayed, _, _ = owner.request("POST", campaign_path(packet) + "/actions", roll_request, label="action_retry")
    require(replayed == {**roll_response, "replayed": True}, "exact_retry_preserves_original_result_and_dice")
    probe.passed("exact_retry_preserves_original_result_and_dice")
    if not packet["state"]["completed"]:
        packet, _ = do_action(owner, packet, "covered_route")
    require(packet["state"]["completed"] and packet["revision"] <= 4, "finite_episode_completes")
    completion = copy.deepcopy(packet)
    packet, _ = do_action(owner, packet, "quiet_interval")
    require(packet["state"]["completed"] and packet["state"]["result"] == completion["state"]["result"],
            "finished_episode_stays_finished")
    probe.passed("finite_episode_completes_and_stays_complete")
    current, _, _ = owner.request("GET", campaign_path(packet), label="read")
    require(current == {k: v for k, v in packet.items() if k != "replayed"}, "independent_checkpoint_readback")
    probe.state["main"]["checkpoint"] = current
    probe.save()
    exported, headers, _ = owner.request("GET", campaign_path(packet) + "/export", label="export")
    require(any(k.lower() == "content-disposition" and v.startswith("attachment;") for k, v in headers.items()),
            "export_download_attachment")
    validate_export(exported, current)
    for secret in (credentials["recovery_code"], credentials["csrf_token"], *(c.value for c in owner.cookies)):
        require(secret not in json.dumps(exported), "export_has_no_session_secrets")
    probe.state["main"]["export"] = exported
    probe.passed("complete_export_and_integrity_chain_verified")
    probe.save()

    other, other_creation = create_campaign(owner)
    requests = [action_request(other, "accept_task"), action_request(other, "move_inside")]
    barrier = threading.Barrier(2)
    clients = [owner.clone(), owner.clone()]

    def submit(index):
        barrier.wait(timeout=10)
        return clients[index].request("POST", campaign_path(other) + "/actions", requests[index],
                                      label="concurrent_action", expected=(200, 409))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, (0, 1)))
    require(sorted(outcome[2] for outcome in outcomes) == [200, 409], "one_concurrent_writer_commits")
    rejected = next(value for value, _, status in outcomes if status == 409)
    require(rejected.get("error") == "STALE_REVISION", "concurrent_rejection_is_stale_revision")
    concurrent_checkpoint, _, _ = owner.request("GET", campaign_path(other), label="read")
    require(concurrent_checkpoint["revision"] == 1 and len(concurrent_checkpoint["events"]) == 1,
            "concurrency_has_one_durable_event")
    probe.state["concurrent"] = {"creation_request": other_creation, "requests": requests,
                                  "checkpoint": concurrent_checkpoint}
    probe.passed("concurrent_different_actions_commit_exactly_once")
    probe.save()

    foreign = Client(probe)
    foreign_credentials = foreign.session()
    probe.state["foreign"] = {"recovery_code": foreign_credentials["recovery_code"], **foreign.private_session()}
    probe.save()
    for suffix in ("", "/export"):
        denied, _, _ = foreign.request("GET", campaign_path(current) + suffix,
                                       label="foreign_read", expected=404)
        require(denied.get("error") == "CAMPAIGN_NOT_FOUND", "foreign_owner_has_no_campaign_access")
    denied, _, _ = foreign.request("POST", campaign_path(current) + "/actions", roll_request,
                                   label="foreign_write", expected=404)
    require(denied.get("error") == "CAMPAIGN_NOT_FOUND", "foreign_owner_cannot_replay_or_write")
    probe.passed("foreign_owner_cannot_read_export_or_write")
    # Repeated independent reads provide a small latency sample without
    # advancing the campaign, changing resources, or accumulating filler turns.
    for _ in range(5):
        reread, _, _ = owner.request("GET", campaign_path(current), label="read")
        require(reread == current, "stable_checkpoint_during_read_timing_sample")
    probe.state["prepared"] = True
    probe.state["prepared_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    probe.passed("prepared_for_external_railway_restart")
    probe.save()


def verify(probe):
    require(probe.state.get("prepared") is True, "prepare_must_complete_before_verify")
    # Never restore saved cookies here: recovery must work as a fresh phone
    # browser after a separately performed application restart.
    fresh = Client(probe)
    require(len(fresh.cookies) == 0, "fresh_verification_cookie_jar")
    health, _, _ = fresh.request("GET", "/health", label="health")
    require(health.get("database") == "postgresql" and health.get("live_import") is False,
            "postgresql_disposable_service_ready")
    main = probe.state["main"]
    before_recovery, _, _ = fresh.request("GET", campaign_path(main["checkpoint"]),
                                          label="anonymous_read", expected=401)
    require(before_recovery.get("error") == "SESSION_REQUIRED", "fresh_browser_needs_recovery")
    recovered = fresh.session(probe.state["owner"]["recovery_code"])
    require(recovered.get("recovery_code") is None, "recovery_does_not_create_another_owner")
    probe.passed("fresh_cookie_jar_recovery_after_external_restart")
    listed, _, _ = fresh.request("GET", "/api/campaigns", label="list")
    expected_ids = {main["checkpoint"]["id"], probe.state["concurrent"]["checkpoint"]["id"]}
    require({c["id"] for c in listed["campaigns"]} == expected_ids, "same_owner_campaign_list_restored")
    current, _, _ = fresh.request("GET", campaign_path(main["checkpoint"]), label="read")
    require(current == main["checkpoint"], "exact_checkpoint_head_and_roll_history_survived")
    other, _, _ = fresh.request("GET", campaign_path(probe.state["concurrent"]["checkpoint"]), label="read")
    require(other == probe.state["concurrent"]["checkpoint"], "concurrent_commit_survived")
    probe.passed("exact_checkpoint_head_and_roll_history_survived")
    replayed, _, _ = fresh.request("POST", campaign_path(current) + "/actions", main["roll_request"],
                                   label="action_retry")
    require(replayed == {**main["roll_response"], "replayed": True}, "original_action_retries_after_restart_without_reroll")
    after_retry, _, _ = fresh.request("GET", campaign_path(current), label="read")
    require(after_retry == current, "historical_retry_does_not_rewind_or_advance_checkpoint")
    probe.passed("original_action_retries_after_restart_without_reroll")
    probe.passed("historical_retry_preserves_latest_checkpoint")
    exported, _, _ = fresh.request("GET", campaign_path(current) + "/export", label="export")
    validate_export(exported, current)
    ignored = {"exported_at", "sha256"}
    require({k: v for k, v in exported.items() if k not in ignored} ==
            {k: v for k, v in main["export"].items() if k not in ignored},
            "complete_export_state_and_events_survived")
    probe.passed("complete_export_state_and_events_survived")
    probe.state["verified_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    probe.state["verification_session"] = fresh.private_session()
    probe.state["verified"] = True
    probe.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "verify"))
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    probe = None
    try:
        base, path = normalized_base(args.base_url), private_path(args.state_file)
        if args.phase == "prepare":
            require(not path.exists(), "prepare_requires_new_private_state_file")
            state = {"schema": SCHEMA, "base_url": base, "prepared": False}
        else:
            state = read_private(path)
            require(state.get("base_url") == base, "verify_origin_must_match_prepare")
        probe = Probe(args.phase, base, path, state)
        probe.save()
        (prepare if args.phase == "prepare" else verify)(probe)
        probe.report("passed")
        return 0
    except Exception as exc:
        failure = str(exc) if isinstance(exc, CheckFailed) else type(exc).__name__
        # Never print a traceback or arbitrary urllib/HTTP exception text: it
        # could include a request, response, or credential-bearing URL.
        if probe is not None:
            try:
                probe.report("failed", failure)
                return 1
            except Exception:
                pass
        print(json.dumps({"phase": args.phase, "status": "failed", "failure": failure}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
