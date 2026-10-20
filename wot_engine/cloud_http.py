"""Authenticated WSGI backend for a trusted Sites MCP gateway.

The gateway must derive X-White-Tower-User from Sites authenticated headers,
never from model arguments. Its bearer secret stays only in server settings.
"""
import hmac
import os
from pathlib import Path

from .cloud_service import CloudGame, campaign_path, list_rehearsals, character_template
from .contracts import ContractError, canonical, parse_json, require
from .controller import ControllerError
from .storage import WriterBusy, RemotePending

MAX_BODY = 16384
FIELDS = {
    'list_rehearsals': ({'after'}, set()),
    'character_template': (set(), set()),
    'start_rehearsal': ({'character'}, set()),
    'read': ({'command','course_id'}, set()),
    'preview': ({'action_id','intent'}, {'action_id','intent'}),
    'accept': ({'action_id','stakes_hash'}, {'action_id','stakes_hash'}),
}


class GameApplication:
    def __init__(self, root, gateway_secret):
        require(type(gateway_secret) is str and len(gateway_secret) >= 32 and gateway_secret.isascii(),
                'A strong gateway secret is required.')
        self.root = Path(root).resolve()
        self.authorization = ('Bearer ' + gateway_secret).encode('ascii')

    def __call__(self, environ, start_response):
        def reply(status, value):
            body = canonical(value)
            start_response(status, [('Content-Type','application/json'),('Content-Length',str(len(body))),
                                    ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')])
            return [body]
        if environ.get('PATH_INFO') == '/health' and environ.get('REQUEST_METHOD') == 'GET':
            return reply('200 OK', {'status':'ready','release':'rehearsal-only'})
        supplied = environ.get('HTTP_AUTHORIZATION', '').encode('utf-8')
        if not hmac.compare_digest(supplied, self.authorization):
            return reply('401 Unauthorized', {'error':'AUTHENTICATION_REQUIRED'})
        principal = environ.get('HTTP_X_WHITE_TOWER_USER', '')
        if not principal or len(principal) > 256 or not principal.isascii() or any(ord(c) < 33 for c in principal):
            return reply('401 Unauthorized', {'error':'AUTHENTICATED_PLAYER_REQUIRED'})
        if environ.get('PATH_INFO') != '/v1/game':
            return reply('404 Not Found', {'error':'NOT_FOUND'})
        if environ.get('REQUEST_METHOD') != 'POST':
            return reply('405 Method Not Allowed', {'error':'POST_REQUIRED'})
        if environ.get('CONTENT_TYPE','').split(';')[0].strip() != 'application/json':
            return reply('415 Unsupported Media Type', {'error':'JSON_REQUIRED'})
        try:
            raw_length = environ.get('CONTENT_LENGTH', '')
            require(raw_length.isdecimal() and len(raw_length) <= 6, 'Invalid length.')
            length = int(raw_length)
            if not 1 <= length <= MAX_BODY:
                return reply('413 Content Too Large', {'error':'REQUEST_SIZE'})
            raw = environ['wsgi.input'].read(length)
            require(len(raw) == length, 'Truncated body.')
            body = parse_json(raw)
            require(type(body) is dict and {'operation','arguments'} <= set(body), 'Invalid request.')
            operation, arguments = body['operation'], body['arguments']
            require(type(operation) is str and operation in FIELDS and type(arguments) is dict, 'Invalid operation.')
            allowed, required = FIELDS[operation]
            require(required <= set(arguments) <= allowed, 'Invalid arguments.')
            global_operation = operation in ('list_rehearsals','character_template')
            require(set(body) == ({'operation','arguments'} if global_operation else
                                 {'operation','arguments','campaign_id'}), 'Invalid request fields.')
            if global_operation:
                result = (list_rehearsals(self.root, principal, **arguments) if operation == 'list_rehearsals'
                          else character_template())
                return reply('200 OK', {'result':result})
            path = campaign_path(self.root, principal, body['campaign_id'])
            if operation != 'start_rehearsal' and not (path / 'initialization.json').is_file():
                return reply('404 Not Found', {'error':'CAMPAIGN_NOT_FOUND',
                             'message':'List your saved campaigns or explicitly start a new rehearsal.'})
            game = CloudGame(self.root, principal, body['campaign_id'])
            result = getattr(game, operation)(**arguments)
            return reply('200 OK', {'result':result})
        except (ContractError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            return reply('400 Bad Request', {'error':'INVALID_REQUEST_OR_ACTION','message':'Check the action, its preview and the current campaign status.'})
        except (WriterBusy, RemotePending):
            return reply('409 Conflict', {'error':'SAVE_PENDING','message':'Resume the same accepted action.'})
        except ControllerError as exc:
            return reply('409 Conflict', {'error':exc.code,'message':'The controller has not released this operation.'})
        except Exception:
            # No traceback, path, token or stored payload reaches the caller.
            return reply('500 Internal Server Error', {'error':'SERVICE_UNAVAILABLE'})


def application_from_environment():
    root = os.environ.get('WOT_DATA_ROOT', '')
    if not root or not os.path.isabs(root) or not os.path.ismount(root):
        raise RuntimeError('WOT_DATA_ROOT must be a mounted persistent volume.')
    return GameApplication(root, os.environ.get('WOT_GATEWAY_SECRET', ''))
