"""Real PostgreSQL behind Flask's HTTP request boundary; no storage mock."""
import hashlib
import json
import os
import uuid

import pytest

from mobile_game.app import COOKIE, create_app
from mobile_game.store import Store, digest


@pytest.fixture
def app(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to the disposable mobile_pilot_test database")
    candidate = Store(url)
    with candidate.connect() as db:
        name = db.execute("SELECT current_database() AS name").fetchone()["name"]
    if name != "mobile_pilot_test":
        pytest.fail("Refusing test cleanup outside the mobile_pilot_test database")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost")
    application = create_app(url, testing=True)
    with candidate.connect() as db:
        db.execute("TRUNCATE mobile_actions, mobile_campaigns, mobile_sessions, mobile_players, mobile_rate_limits")
    return application


def start(client):
    response = client.post("/api/session", json={})
    assert response.status_code == 200
    credentials = response.get_json()
    assert credentials["recovery_code"]
    headers = {"X-CSRF-Token": credentials["csrf_token"]}
    response = client.post("/api/campaigns", json={"request_id": str(uuid.uuid4())}, headers=headers)
    assert response.status_code == 200
    return response.get_json(), headers, credentials


def action(packet, choice_id="accept_task"):
    choice = next(c for c in packet["state"]["choices"] if c["id"] == choice_id)
    return {"action_id": str(uuid.uuid4()), "expected_revision": packet["revision"],
            "choice_id": choice_id, "choice_hash": choice["choice_hash"]}


def test_anonymous_and_other_owner_cannot_read_write_or_export(app):
    owner = app.test_client()
    packet, owner_headers, _ = start(owner)
    path = "/api/campaigns/" + packet["id"]
    stranger = app.test_client()
    for suffix in ("", "/export"):
        denied = stranger.get(path + suffix)
        assert denied.status_code == 401
        assert denied.get_json()["error"] == "SESSION_REQUIRED"
    denied = stranger.post(path + "/actions", json=action(packet), headers=owner_headers)
    assert denied.status_code == 401
    _, stranger_headers, _ = start(stranger)
    for suffix in ("", "/export"):
        denied = stranger.get(path + suffix)
        assert denied.status_code == 404
        assert denied.get_json()["error"] == "CAMPAIGN_NOT_FOUND"
    denied = stranger.post(path + "/actions", json=action(packet), headers=stranger_headers)
    assert denied.status_code == 404
    assert owner.get(path).get_json() == packet


@pytest.mark.parametrize("extra_headers,expected_error", [
    ({}, "SESSION_CHANGED"),
    ({"X-CSRF-Token": "incorrect"}, "SESSION_CHANGED"),
    ({"Origin": "https://attacker.invalid"}, "ORIGIN_REJECTED"),
    ({"Sec-Fetch-Site": "cross-site"}, "ORIGIN_REJECTED"),
])
def test_csrf_and_cross_site_requests_do_not_mutate_campaign(app, extra_headers, expected_error):
    client = app.test_client()
    packet, headers, _ = start(client)
    if expected_error == "ORIGIN_REJECTED":
        extra_headers = {**headers, **extra_headers}
    path = "/api/campaigns/" + packet["id"]
    rejected = client.post(path + "/actions", json=action(packet), headers=extra_headers)
    assert rejected.status_code == 403
    assert rejected.get_json()["error"] == expected_error
    assert client.get(path).get_json() == packet


def test_json_and_exact_action_contract_are_required(app):
    client = app.test_client()
    packet, headers, _ = start(client)
    path = "/api/campaigns/" + packet["id"]
    rejected = client.post(path + "/actions", data=json.dumps(action(packet)), content_type="text/plain", headers=headers)
    assert rejected.status_code == 415
    for change in ("missing_hash", "extra_client_state", "boolean_revision"):
        request = action(packet)
        if change == "missing_hash":
            del request["choice_hash"]
        elif change == "extra_client_state":
            request["state"] = {"resources": {"silver": 999999}}
        else:
            request["expected_revision"] = False
        rejected = client.post(path + "/actions", json=request, headers=headers)
        assert rejected.status_code == 422
    assert client.get(path).get_json() == packet


def test_http_lost_reply_retry_and_new_browser_recovery(app):
    first_browser = app.test_client()
    packet, headers, credentials = start(first_browser)
    path = "/api/campaigns/" + packet["id"]
    request = action(packet)
    first = first_browser.post(path + "/actions", json=request, headers=headers)
    assert first.status_code == 200
    committed = first.get_json()
    # A fresh browser has no cookie, but the recovery credential reconnects it
    # to the same owner and the request identifier recovers the exact save.
    restarted_app = create_app(app.extensions["store"].url, testing=True)
    second_browser = restarted_app.test_client()
    assert second_browser.get(path).status_code == 401
    recovered = second_browser.post("/api/session/recover", json={"recovery_code": credentials["recovery_code"]})
    assert recovered.status_code == 200
    assert recovered.get_json()["recovery_code"] is None
    new_headers = {"X-CSRF-Token": recovered.get_json()["csrf_token"]}
    retried = second_browser.post(path + "/actions", json=request, headers=new_headers)
    assert retried.status_code == 200
    assert retried.get_json() == {**committed, "replayed": True}
    assert second_browser.get(path).get_json()["revision"] == 1
    assert second_browser.get("/api/campaigns").get_json()["campaigns"][0]["id"] == packet["id"]
    invalid = app.test_client().post("/api/session/recover", json={"recovery_code": "x" * 43})
    assert invalid.status_code == 401


@pytest.mark.parametrize("bad", [None, False, 0, [], {}, ""])
def test_invalid_recovery_never_creates_or_replaces_an_owner(app, bad):
    client = app.test_client()
    credentials = client.post("/api/session", json={}).get_json()
    old_cookie = client.get_cookie(COOKIE).value
    for browser in (client, app.test_client()):
        response = browser.post("/api/session/recover", json={"recovery_code": bad})
        assert response.status_code == 401
        assert response.get_json()["error"] == "INVALID_RECOVERY"
        assert "Set-Cookie" not in response.headers
    assert client.get_cookie(COOKIE).value == old_cookie
    assert client.get("/api/session").get_json()["player_id"] == credentials["player_id"]
    with app.extensions["store"].connect() as db:
        assert db.execute("SELECT count(*) AS n FROM mobile_players").fetchone()["n"] == 1
        assert db.execute("SELECT count(*) AS n FROM mobile_sessions").fetchone()["n"] == 1


def test_session_lookup_is_read_only_and_owner_identity_survives_recovery(app):
    client = app.test_client()
    assert client.get("/api/session").status_code == 401
    with app.extensions["store"].connect() as db:
        assert db.execute("SELECT count(*) AS n FROM mobile_players").fetchone()["n"] == 0
        assert db.execute("SELECT count(*) AS n FROM mobile_sessions").fetchone()["n"] == 0
    credentials = client.post("/api/session", json={}).get_json()
    owner = credentials["player_id"]
    assert str(uuid.UUID(owner)) == owner
    response = client.get("/api/session")
    assert response.status_code == 200 and "Set-Cookie" not in response.headers
    assert response.get_json() == {"player_id": owner, "csrf_token": credentials["csrf_token"], "recovery_code": None}
    assert client.post("/api/session", json={}).get_json()["player_id"] == owner
    other = app.test_client().post("/api/session", json={}).get_json()
    assert other["player_id"] != owner
    fresh = app.test_client()
    recovered = fresh.post("/api/session/recover", json={"recovery_code": credentials["recovery_code"]})
    assert recovered.get_json()["player_id"] == owner
    assert fresh.get("/api/session").get_json()["player_id"] == owner


def test_http_stale_and_changed_request_are_explicit_conflicts(app):
    client = app.test_client()
    packet, headers, _ = start(client)
    path = "/api/campaigns/" + packet["id"]
    request = action(packet)
    assert client.post(path + "/actions", json=request, headers=headers).status_code == 200
    stale = client.post(path + "/actions", json=action(packet, "move_inside"), headers=headers)
    assert stale.status_code == 409
    assert stale.get_json()["error"] == "STALE_REVISION"
    changed = action(packet, "move_inside")
    changed["action_id"] = request["action_id"]
    conflicting = client.post(path + "/actions", json=changed, headers=headers)
    assert conflicting.status_code == 409
    assert conflicting.get_json()["error"] == "ACTION_ID_CONFLICT"
    assert client.get(path).get_json()["revision"] == 1


def test_http_export_is_downloadable_complete_and_has_no_credentials(app):
    client = app.test_client()
    packet, headers, credentials = start(client)
    path = "/api/campaigns/" + packet["id"]
    saved = client.post(path + "/actions", json=action(packet, "move_inside"), headers=headers)
    assert saved.status_code == 200
    response = client.get(path + "/export")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert "r0001.json" in response.headers["Content-Disposition"]
    exported = response.get_json()
    assert exported["revision"] == 1 and len(exported["events"]) == 1
    assert exported["state"] == exported["events"][0]["post_state"]
    assert exported["state"]["identity"]["name"] == "Elin QA"
    assert exported["sha256"] == digest({k: v for k, v in exported.items() if k != "sha256"})
    for secret in (credentials["recovery_code"], credentials["csrf_token"], client.get_cookie(COOKIE).value):
        assert secret not in response.get_data(as_text=True)


def test_session_cookie_and_responses_have_private_browser_headers(app):
    client = app.test_client()
    response = client.post("/api/session", json={})
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    assert "token" not in response.get_json()
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    health = client.get("/health")
    assert health.status_code == 200 and health.get_json()["database"] == "postgresql"
    assert health.get_json()["live_import"] is False
    assert health.get_json()["release"] == "mobile-disposable-pilot-v2"


def test_production_uses_secure_cookie_and_hsts(app, monkeypatch):
    monkeypatch.delenv("WOT_LOCAL_DEV", raising=False)
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://mobile.example.test")
    production = create_app(app.extensions["store"].url, testing=False)
    response = production.test_client().post("/api/session", json={},
                                             base_url="https://mobile.example.test",
                                             headers={"Origin": "https://mobile.example.test"})
    assert response.status_code == 200
    assert "Secure" in response.headers["Set-Cookie"]
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_recovery_code_rotation_requires_session_csrf_and_same_origin(app):
    client = app.test_client()
    packet, headers, credentials = start(client)
    route = "/api/session/recovery-code"
    assert app.test_client().post(route, json={}).status_code == 401
    assert client.post(route, json={}).status_code == 403
    assert client.post(route, json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    cross_site = client.post(route, json={}, headers={**headers, "Origin": "https://attacker.invalid"})
    assert cross_site.status_code == 403
    assert cross_site.get_json()["error"] == "ORIGIN_REJECTED"
    # All rejected requests must leave the previous credential operational.
    still_valid = app.test_client().post("/api/session/recover", json={"recovery_code": credentials["recovery_code"]})
    assert still_valid.status_code == 200
    assert client.get("/api/campaigns/" + packet["id"]).get_json() == packet


def test_http_lost_code_replacement_retains_sessions_and_cloud_campaign(app):
    client = app.test_client()
    packet, headers, credentials = start(client)
    path = "/api/campaigns/" + packet["id"]
    saved = client.post(path + "/actions", json=action(packet, "move_inside"), headers=headers).get_json()
    original_cookie = client.get_cookie(COOKIE).value
    replacement_reply = client.post("/api/session/recovery-code", json={}, headers=headers)
    assert replacement_reply.status_code == 200
    replacement = replacement_reply.get_json()["recovery_code"]
    assert replacement != credentials["recovery_code"]
    assert client.get_cookie(COOKIE).value == original_cookie
    assert client.get(path).get_json()["head"] == saved["head"]
    stale_code = app.test_client().post("/api/session/recover", json={"recovery_code": credentials["recovery_code"]})
    assert stale_code.status_code == 401
    assert stale_code.get_json()["error"] == "INVALID_RECOVERY"
    restarted = create_app(app.extensions["store"].url, testing=True).test_client()
    recovered = restarted.post("/api/session/recover", json={"recovery_code": replacement})
    assert recovered.status_code == 200
    assert restarted.get(path).get_json() == {k: v for k, v in saved.items() if k != "replayed"}
    assert restarted.get("/api/campaigns").get_json()["campaigns"][0]["id"] == packet["id"]


def test_valid_bootstrap_reload_bypasses_exhausted_anonymous_ip_limit(app):
    client = app.test_client()
    packet, _, credentials = start(client)
    original_cookie = client.get_cookie(COOKIE).value
    bucket = "entry:" + hashlib.sha256(b"127.0.0.1").hexdigest()
    store = app.extensions["store"]
    with store.connect() as db:
        db.execute("UPDATE mobile_rate_limits SET count=120 WHERE bucket=%s", (bucket,))
    # Anonymous entry is exhausted for this address, but legitimate reloads
    # must neither consume that allowance nor strand an existing player.
    anonymous = app.test_client().post("/api/session", json={})
    assert anonymous.status_code == 429
    for _ in range(125):
        response = client.post("/api/session", json={})
        assert response.status_code == 200
        assert response.get_json() == {"csrf_token": credentials["csrf_token"], "recovery_code": None,
                                       "player_id": credentials["player_id"]}
    assert client.get_cookie(COOKIE).value == original_cookie
    assert client.get("/api/campaigns/" + packet["id"]).get_json() == packet
    with store.connect() as db:
        assert db.execute("SELECT count FROM mobile_rate_limits WHERE bucket=%s", (bucket,)).fetchone()["count"] == 121
        assert db.execute("SELECT count(*) AS n FROM mobile_sessions").fetchone()["n"] == 1
        assert db.execute("SELECT count(*) AS n FROM mobile_players").fetchone()["n"] == 1
