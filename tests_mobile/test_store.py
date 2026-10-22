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
        db.execute("TRUNCATE mobile_actions, mobile_campaigns, mobile_sessions, mobile_players, mobile_rate_limits")
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
