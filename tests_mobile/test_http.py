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
    monkeypatch.delenv("WOT_GM_ENABLED", raising=False)
    application = create_app(url, testing=True)
    with candidate.connect() as db:
        db.execute("TRUNCATE mobile_gm_requests, mobile_gm_budget, mobile_actions, mobile_campaigns, mobile_sessions, mobile_players, mobile_rate_limits")
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


def test_authored_adventure_complete_flow_recovery_and_readonly_intents(app):
    client=app.test_client()
    _, headers, credentials=start(client)
    request={"request_id":str(uuid.uuid4()),"episode_id":"gallery-letter-v1"}
    created=client.post("/api/campaigns",json=request,headers=headers)
    assert created.status_code==200
    packet=created.get_json(); base=f'/api/campaigns/{packet["id"]}'
    assert packet["capabilities"]["typed_intents"] and not packet["capabilities"]["gm_assistant"]
    for prompt in ("Look around", "Use Air Hand", "Study until the lesson ends"):
        before=client.get(base).get_json()
        reply=client.post(base+"/intent",json={"prompt":prompt,"expected_revision":before["revision"]},headers=headers).get_json()
        assert client.get(base).get_json()==before
        assert reply["kind"]=="proposal"
        choice=reply["choice"]
        action={"action_id":str(uuid.uuid4()),"expected_revision":before["revision"],"choice_id":choice["id"],"choice_hash":choice["choice_hash"]}
        response=client.post(base+"/actions",json=action,headers=headers)
        assert response.status_code==200
        assert client.post(base+"/actions",json=action,headers=headers).get_json()["replayed"] is True
    saved=client.get(base).get_json()
    assert saved["revision"]==3 and saved["state"]["completed"]
    assert saved["state"]["resources"]["strain"]==1
    assert saved["companion"]["study"]["gallery_review"]["minutes"]==20
    recovered=app.test_client()
    assert recovered.post("/api/session/recover",json={"recovery_code":credentials["recovery_code"]}).status_code==200
    assert recovered.get(base).get_json()==saved
    journal=recovered.get(base+"/journal?q=Maerin").get_json()
    assert len(journal["entries"])==3 and "pre_state" not in str(journal)
    assert client.post(base+"/intent",json={"prompt":"look around","expected_revision":0},headers=headers).status_code==409
    anonymous=app.test_client()
    assert anonymous.get(base+"/journal").status_code==401
    assert client.post(base+"/intent",json={"prompt":"look around","expected_revision":3}).status_code==403
    conflict={**request,"episode_id":"courtyard-cover-disposable-v1"}
    assert client.post("/api/campaigns",json=conflict,headers=headers).status_code==409


def test_journal_pagination_and_literal_search(app):
    client=app.test_client();packet,headers,_=start(client);base=f'/api/campaigns/{packet["id"]}'
    def act(id):
        nonlocal packet
        c=next(c for c in packet["state"]["choices"] if c["id"]==id)
        packet=client.post(base+"/actions",headers=headers,json={"action_id":str(uuid.uuid4()),"expected_revision":packet["revision"],"choice_id":id,"choice_hash":c["choice_hash"]}).get_json()
    act("decline_task")
    for _ in range(32):act("quiet_interval")
    first=client.get(base+"/journal?q=quiet").get_json()
    assert len(first["entries"])==30
    second=client.get(base+f'/journal?q=quiet&before={first["next_before"]}').get_json()
    assert len(second["entries"])==2 and second["next_before"] is None
    assert not set(e["revision"] for e in first["entries"]) & set(e["revision"] for e in second["entries"])
    assert client.get(base+"/journal?q=%25").get_json()["entries"]==[]
    assert client.get(base+"/journal?before=bad").status_code==422


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


def enable_test_gm(app, interpreter):
    app.extensions["store"].gm_policy = {"max_requests": 20, "budget_micro_usd": 1_000_000, "reservation_micro_usd": 23_700}
    app.extensions["gm_interpreter"] = interpreter


def gm_http_request(packet):
    return {"request_id": str(uuid.uuid4()), "expected_revision": packet["revision"], "prompt": "Could I move the readers inside?"}


def gm_http_result():
    return {"kind": "proposal", "choice_id": "move_inside", "message": "Moving inside is available.",
            "usage": {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}}


def test_http_gm_disabled_does_not_reserve_or_call(app):
    client = app.test_client()
    packet, headers, _ = start(client)
    app.extensions["gm_interpreter"] = lambda *_: pytest.fail("disabled provider call")
    response = client.post("/api/campaigns/" + packet["id"] + "/gm-requests", json=gm_http_request(packet), headers=headers)
    assert response.status_code == 503 and response.get_json()["error"] == "GM_DISABLED"
    assert packet["capabilities"]["gm_assistant"] is False
    with app.extensions["store"].connect() as db:
        assert db.execute("SELECT count(*) AS n FROM mobile_gm_requests").fetchone()["n"] == 0
        assert db.execute("SELECT count(*) AS n FROM mobile_gm_budget").fetchone()["n"] == 0


def test_http_gm_requires_owner_and_csrf_before_provider_or_reservation(app):
    enable_test_gm(app, lambda *_: pytest.fail("unauthorized provider call"))
    client = app.test_client()
    packet, headers, _ = start(client)
    route = "/api/campaigns/" + packet["id"] + "/gm-requests"
    value = gm_http_request(packet)
    assert app.test_client().post(route, json=value).status_code == 401
    assert client.post(route, json=value).status_code == 403
    assert client.post(route, json=value, headers={**headers, "Origin": "https://foreign.invalid"}).status_code == 403
    stranger = app.test_client()
    _, stranger_headers, _ = start(stranger)
    assert stranger.post(route, json=value, headers=stranger_headers).status_code == 404
    assert stranger.get(route + "/" + value["request_id"]).status_code == 404
    with app.extensions["store"].connect() as db:
        assert db.execute("SELECT count(*) AS n FROM mobile_gm_requests").fetchone()["n"] == 0


def test_http_gm_proposal_is_readonly_exactly_retrievable_and_normal_action_remains_required(app):
    calls = []
    enable_test_gm(app, lambda *_: (calls.append(True), gm_http_result())[1])
    client = app.test_client()
    packet, headers, _ = start(client)
    route = "/api/campaigns/" + packet["id"]
    value = gm_http_request(packet)
    response = client.post(route + "/gm-requests", json=value, headers=headers)
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == "completed" and result["expected_revision"] == 0
    offered = next(c for c in packet["state"]["choices"] if c["id"] == "move_inside")
    assert result["result"]["choice_hash"] == offered["choice_hash"]
    assert client.get(route).get_json() == packet
    assert client.get(route + "/gm-requests/" + value["request_id"]).get_json() == result
    assert client.post(route + "/gm-requests", json=value, headers=headers).get_json() == result
    changed = client.post(route + "/gm-requests", json={**value, "prompt": "Different input"}, headers=headers)
    assert changed.status_code == 409 and changed.get_json()["error"] == "GM_REQUEST_ID_CONFLICT"
    assert calls == [True]
    advanced = client.post(route + "/actions", json=action(packet, "move_inside"), headers=headers)
    assert advanced.status_code == 200 and advanced.get_json()["revision"] == 1
    assert client.post(route + "/gm-requests", json=value, headers=headers).get_json() == result
    stale = client.post(route + "/gm-requests", json={**value, "request_id": str(uuid.uuid4())}, headers=headers)
    assert stale.status_code == 409 and stale.get_json()["error"] == "STALE_REVISION"
    assert calls == [True]


def test_http_gm_prepared_poll_and_retry_202_then_unknown_never_recall(app):
    enable_test_gm(app, lambda *_: pytest.fail("crashed request must not call provider"))
    client = app.test_client()
    packet, headers, credentials = start(client)
    route = "/api/campaigns/" + packet["id"] + "/gm-requests"
    value = gm_http_request(packet)
    class Crash(BaseException):
        pass
    def crash(_):
        raise Crash()
    store = app.extensions["store"]
    with pytest.raises(Crash):
        store.gm_request(credentials["player_id"], packet["id"], value, app.extensions["gm_interpreter"], fault=crash)
    for response in (client.get(route + "/" + value["request_id"]), client.post(route, json=value, headers=headers)):
        assert response.status_code == 202 and response.get_json()["status"] == "prepared"
        assert response.headers["Retry-After"] == "1"
    with store.connect() as db:
        db.execute("UPDATE mobile_gm_requests SET expires_at=now()-interval '1 second'")
    result = client.get(route + "/" + value["request_id"])
    assert result.status_code == 200 and result.get_json()["status"] == "unknown"
    assert client.post(route, json=value, headers=headers).get_json() == result.get_json()
    assert client.get("/api/campaigns/" + packet["id"]).get_json() == packet


def test_http_gm_billing_failure_exposes_only_safe_error_and_never_retries(app):
    from mobile_game.gm import GMError
    calls = []
    def unavailable(*_):
        calls.append(True)
        error = GMError("GM_BILLING_UNAVAILABLE", attempted=True)
        error.message = "private provider error with credential-like fixture"
        raise error
    enable_test_gm(app, unavailable)
    client = app.test_client()
    packet, headers, _ = start(client)
    route = "/api/campaigns/" + packet["id"] + "/gm-requests"
    value = gm_http_request(packet)
    response = client.post(route, json=value, headers=headers)
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == "unknown" and result["error"]["code"] == "GM_BILLING_UNAVAILABLE"
    assert "private provider" not in response.get_data(as_text=True)
    assert client.post(route, json=value, headers=headers).get_json() == result
    assert calls == [True]
    assert client.get("/api/campaigns/" + packet["id"]).get_json() == packet


@pytest.mark.parametrize("enable,maximum,budget,allowed", [
    (None, "20", "1000000", False), ("0", "20", "1000000", False),
    ("1", None, "1000000", False), ("1", "20", None, False),
    ("1", "0", "1000000", False), ("1", "20", "0", False),
    ("1", "20", "23700", True), ("1", "20", "23699", False),
])
def test_http_gm_requires_explicit_limited_enable_even_with_configured_provider(app, monkeypatch, enable, maximum, budget, allowed):
    from mobile_game import gm
    monkeypatch.setattr(gm, "configured", lambda: True)
    for name, value in (("WOT_GM_ENABLED", enable), ("WOT_GM_MAX_REQUESTS", maximum), ("WOT_GM_BUDGET_MICRO_USD", budget)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    configured_app = create_app(app.extensions["store"].url, testing=True,
                                gm_interpreter=lambda *_: pytest.fail("configuration test must not call provider"))
    assert (configured_app.extensions["store"].gm_policy is not None) == allowed


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
    assert health.get_json()["release"] == "mobile-disposable-pilot-v4"


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


def test_personal_notes_cross_device_conflict_retry_export_and_no_game_mutation(app):
    client=app.test_client();packet,headers,credentials=start(client)
    base=f'/api/campaigns/{packet["id"]}';url=base+'/notes'
    assert client.get(url).get_json()=={'text':'','version':0}
    request={'expected_version':0,'text':'Remember to ask about the lesson. 🕯️'}
    saved=client.post(url,json=request,headers=headers).get_json()
    assert saved=={'text':request['text'],'version':1}
    assert client.post(url,json=request,headers=headers).get_json()==saved
    assert client.get(base).get_json()==packet
    fresh=app.test_client();fresh.post('/api/session/recover',json={'recovery_code':credentials['recovery_code']})
    assert fresh.get(url).get_json()==saved
    assert client.post(url,json={'expected_version':0,'text':'Stale overwrite'},headers=headers).status_code==409
    assert client.get(url).get_json()==saved
    exported=client.get(base+'/export').get_json()
    assert exported['player_notes']==saved
    assert exported['sha256']==digest({k:v for k,v in exported.items() if k!='sha256'})
    assert client.post(url,json={'expected_version':1,'text':''},headers=headers).get_json()=={'text':'','version':2}
    assert client.get(base).get_json()==packet


def test_personal_notes_owner_csrf_and_input_boundaries(app):
    client=app.test_client();packet,headers,_=start(client);url=f'/api/campaigns/{packet["id"]}/notes'
    foreign=app.test_client();_,other_headers,_=start(foreign)
    assert foreign.get(url).status_code==404
    assert foreign.post(url,json={'expected_version':0,'text':'intruder'},headers=other_headers).status_code==404
    assert app.test_client().get(url).status_code==401
    assert client.post(url,json={'expected_version':0,'text':'no csrf'}).status_code==403
    for version,content in [(True,'x'),(-1,'x'),(0,'x'*10001),(0,'bad\x00text'),(0,['x'])]:
        assert client.post(url,json={'expected_version':version,'text':content},headers=headers).status_code==422
    assert client.post(url,json={'expected_version':0,'text':'x'*10000},headers=headers).status_code==200


def test_connected_chapter_keeps_campaign_notes_history_and_recovery(app):
    client=app.test_client();_,headers,cred=start(client)
    packet=client.post('/api/campaigns',json={'request_id':str(uuid.uuid4()),'episode_id':'gallery-letter-v1'},headers=headers).get_json()
    base=f'/api/campaigns/{packet["id"]}'
    client.post(base+'/notes',json={'expected_version':0,'text':'Carry this plan forward.'},headers=headers)
    for choice in ('decline_letter','next_chapter','garden_listen','garden_welcome','garden_finish'):
        request=action(packet,choice)
        response=client.post(base+'/actions',json=request,headers=headers)
        assert response.status_code==200
        packet=response.get_json()
        assert client.post(base+'/actions',json=request,headers=headers).get_json()=={**packet,'replayed':True}
    saved=client.get(base).get_json()
    assert saved['revision']==5 and saved['state']['completed']
    assert len(saved['companion']['chapters'])==2
    assert all(c['completed'] for c in saved['companion']['chapters'])
    fresh=app.test_client();fresh.post('/api/session/recover',json={'recovery_code':cred['recovery_code']})
    assert fresh.get(base).get_json()==saved
    assert fresh.get(base+'/notes').get_json()['text']=='Carry this plan forward.'
    exported=fresh.get(base+'/export').get_json()
    assert len(exported['events'])==5 and exported['state']['world']['episode']['result']=='declined'
    assert exported['sha256']==digest({k:v for k,v in exported.items() if k!='sha256'})


def test_sandbox_tools_preview_commit_replay_ownership_and_resume(app):
    client=app.test_client();_,headers,cred=start(client)
    def call(name,args,code=200):
        response=client.post('/api/sandbox/tools/'+name,json=args,headers=headers)
        assert response.status_code==code,response.get_json()
        return response.get_json()
    specs=client.get('/api/sandbox/tools').get_json()
    assert not specs['chatgpt_connection_ready'] and len(specs['tools'])==4
    packet=call('sandbox_create',{'request_id':str(uuid.uuid4())});id=packet['id'];base=f'/api/campaigns/{id}'
    original=json.loads(json.dumps(packet))
    args={'campaign_id':id,'expected_revision':0,'action_id':str(uuid.uuid4()),'command':{'op':'cast','weave':'W02','target':'wooden_token'}}
    preview=call('sandbox_preview',args)
    assert preview['effects']['resources_after']['strain']==1 and not preview['committed']
    assert call('sandbox_read',{'campaign_id':id})==original
    bad={**preview['request'],'choice_hash':'forged'}
    call('sandbox_commit',{'campaign_id':id,'request':bad},409)
    committed=call('sandbox_commit',{'campaign_id':id,'request':preview['request']})
    assert committed['revision']==1 and committed['state']['resources']['strain']==1
    assert call('sandbox_commit',{'campaign_id':id,'request':preview['request']})=={**committed,'replayed':True}
    call('sandbox_preview',args,409)
    call('sandbox_read',{'campaign_id':id,'player_id':'forged'},422)
    call('sandbox_preview',{**args,'expected_revision':1,'command':{'op':'cast','weave':'W02','target':'invented','supervised':True}},422)
    fresh=app.test_client();fresh.post('/api/session/recover',json={'recovery_code':cred['recovery_code']})
    assert fresh.get(base).get_json()=={k:v for k,v in committed.items() if k!='replayed'}
    foreign=app.test_client();_,other_headers,_=start(foreign)
    assert foreign.post('/api/sandbox/tools/sandbox_read',json={'campaign_id':id},headers=other_headers).status_code==404
    assert client.post('/api/sandbox/tools/sandbox_read',json={'campaign_id':id}).status_code==403
    assert app.test_client().get('/api/sandbox/tools').status_code==401
    exported=client.get(base+'/export').get_json()
    assert exported['state']['world']['sandbox']['objects']['wooden_token']['location']=='inventory'
    assert exported['sha256']==digest({k:v for k,v in exported.items() if k!='sha256'})
