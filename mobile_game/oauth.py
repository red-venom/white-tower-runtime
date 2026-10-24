"""OAuth authorization code + S256 PKCE using Authlib and the existing owner login.

All credential material is hashed in PostgreSQL. Grant-family locks serialize
code exchange, refresh rotation and replay revocation across server workers.
No implicit, password, client-credentials or arbitrary-redirect grant exists.
"""
import hashlib
import os
import re
import secrets
import uuid
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749 import OAuth2Request
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant, RefreshTokenGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from flask import g, jsonify, request, send_from_directory

from .store import Problem, secret_hash

SCOPES = 'sandbox:read sandbox:write'
REDIRECT = 'https://chatgpt.com/connector_platform_oauth_redirect'
SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_oauth_clients (
 id text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS mobile_oauth_grants (
 id uuid PRIMARY KEY, player_id uuid NOT NULL REFERENCES mobile_players(id),
 client_id text NOT NULL REFERENCES mobile_oauth_clients(id), resource text NOT NULL,
 scope text NOT NULL, revoked boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days'
);
CREATE TABLE IF NOT EXISTS mobile_oauth_codes (
 code_hash text PRIMARY KEY, grant_id uuid NOT NULL REFERENCES mobile_oauth_grants(id),
 redirect_uri text NOT NULL, code_challenge text NOT NULL,
 code_challenge_method text NOT NULL CHECK(code_challenge_method='S256'),
 used boolean NOT NULL DEFAULT false,
 expires_at timestamptz NOT NULL DEFAULT now() + interval '5 minutes'
);
CREATE TABLE IF NOT EXISTS mobile_oauth_tokens (
 access_hash text PRIMARY KEY, refresh_hash text NOT NULL UNIQUE,
 grant_id uuid NOT NULL REFERENCES mobile_oauth_grants(id),
 scope text NOT NULL, rotated boolean NOT NULL DEFAULT false,
 expires_at timestamptz NOT NULL DEFAULT now() + interval '1 hour'
);
CREATE INDEX IF NOT EXISTS mobile_oauth_grant_owner ON mobile_oauth_grants(player_id);
CREATE INDEX IF NOT EXISTS mobile_oauth_token_grant ON mobile_oauth_tokens(grant_id);
"""


class Client:
    def __init__(self, client_id): self.client_id = client_id
    def get_client_id(self): return self.client_id
    def get_default_redirect_uri(self): return REDIRECT
    def check_redirect_uri(self, uri): return uri == REDIRECT
    def check_response_type(self, value): return value == 'code'
    def check_grant_type(self, value): return value in ('authorization_code', 'refresh_token')
    def check_endpoint_auth_method(self, method, endpoint): return method == 'none'
    def check_client_secret(self, secret): return False
    def get_allowed_scope(self, scope):
        return ' '.join(s for s in (scope or SCOPES).split() if s in SCOPES.split())


class Credential(SimpleNamespace):
    def get_redirect_uri(self): return self.redirect_uri
    def get_scope(self): return self.scope
    def check_client(self, client): return self.client_id == client.client_id


class ProtocolRequest(OAuth2Request):
    def __init__(self, origin, data):
        super().__init__(request.method, origin + request.path, headers=request.headers)
        self.payload = BasicOAuth2Payload(data)
    @property
    def form(self): return self.payload.data
    @property
    def args(self): return self.payload.data


def install(app, store, origin, static):
    # Canonical configuration, never an attacker-controlled Host or forwarded header.
    parsed = urlsplit(origin)
    enabled = os.environ.get('WOT_MCP_ENABLED') == '1'
    if enabled and (parsed.scheme != 'https' or not parsed.hostname or parsed.path or
                    parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise RuntimeError('MCP requires a canonical HTTPS PUBLIC_ORIGIN')
    resource = origin + '/mcp'
    app.extensions['oauth_enabled'] = enabled
    app.extensions['mcp_resource'] = resource

    def require_enabled():
        if not enabled: raise Problem(503, 'MCP_NOT_CONFIGURED', 'The ChatGPT connection is not enabled yet.')

    def rate_limit():
        address = request.headers.get('X-Railway-Client-IP', request.remote_addr or 'unknown')
        store.rate_limit('oauth:' + hashlib.sha256(address.encode()).hexdigest(), 120, 60)

    def data():
        values = request.form if request.method == 'POST' else request.args
        if any(len(values.getlist(k)) != 1 for k in values):
            raise Problem(400, 'invalid_request', 'Repeated OAuth parameters are not accepted.')
        return values.to_dict()

    def query_client(client_id):
        row = g.oauth_db.execute('SELECT id FROM mobile_oauth_clients WHERE id=%s', (client_id,)).fetchone()
        return Client(row['id']) if row else None

    class Server(AuthorizationServer):
        def create_oauth2_request(self, ignored):
            return ProtocolRequest(origin, g.oauth_data)

    def lock_grant(grant_id):
        return g.oauth_db.execute('SELECT *, expires_at>now() AS fresh FROM mobile_oauth_grants WHERE id=%s FOR UPDATE', (grant_id,)).fetchone()

    def revoke(grant_id):
        g.oauth_db.execute('UPDATE mobile_oauth_grants SET revoked=true WHERE id=%s', (grant_id,))

    def save_token(token, req):
        credential = req.authorization_code or req.refresh_token
        g.oauth_db.execute('''INSERT INTO mobile_oauth_tokens(access_hash,refresh_hash,grant_id,scope)
          VALUES(%s,%s,%s,%s)''', (secret_hash(token['access_token']), secret_hash(token['refresh_token']), credential.grant_id, token['scope']))

    class CodeGrant(AuthorizationCodeGrant):
        TOKEN_ENDPOINT_AUTH_METHODS = ['none']

        def save_authorization_code(self, code, req):
            grant_id = uuid.uuid4()
            g.oauth_db.execute('''INSERT INTO mobile_oauth_grants(id,player_id,client_id,resource,scope)
             VALUES(%s,%s,%s,%s,%s)''', (grant_id, req.user, req.client.client_id, resource, req.scope))
            g.oauth_db.execute('''INSERT INTO mobile_oauth_codes(code_hash,grant_id,redirect_uri,code_challenge,code_challenge_method)
             VALUES(%s,%s,%s,%s,'S256')''', (secret_hash(code), grant_id, req.payload.redirect_uri, req.payload.data['code_challenge']))

        def query_authorization_code(self, code, client):
            row = g.oauth_db.execute('SELECT *, expires_at>now() AS fresh FROM mobile_oauth_codes WHERE code_hash=%s', (secret_hash(code),)).fetchone()
            if not row: return None
            grant = lock_grant(row['grant_id'])
            if grant['client_id'] != client.client_id or grant['resource'] != resource: return None
            # Re-read after taking the family lock: another worker may have redeemed it.
            row = g.oauth_db.execute('SELECT *, expires_at>now() AS fresh FROM mobile_oauth_codes WHERE code_hash=%s', (secret_hash(code),)).fetchone()
            if row['used']:
                revoke(row['grant_id'])
                return None
            if not row['fresh'] or not grant['fresh'] or grant['revoked']: return None
            return Credential(**{**row, 'player_id':grant['player_id'], 'client_id':grant['client_id'], 'scope':grant['scope']})

        def delete_authorization_code(self, credential):
            g.oauth_db.execute('UPDATE mobile_oauth_codes SET used=true WHERE code_hash=%s', (credential.code_hash,))

        def authenticate_user(self, credential): return credential.player_id

    class RefreshGrant(RefreshTokenGrant):
        TOKEN_ENDPOINT_AUTH_METHODS = ['none']
        INCLUDE_NEW_REFRESH_TOKEN = True

        def authenticate_refresh_token(self, token):
            row = g.oauth_db.execute('SELECT * FROM mobile_oauth_tokens WHERE refresh_hash=%s', (secret_hash(token),)).fetchone()
            if not row: return None
            grant = lock_grant(row['grant_id'])
            if grant['client_id'] != self.request.client.client_id or grant['resource'] != resource: return None
            row = g.oauth_db.execute('SELECT * FROM mobile_oauth_tokens WHERE refresh_hash=%s', (secret_hash(token),)).fetchone()
            if row['rotated']:
                revoke(row['grant_id'])
                return None
            if not grant['fresh'] or grant['revoked']: return None
            return Credential(**{**row,'player_id':grant['player_id'],'client_id':grant['client_id']})

        def authenticate_user(self, credential): return credential.player_id
        def revoke_old_credential(self, credential):
            g.oauth_db.execute('UPDATE mobile_oauth_tokens SET rotated=true WHERE access_hash=%s', (credential.access_hash,))

    app.config.update(OAUTH2_REFRESH_TOKEN_GENERATOR=True,
                      OAUTH2_TOKEN_EXPIRES_IN={'authorization_code':3600,'refresh_token':3600},
                      OAUTH2_SCOPES_SUPPORTED=SCOPES.split())
    server = Server(app, query_client=query_client, save_token=save_token)
    pkce = CodeChallenge(required=True)
    pkce.SUPPORTED_CODE_CHALLENGE_METHOD = ['S256']
    server.register_grant(CodeGrant, [pkce])
    server.register_grant(RefreshGrant)

    @app.get('/.well-known/oauth-protected-resource')
    @app.get('/.well-known/oauth-protected-resource/mcp')
    def resource_metadata():
        require_enabled()
        return jsonify(resource=resource, authorization_servers=[origin], scopes_supported=SCOPES.split(), bearer_methods_supported=['header'])

    @app.get('/.well-known/oauth-authorization-server')
    def authorization_metadata():
        require_enabled()
        return jsonify(issuer=origin, authorization_endpoint=origin+'/oauth/authorize',
          token_endpoint=origin+'/oauth/token', registration_endpoint=origin+'/oauth/register',
          response_types_supported=['code'], grant_types_supported=['authorization_code','refresh_token'],
          token_endpoint_auth_methods_supported=['none'], code_challenge_methods_supported=['S256'],
          scopes_supported=SCOPES.split(), authorization_response_iss_parameter_supported=True)

    @app.post('/oauth/register')
    def register_client():
        require_enabled(); rate_limit()
        value = request.get_json(silent=True)
        if (type(value) is not dict or value.get('redirect_uris') != [REDIRECT] or
            value.get('token_endpoint_auth_method','none') != 'none' or
            value.get('response_types',['code']) != ['code'] or
            type(value.get('grant_types',[])) is not list or
            any(type(v) is not str for v in value.get('grant_types',[])) or
            set(value.get('grant_types',['authorization_code','refresh_token'])) - {'authorization_code','refresh_token'}):
            raise Problem(400, 'invalid_client_metadata', 'Only the registered ChatGPT callback and authorization code flow are supported.')
        client_id = secrets.token_urlsafe(24)
        with store.connect() as db: db.execute('INSERT INTO mobile_oauth_clients(id) VALUES(%s)', (client_id,))
        return jsonify(client_id=client_id, client_name='ChatGPT', redirect_uris=[REDIRECT],
          token_endpoint_auth_method='none', response_types=['code'], grant_types=['authorization_code','refresh_token']), 201

    def validate_authorization(value):
        if (type(value) is not dict or any(type(v) is not str for v in value.values()) or
            value.get('resource') != resource or value.get('redirect_uri') != REDIRECT or
            value.get('response_type') != 'code' or value.get('code_challenge_method') != 'S256' or
            not re.fullmatch(r'[A-Za-z0-9_-]{43}', value.get('code_challenge','')) or
            not 1 <= len(value.get('state','')) <= 2048 or
            set(value.get('scope',SCOPES).split()) - set(SCOPES.split())):
            raise Problem(400, 'invalid_request', 'Invalid OAuth authorization request. Start the connection again from ChatGPT.')
        return value

    @app.get('/oauth/authorize')
    def authorize_page():
        require_enabled(); rate_limit()
        value = validate_authorization(data())
        with store.connect() as db:
            g.oauth_db = db
            if not query_client(value.get('client_id')): raise Problem(400,'invalid_client','Unknown connection. Start again from ChatGPT.')
        return send_from_directory(static, 'connect.html')

    @app.get('/connect')
    def manage_page():
        require_enabled()
        return send_from_directory(static, 'connect.html')

    @app.post('/api/oauth/authorize')
    def consent():
        # Existing API middleware requires owner cookie, same origin and CSRF.
        require_enabled()
        payload = request.get_json()
        if type(payload) is not dict or set(payload) != {'authorization','allow'} or type(payload['allow']) is not bool:
            raise Problem(400,'invalid_request','Choose whether to allow this connection.')
        g.oauth_data = validate_authorization(payload['authorization'])
        with store.connect() as db:
            g.oauth_db = db
            response = server.create_authorization_response(grant_user=g.identity['player_id'] if payload['allow'] else None)
            if response.status_code != 302: return response
            # RFC 9207 issuer identification on success and redirected errors.
            return jsonify(redirect=response.headers['Location']+'&'+urlencode({'iss':origin}))

    @app.post('/oauth/token')
    def token_endpoint():
        require_enabled(); rate_limit()
        if request.mimetype != 'application/x-www-form-urlencoded' or request.args:
            raise Problem(400,'invalid_request','Use a form-encoded token request without query parameters.')
        g.oauth_data = data()
        if g.oauth_data.get('resource') != resource:
            raise Problem(400,'invalid_target','The token resource must match this sandbox.')
        with store.connect() as db:
            g.oauth_db = db
            return server.create_token_response()

    @app.post('/api/oauth/disconnect')
    def disconnect():
        require_enabled()
        if request.get_json() != {}: raise Problem(400,'invalid_request','No arguments required.')
        with store.connect() as db:
            db.execute('UPDATE mobile_oauth_grants SET revoked=true WHERE player_id=%s', (g.identity['player_id'],))
        return jsonify(disconnected=True)

    def authenticate(header):
        require_enabled()
        if not isinstance(header,str) or not re.fullmatch(r'(?i:Bearer) [A-Za-z0-9._~-]{20,512}',header): return None
        with store.connect() as db:
            return db.execute('''SELECT g.player_id,t.scope FROM mobile_oauth_tokens t
              JOIN mobile_oauth_grants g ON g.id=t.grant_id
              WHERE t.access_hash=%s AND t.expires_at>now() AND NOT t.rotated
              AND g.expires_at>now() AND NOT g.revoked AND g.resource=%s''',
              (secret_hash(header[7:]),resource)).fetchone()
    app.extensions['mcp_authenticate'] = authenticate
