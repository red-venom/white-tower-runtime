"""Acceptance checks against an explicitly selected disposable PostgreSQL DB.

Run with TEST_DATABASE_URL set to the mobile_pilot_test database. These tests
intentionally use real commits, rollbacks, row locks, and new connections.
"""
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from mobile_game import rules
from mobile_game.store import Problem, Store, digest, secret_hash
from psycopg.types.json import Jsonb


@pytest.fixture
def store():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to the disposable mobile_pilot_test database")
    candidate = Store(url)
    with candidate.connect() as db:
        name = db.execute("SELECT current_database() AS name").fetchone()["name"]
    if name != "mobile_pilot_test":
        pytest.fail("Refusing test cleanup outside the mobile_pilot_test database")
    candidate.initialize()
    with candidate.connect() as db:
        db.execute("TRUNCATE mobile_oauth_tokens, mobile_oauth_codes, mobile_oauth_grants, mobile_oauth_clients, mobile_gm_requests, mobile_gm_budget, mobile_actions, mobile_campaigns, mobile_sessions, mobile_players, mobile_rate_limits")
    yield candidate


@pytest.fixture
def campaign(store):
    credentials = store.new_session()
    player = store.session(credentials["token"])["player_id"]
    packet = store.create(player, str(uuid.uuid4()))
    return player, packet, credentials


def action(packet, choice_id=None, action_id=None):
    choices = packet["state"]["choices"]
    choice = next(c for c in choices if c["id"] == choice_id) if choice_id else next(c for c in choices if not c["requires_roll"])
    return {"action_id": action_id or str(uuid.uuid4()),
            "expected_revision": packet["revision"],
            "choice_id": choice["id"], "choice_hash": choice["choice_hash"]}


def counts(store):
    with store.connect() as db:
        return db.execute("SELECT (SELECT count(*) FROM mobile_actions) AS actions, (SELECT count(*) FROM mobile_campaigns) AS campaigns").fetchone()


def assert_chain(export):
    previous_state = None
    previous_head = None
    for sequence, event in enumerate(export["events"], 1):
        assert event["revision"] == sequence
        assert event["request_sha256"] == digest(event["request"])
        assert event["head"] == digest({k: v for k, v in event.items() if k != "head"})
        assert event["post_state"]["clock"]["fictional_seconds"] - event["pre_state"]["clock"]["fictional_seconds"] == event["elapsed_seconds"]
        if previous_state is not None:
            assert event["pre_state"] == previous_state
            assert event["predecessor_head"] == previous_head
        else:
            assert event["predecessor_head"] == digest({"campaign_id": export["campaign_id"], "revision": 0, "state": event["pre_state"]})
        previous_state, previous_head = event["post_state"], event["head"]
    assert export["revision"] == len(export["events"])
    if export["events"]:
        assert export["state"] == previous_state
        assert export["head"] == previous_head
    assert export["sha256"] == digest({k: v for k, v in export.items() if k != "sha256"})


def test_session_credentials_are_hashed_and_invalid_recovery_creates_nothing(store):
    assert store.health()
    credentials = store.new_session()
    identity = store.session(credentials["token"])
    assert identity and identity["csrf_token"] == credentials["csrf_token"]
    with store.connect() as db:
        saved_session = db.execute("SELECT * FROM mobile_sessions").fetchone()
        saved_player = db.execute("SELECT * FROM mobile_players").fetchone()
    assert saved_session["token_hash"] == secret_hash(credentials["token"])
    assert saved_player["recovery_hash"] == secret_hash(credentials["recovery_code"])
    assert saved_session["token_hash"] != credentials["token"]
    assert saved_player["recovery_hash"] != credentials["recovery_code"]
    for bad in ("incorrect", "x" * 43, None, "x" * 129):
        if bad is None:
            assert store.session(bad) is None
        with pytest.raises(Problem) as error:
            store.new_session(bad)
        assert error.value.status == 401
    with store.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM mobile_players").fetchone()["n"] == 1
        assert db.execute("SELECT count(*) AS n FROM mobile_sessions").fetchone()["n"] == 1


def test_creation_retry_after_lost_response_is_one_campaign(store):
    credentials = store.new_session()
    owner = store.session(credentials["token"])["player_id"]
    request_id = str(uuid.uuid4())
    committed = store.create(owner, request_id)
    retried = Store(store.url).create(owner, request_id)
    assert retried == committed
    assert counts(store) == {"actions": 0, "campaigns": 1}


@pytest.mark.parametrize("point", ["after_event_insert", "before_commit"])
def test_action_fault_rolls_back_journal_and_checkpoint_together(store, campaign, point):
    owner, before, _ = campaign
    request = action(before, "accept_task")

    def interrupt(actual_point):
        if actual_point == point:
            raise RuntimeError("simulated process interruption before commit")

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        store.act(owner, before["id"], request, fault=interrupt)
    assert Store(store.url).read(owner, before["id"]) == before
    assert counts(store) == {"actions": 0, "campaigns": 1}
    saved = Store(store.url).act(owner, before["id"], request)
    assert saved["revision"] == 1 and saved["replayed"] is False
    assert len(saved["events"]) == 1
    assert_chain(store.export(owner, before["id"]))


def test_lost_response_retry_preserves_original_dice_and_full_result(store, campaign):
    owner, packet, _ = campaign
    packet = store.act(owner, packet["id"], action(packet, "accept_task"))
    request = action(packet, "cross_courtyard")
    committed = store.act(owner, packet["id"], request)
    assert committed["events"][-1]["roll"] is not None
    # Simulate the browser never receiving the first reply, and reconnecting
    # through another server process with exactly the same pending request.
    retried = Store(store.url).act(owner, packet["id"], deepcopy(request))
    assert retried == {**committed, "replayed": True}
    assert retried["events"][-1]["roll"]["dice"] == committed["events"][-1]["roll"]["dice"]
    assert counts(store)["actions"] == 2
    assert store.read(owner, packet["id"])["revision"] == 2
    assert_chain(store.export(owner, packet["id"]))


def test_same_action_id_changed_request_is_conflict_not_second_action(store, campaign):
    owner, packet, _ = campaign
    request = action(packet, "accept_task")
    saved = store.act(owner, packet["id"], request)
    changed = action(packet, "move_inside", action_id=request["action_id"])
    with pytest.raises(Problem) as error:
        store.act(owner, packet["id"], changed)
    assert (error.value.status, error.value.code) == (409, "ACTION_ID_CONFLICT")
    assert store.read(owner, packet["id"])["head"] == saved["head"]
    assert counts(store)["actions"] == 1


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_requests_commit_once_at_one_revision(store, campaign, duplicate):
    owner, packet, _ = campaign
    first = action(packet, "accept_task")
    second = deepcopy(first) if duplicate else action(packet, "move_inside")
    barrier = threading.Barrier(2)

    def submit(request):
        barrier.wait(timeout=5)
        try:
            return Store(store.url).act(owner, packet["id"], request)
        except Problem as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (first, second)))
    successful = [r for r in results if isinstance(r, dict)]
    failures = [r for r in results if isinstance(r, Problem)]
    if duplicate:
        assert len(successful) == 2 and not failures
        assert sorted(r["replayed"] for r in successful) == [False, True]
        assert successful[0]["head"] == successful[1]["head"]
    else:
        assert len(successful) == 1 and len(failures) == 1
        assert (failures[0].status, failures[0].code) == (409, "STALE_REVISION")
    assert counts(store)["actions"] == 1
    assert store.read(owner, packet["id"])["revision"] == 1
    assert_chain(store.export(owner, packet["id"]))


def test_new_store_and_recovered_session_resume_exact_committed_game(store, campaign):
    owner, packet, credentials = campaign
    saved = store.act(owner, packet["id"], action(packet, "move_inside"))
    with store.connect() as db:
        db.execute("UPDATE mobile_sessions SET expires_at=now()-interval '1 second'")
    fresh = Store(store.url)
    assert fresh.session(credentials["token"]) is None
    recovered = fresh.new_session(credentials["recovery_code"])
    assert recovered["token"] != credentials["token"]
    assert recovered["recovery_code"] is None
    assert fresh.session(recovered["token"])["player_id"] == owner
    assert fresh.read(owner, packet["id"]) == {k: v for k, v in saved.items() if k != "replayed"}
    assert fresh.campaigns(owner)[0]["id"] == packet["id"]


def test_unknown_state_is_preserved_but_not_exposed_by_public_projection(store, campaign):
    owner, packet, _ = campaign
    state = rules.initial_state()
    state["future_extension"] = {"unicode": "Cairhien — é", "values": [None, False, 0, {"nested": [1, 2, 3]}]}
    state["world"]["private_continuity"] = {"fixture_secret": "not-for-public-projection", "later": []}
    initial_head = digest({"campaign_id": packet["id"], "revision": 0, "state": state})
    with store.connect() as db:
        db.execute("UPDATE mobile_campaigns SET state=%s,head=%s WHERE id=%s", (Jsonb(state), initial_head, packet["id"]))
    packet = store.read(owner, packet["id"])
    saved = store.act(owner, packet["id"], action(packet, "move_inside"))
    assert "future_extension" not in saved["state"]
    assert "not-for-public-projection" not in json.dumps(saved)
    export = store.export(owner, packet["id"])
    assert export["state"]["future_extension"] == state["future_extension"]
    assert export["state"]["world"]["private_continuity"] == state["world"]["private_continuity"]
    assert export["events"][0]["pre_state"] == state
    assert export["events"][0]["post_state"] == export["state"]
    assert_chain(export)


def test_export_is_complete_and_has_no_authentication_or_server_dice_seed(store, campaign):
    owner, packet, credentials = campaign
    packet = store.act(owner, packet["id"], action(packet, "accept_task"))
    packet = store.act(owner, packet["id"], action(packet, "cross_courtyard"))
    export = store.export(owner, packet["id"])
    with store.connect() as db:
        row = db.execute("SELECT state,seed FROM mobile_campaigns WHERE id=%s", (packet["id"],)).fetchone()
    assert export["state"] == row["state"]
    assert len(export["events"]) == 2
    encoded = json.dumps(export)
    for secret in (credentials["token"], credentials["csrf_token"], credentials["recovery_code"], bytes(row["seed"]).hex()):
        assert secret not in encoded

    def keys(value):
        if isinstance(value, dict):
            for key, nested in value.items():
                yield key
                yield from keys(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from keys(nested)
    assert not ({"seed", "token", "token_hash", "recovery_code", "recovery_hash", "csrf_token"} & set(keys(export)))
    assert_chain(export)


def test_finite_episode_completes_and_stays_complete_after_restart(store, campaign):
    owner, packet, _ = campaign
    original = store.export(owner, packet["id"])["state"]
    for choice in ("accept_task", "prepare_grip", "cross_courtyard"):
        packet = store.act(owner, packet["id"], action(packet, choice))
    if not packet["state"]["completed"]:
        packet = store.act(owner, packet["id"], action(packet, "covered_route"))
    assert packet["state"]["completed"] and packet["state"]["status"] == "complete"
    assert packet["revision"] <= 4
    packet = Store(store.url).read(owner, packet["id"])
    packet = Store(store.url).act(owner, packet["id"], action(packet, "quiet_interval"))
    assert packet["state"]["completed"]
    exported = Store(store.url).export(owner, packet["id"])
    assert exported["state"]["world"]["episode"]["check_count"] == 1
    assert exported["state"]["progression"] == original["progression"]
    assert exported["state"]["resources"] == original["resources"]
    assert_chain(exported)


def test_changed_displayed_stakes_cannot_be_silently_accepted(store, campaign):
    owner, packet, _ = campaign
    request = action(packet, "accept_task")
    request["choice_hash"] = "0" * 64
    with pytest.raises(Problem) as error:
        store.act(owner, packet["id"], request)
    assert (error.value.status, error.value.code) == (409, "STAKES_CHANGED")
    assert store.read(owner, packet["id"]) == packet
    assert counts(store)["actions"] == 0


def test_lost_recovery_code_can_be_replaced_without_changing_identity_or_save(store, campaign):
    owner, packet, credentials = campaign
    saved = store.act(owner, packet["id"], action(packet, "move_inside"))
    other_session = store.new_session(credentials["recovery_code"])
    before_identity = store.session(credentials["token"])
    # The owner still has a valid browser session even if the old recovery
    # code or the first rotation response has been lost.
    lost_replacement = store.rotate_recovery(owner)
    replacement = Store(store.url).rotate_recovery(owner)
    assert replacement not in (credentials["recovery_code"], lost_replacement)
    for old_code in (credentials["recovery_code"], lost_replacement):
        with pytest.raises(Problem) as error:
            store.new_session(old_code)
        assert (error.value.status, error.value.code) == (401, "INVALID_RECOVERY")
    assert store.session(credentials["token"]) == before_identity
    assert store.session(other_session["token"])["player_id"] == owner
    recovered = Store(store.url).new_session(replacement)
    assert store.session(recovered["token"])["player_id"] == owner
    assert store.read(owner, packet["id"]) == {k: v for k, v in saved.items() if k != "replayed"}
    with store.connect() as db:
        row = db.execute("SELECT recovery_hash FROM mobile_players WHERE id=%s", (owner,)).fetchone()
        assert row["recovery_hash"] == secret_hash(replacement)
        assert db.execute("SELECT count(*) AS n FROM mobile_players").fetchone()["n"] == 1
    assert counts(store) == {"actions": 1, "campaigns": 1}


GM_POLICY = {"max_requests": 20, "budget_micro_usd": 1_000_000, "reservation_micro_usd": 23_700}


def gm_request(packet, prompt="May I use the covered space?"):
    return {"request_id": str(uuid.uuid4()), "expected_revision": packet["revision"], "prompt": prompt}


def gm_result(kind="proposal", choice_id="move_inside"):
    return {"kind": kind, "choice_id": choice_id if kind == "proposal" else None,
            "message": "The covered space is an available option.",
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}}


def gm_counts(store):
    with store.connect() as db:
        return db.execute("""SELECT (SELECT count(*) FROM mobile_gm_requests) AS requests,
            COALESCE((SELECT reserved_requests FROM mobile_gm_budget),0) AS reserved,
            COALESCE((SELECT reserved_micro_usd FROM mobile_gm_budget),0) AS micro_usd""").fetchone()


@pytest.mark.parametrize("kind", ["proposal", "answer", "clarify"])
def test_gm_public_context_only_readonly_result_and_exact_restart_retry(store, campaign, kind):
    owner, packet, _ = campaign
    enabled = Store(store.url, gm_policy=GM_POLICY)
    with store.connect() as db:
        row = db.execute("SELECT state FROM mobile_campaigns WHERE id=%s", (packet["id"],)).fetchone()
        state = row["state"]
        state["world"]["private_continuity"] = {"secret": "private-fixture-never-model"}
        db.execute("UPDATE mobile_campaigns SET state=%s WHERE id=%s", (Jsonb(state), packet["id"]))
    before = store.read(owner, packet["id"])
    request, calls = gm_request(packet), []

    def interpreter(public, prompt):
        calls.append((deepcopy(public), prompt))
        assert "private-fixture-never-model" not in json.dumps(public)
        assert public == rules.view(state)
        public["resources"]["silver"] = 99999  # Even a bad adapter cannot mutate a save.
        return gm_result(kind)

    saved = enabled.gm_request(owner, packet["id"], request, interpreter)
    assert saved["status"] == "completed" and saved["expected_revision"] == 0
    assert saved["result"]["choice_hash"] == (next(c["choice_hash"] for c in before["state"]["choices"] if c["id"] == "move_inside") if kind == "proposal" else None)
    assert "usage" not in saved["result"]
    assert store.read(owner, packet["id"]) == before
    assert counts(store)["actions"] == 0
    # Disabled mode still retrieves prior results; a retry never calls again.
    assert Store(store.url).gm_request(owner, packet["id"], request, lambda *_: pytest.fail("second model call")) == saved
    assert Store(store.url).gm_status(owner, packet["id"], request["request_id"]) == saved
    assert len(calls) == 1
    assert gm_counts(store) == {"requests": 1, "reserved": 1, "micro_usd": 23_700}


def test_gm_disabled_foreign_stale_and_non_disposable_reject_before_reservation(store, campaign):
    owner, packet, _ = campaign
    request = gm_request(packet)
    forbidden = lambda *_: pytest.fail("provider must not run")
    with pytest.raises(Problem, match="not enabled") as error:
        store.gm_request(owner, packet["id"], request, forbidden)
    assert error.value.status == 503
    enabled = Store(store.url, gm_policy=GM_POLICY)
    stranger = store.new_session()["player_id"]
    for call in (lambda: enabled.gm_request(stranger, packet["id"], request, forbidden),
                 lambda: enabled.gm_status(stranger, packet["id"], request["request_id"])):
        with pytest.raises(Problem) as error:
            call()
        assert error.value.status == 404
    advanced = store.act(owner, packet["id"], action(packet))
    with pytest.raises(Problem) as error:
        enabled.gm_request(owner, packet["id"], request, forbidden)
    assert error.value.code == "STALE_REVISION"
    with store.connect() as db:
        state = db.execute("SELECT state FROM mobile_campaigns WHERE id=%s", (packet["id"],)).fetchone()["state"]
        state["disposable"] = False
        db.execute("UPDATE mobile_campaigns SET state=%s WHERE id=%s", (Jsonb(state), packet["id"]))
    with pytest.raises(Problem) as error:
        enabled.gm_request(owner, packet["id"], gm_request(advanced), forbidden)
    assert error.value.code == "GM_DISPOSABLE_ONLY"
    assert gm_counts(store) == {"requests": 0, "reserved": 0, "micro_usd": 0}


@pytest.mark.parametrize("change", [{"prompt": "different"}, {"expected_revision": 1}])
def test_gm_changed_input_conflicts_even_after_completed_request(store, campaign, change):
    owner, packet, _ = campaign
    enabled = Store(store.url, gm_policy=GM_POLICY)
    request = gm_request(packet)
    saved = enabled.gm_request(owner, packet["id"], request, lambda *_: gm_result())
    with pytest.raises(Problem) as error:
        enabled.gm_request(owner, packet["id"], {**request, **change}, lambda *_: pytest.fail("reused ID called provider"))
    assert error.value.code == "GM_REQUEST_ID_CONFLICT"
    assert enabled.gm_status(owner, packet["id"], request["request_id"]) == saved


@pytest.mark.parametrize("point,call_count", [("after_reservation", 0), ("after_provider", 1)])
def test_gm_crash_reservation_expires_without_second_call_or_budget_reset(store, campaign, point, call_count):
    owner, packet, _ = campaign
    policy = {**GM_POLICY, "max_requests": 1}
    enabled = Store(store.url, gm_policy=policy)
    request, calls = gm_request(packet), []
    class Crash(BaseException):
        pass
    def fault(phase):
        if phase == point:
            raise Crash()
    def interpreter(*_):
        calls.append(True)
        return gm_result()
    with pytest.raises(Crash):
        enabled.gm_request(owner, packet["id"], request, interpreter, fault=fault)
    restarted = Store(store.url, gm_policy=policy)
    assert restarted.gm_request(owner, packet["id"], request, interpreter)["status"] == "prepared"
    assert len(calls) == call_count
    with store.connect() as db:
        db.execute("UPDATE mobile_gm_requests SET expires_at=now()-interval '1 second'")
    saved = restarted.gm_status(owner, packet["id"], request["request_id"])
    assert saved["status"] == "unknown" and saved["result"] is None
    assert restarted.gm_request(owner, packet["id"], request, interpreter) == saved
    assert len(calls) == call_count
    with pytest.raises(Problem) as error:
        restarted.gm_request(owner, packet["id"], gm_request(packet), interpreter)
    assert error.value.code == "GM_BUDGET_EXHAUSTED"
    assert gm_counts(store) == {"requests": 1, "reserved": 1, "micro_usd": 23_700}
    assert store.read(owner, packet["id"]) == packet


@pytest.mark.parametrize("failure", ["billing", "configuration", "raw", "invalid_proposal", "nul_output", "invalid_unicode"])
def test_gm_failures_are_safe_terminal_and_keep_reservation(store, campaign, failure):
    from mobile_game.gm import GMError
    owner, packet, _ = campaign
    enabled = Store(store.url, gm_policy=GM_POLICY)
    request, calls = gm_request(packet), []
    def interpreter(*_):
        calls.append(True)
        if failure == "invalid_proposal":
            return gm_result(choice_id="invent_money")
        if failure in ("nul_output", "invalid_unicode"):
            return {**gm_result("answer"), "message": "\x00" if failure == "nul_output" else "\ud800"}
        if failure == "raw":
            raise RuntimeError("secret-provider-body-do-not-expose")
        error = GMError("GM_BILLING_UNAVAILABLE" if failure == "billing" else "GM_NOT_CONFIGURED",
                        attempted=failure == "billing", usage={"input_tokens": 17})
        error.message = "secret-provider-body-do-not-expose"
        raise error
    result = enabled.gm_request(owner, packet["id"], request, interpreter)
    assert result["status"] == ("failed" if failure == "configuration" else "unknown")
    assert result["result"] is None and "secret-provider-body" not in json.dumps(result)
    if failure == "billing":
        assert result["error"]["code"] == "GM_BILLING_UNAVAILABLE"
        with store.connect() as db:
            assert db.execute("SELECT usage FROM mobile_gm_requests").fetchone()["usage"]["input_tokens"] == 17
    assert enabled.gm_request(owner, packet["id"], request, interpreter) == result
    assert calls == [True] and gm_counts(store)["reserved"] == 1
    assert store.read(owner, packet["id"]) == packet


def test_gm_inflight_duplicate_does_not_block_gameplay_or_recall_provider(store, campaign):
    owner, packet, _ = campaign
    enabled = Store(store.url, gm_policy=GM_POLICY)
    request, calls = gm_request(packet), []
    started, release = threading.Event(), threading.Event()
    def interpreter(*_):
        calls.append(True); started.set()
        assert release.wait(5)
        return gm_result()
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(enabled.gm_request, owner, packet["id"], request, interpreter)
        assert started.wait(3)
        try:
            duplicate = pool.submit(enabled.gm_request, owner, packet["id"], request, interpreter).result(timeout=2)
            assert duplicate["status"] == "prepared"
            with pytest.raises(Problem) as error:
                enabled.gm_request(owner, packet["id"], {**request, "prompt": "Changed while pending"}, interpreter)
            assert error.value.code == "GM_REQUEST_ID_CONFLICT"
            # This needs the campaign row lock. It must commit while the model waits.
            advanced = pool.submit(store.act, owner, packet["id"], action(packet)).result(timeout=2)
            assert advanced["revision"] == 1
        finally:
            release.set()
        saved = first.result(timeout=3)
    assert saved["status"] == "completed" and saved["expected_revision"] == 0
    assert calls == [True] and counts(store)["actions"] == 1
    assert enabled.gm_request(owner, packet["id"], request, interpreter) == saved
    assert store.read(owner, packet["id"])["revision"] == 1


@pytest.mark.parametrize("limiting", ["requests", "credits"])
def test_gm_global_lifetime_cap_across_owners_and_concurrent_workers(store, campaign, limiting):
    owner, packet, _ = campaign
    other = store.new_session()["player_id"]
    other_packet = store.create(other, str(uuid.uuid4()))
    policy = {**GM_POLICY, **({"max_requests": 1} if limiting == "requests" else {"budget_micro_usd": 23_700})}
    barrier, calls = threading.Barrier(2), []
    def submit(player, current):
        barrier.wait()
        try:
            return Store(store.url, gm_policy=policy).gm_request(player, current["id"], gm_request(current),
                                                               lambda *_: (calls.append(True), gm_result())[1])
        except Problem as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, owner, packet), pool.submit(submit, other, other_packet)]
        results = [future.result(timeout=5) for future in futures]
    assert sum(isinstance(result, dict) and result["status"] == "completed" for result in results) == 1
    assert results.count("GM_BUDGET_EXHAUSTED") == 1 and calls == [True]
    assert gm_counts(store) == {"requests": 1, "reserved": 1, "micro_usd": 23_700}


@pytest.mark.parametrize("change", [{"prompt": "x" * 2001}, {"prompt": "\ud800"}, {"prompt": "x" + "\x01" * 1999},
                                    {"prompt": " "}, {"prompt": "\x00"}, {"expected_revision": True}, {"unexpected": 1}])
def test_gm_invalid_input_never_reserves_or_calls(store, campaign, change):
    owner, packet, _ = campaign
    enabled = Store(store.url, gm_policy=GM_POLICY)
    with pytest.raises(Problem) as error:
        enabled.gm_request(owner, packet["id"], {**gm_request(packet), **change}, lambda *_: pytest.fail("invalid input called provider"))
    assert error.value.status == 422
    assert gm_counts(store) == {"requests": 0, "reserved": 0, "micro_usd": 0}


def test_gm_exact_prompt_limit_and_late_completion_cannot_reopen_expired_request(store, campaign):
    from mobile_game.gm import MAX_PROMPT_CHARS
    assert MAX_PROMPT_CHARS == 2000
    owner, packet, _ = campaign
    enabled = Store(store.url, gm_policy=GM_POLICY)
    request, calls = gm_request(packet, "x" * MAX_PROMPT_CHARS), []
    def interpreter(*_):
        calls.append(True)
        with store.connect() as db:
            db.execute("UPDATE mobile_gm_requests SET expires_at=now()-interval '1 second'")
        assert enabled.gm_status(owner, packet["id"], request["request_id"])["status"] == "unknown"
        return gm_result()
    result = enabled.gm_request(owner, packet["id"], request, interpreter)
    assert result["status"] == "unknown" and result["result"] is None
    assert enabled.gm_request(owner, packet["id"], request, interpreter) == result
    assert calls == [True]
    with store.connect() as db:
        assert db.execute("SELECT result FROM mobile_gm_requests").fetchone()["result"] is None
