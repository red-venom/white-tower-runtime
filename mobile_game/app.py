"""Phone web interface. PostgreSQL is required; the desktop is not a dependency."""
import hashlib
import hmac
import json
import os
from pathlib import Path

import psycopg
from flask import Flask, Response, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .store import Store, Problem

STATIC = Path(__file__).parent / "static"
COOKIE = "wt_mobile_session"


def create_app(database_url=None, testing=False):
    app = Flask(__name__, static_folder=None)
    app.config.update(TESTING=testing, MAX_CONTENT_LENGTH=16384)
    store = Store(database_url or os.environ.get("DATABASE_URL"))
    store.initialize()
    app.extensions["store"] = store
    production = not testing and os.environ.get("WOT_LOCAL_DEV") != "1"
    public_origin = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")

    @app.before_request
    def protect():
        g.identity = None
        if not request.path.startswith("/api/"):
            return
        if request.method not in ("GET", "HEAD"):
            if request.mimetype != "application/json":
                raise Problem(415, "JSON_REQUIRED", "Please reload the game before continuing.")
            origin = request.headers.get("Origin")
            host_origin = public_origin or (("https://" if production else request.scheme + "://") + request.host)
            if origin and origin.rstrip("/") != host_origin:
                raise Problem(403, "ORIGIN_REJECTED", "Open the game directly to continue.")
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                raise Problem(403, "ORIGIN_REJECTED", "Open the game directly to continue.")
        identity = store.session(request.cookies.get(COOKIE))
        g.identity = identity
        if request.path in ("/api/session", "/api/session/recover"):
            if request.path == "/api/session" and identity:
                return
            # No credential is needed to create an empty disposable session.
            address = request.headers.get("X-Railway-Client-IP", request.remote_addr or "unknown") if production else request.remote_addr or "test"
            bucket = "entry:" + hashlib.sha256(address.encode()).hexdigest()
            store.rate_limit(bucket, 120 if testing else 40, 3600)
            return
        if not identity:
            raise Problem(401, "SESSION_REQUIRED", "Reconnect with your recovery code to see your saved game.")
        if request.method not in ("GET", "HEAD"):
            supplied = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(supplied, identity["csrf_token"]):
                raise Problem(403, "SESSION_CHANGED", "Please reload the game before continuing.")
            store.rate_limit("actions:" + str(identity["player_id"]), 300 if testing else 120, 60)

    @app.after_request
    def headers(response):
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(Problem)
    def known_error(exc):
        return jsonify(error=exc.code, message=exc.message), exc.status

    @app.errorhandler(psycopg.Error)
    def database_error(exc):
        # Avoid leaking connection strings, queries, or private state.
        app.logger.warning("database operation unavailable: %s", type(exc).__name__)
        return jsonify(error="SAVE_UNCERTAIN", message="The connection was interrupted. Keep this page and retry the same action."), 503

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error="REQUEST_REJECTED", message=exc.description), exc.code
        if testing:
            raise exc
        app.logger.error("request failed: %s", type(exc).__name__)
        return jsonify(error="SAVE_UNCERTAIN", message="The result could not be confirmed. Retry the same action."), 500

    def body(fields):
        value = request.get_json()
        if not isinstance(value, dict) or set(value) != fields:
            raise Problem(422, "INVALID_REQUEST", "Please reload the game and try again.")
        return value

    def session_reply(value):
        response = jsonify(csrf_token=value["csrf_token"], recovery_code=value["recovery_code"])
        response.set_cookie(COOKIE, value["token"], max_age=30 * 86400, secure=production, httponly=True, samesite="Strict", path="/")
        return response

    @app.post("/api/session")
    def session():
        body(set())
        if g.identity:
            return jsonify(csrf_token=g.identity["csrf_token"], recovery_code=None)
        return session_reply(store.new_session())

    @app.post("/api/session/recover")
    def recover():
        value = body({"recovery_code"})
        return session_reply(store.new_session(value["recovery_code"]))

    @app.post("/api/session/recovery-code")
    def recovery_code():
        body(set())
        return jsonify(recovery_code=store.rotate_recovery(g.identity["player_id"]))

    @app.get("/api/campaigns")
    def campaigns():
        return jsonify(campaigns=store.campaigns(g.identity["player_id"]))

    @app.post("/api/campaigns")
    def create():
        value = body({"request_id"})
        return jsonify(store.create(g.identity["player_id"], value["request_id"]))

    @app.get("/api/campaigns/<campaign>")
    def read(campaign):
        return jsonify(store.read(g.identity["player_id"], campaign))

    @app.post("/api/campaigns/<campaign>/actions")
    def act(campaign):
        value = body({"action_id", "expected_revision", "choice_id", "choice_hash"})
        return jsonify(store.act(g.identity["player_id"], campaign, value))

    @app.get("/api/campaigns/<campaign>/export")
    def export(campaign):
        value = store.export(g.identity["player_id"], campaign)
        response = Response(json.dumps(value, ensure_ascii=False, indent=2) + "\n", mimetype="application/json")
        response.headers["Content-Disposition"] = f'attachment; filename="white-tower-sample-{campaign}-r{value["revision"]:04d}.json"'
        return response

    @app.get("/health")
    def health():
        store.health()
        return jsonify(status="ready", database="postgresql", release="mobile-disposable-pilot-v1", live_import=False)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/assets/<path:filename>")
    @app.get("/static/<path:filename>")
    def assets(filename):
        return send_from_directory(STATIC, filename)

    return app
