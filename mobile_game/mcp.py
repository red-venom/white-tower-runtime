"""Stateless Streamable HTTP JSON transport; all durable state lives in PostgreSQL."""
import json
from flask import jsonify, request
from .sandbox_tools import TOOLS, call
from .store import Problem

VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')


def install(app, store, origin):
    def error(code, message, id=None, status=400):
        return jsonify(jsonrpc='2.0', id=id, error={'code':code,'message':message}), status

    def challenge(status=401, scope='sandbox:read sandbox:write'):
        response = jsonify(error='insufficient_scope' if status==403 else 'invalid_token')
        response.status_code = status
        response.headers['WWW-Authenticate'] = (f'Bearer resource_metadata="{origin}/.well-known/oauth-protected-resource/mcp", '
          f'scope="{scope}"'+(', error="insufficient_scope"' if status==403 else ''))
        return response

    @app.route('/mcp', methods=['GET','POST','DELETE'])
    def endpoint():
        supplied_origin = request.headers.get('Origin')
        if supplied_origin and supplied_origin not in (origin,'https://chatgpt.com'):
            return error(-32000,'Origin rejected.',status=403)
        if request.args: return error(-32600,'MCP does not accept query parameters.')
        identity = app.extensions['mcp_authenticate'](request.headers.get('Authorization'))
        if not identity: return challenge()
        if request.method != 'POST': return '', 405, {'Allow':'POST'}
        store.rate_limit('mcp:'+str(identity['player_id']),120,60)
        if request.mimetype != 'application/json': return error(-32600,'Use application/json.',status=415)
        accept = request.accept_mimetypes
        if not accept['application/json'] or not accept['text/event-stream']:
            return error(-32600,'Accept application/json and text/event-stream.',status=406)
        version = request.headers.get('MCP-Protocol-Version','2025-03-26')
        if version not in VERSIONS: return error(-32600,'Unsupported MCP protocol version.')
        body = request.get_json(silent=True)
        if type(body) is not dict or body.get('jsonrpc')!='2.0' or type(body.get('method')) is not str:
            return error(-32600,'Expected one JSON-RPC request.')
        id = body.get('id')
        if 'id' in body and (type(id) not in (str,int) or isinstance(id,bool)):
            return error(-32600,'Invalid request ID.')
        method = body['method']; params = body.get('params',{})
        if type(params) is not dict: return error(-32602,'Invalid parameters.',id)
        if 'id' not in body:
            if method in ('notifications/initialized','notifications/cancelled'): return '',202
            return error(-32600,'This operation requires a request ID.')
        if method=='initialize':
            if (type(params.get('protocolVersion')) is not str or type(params.get('capabilities')) is not dict or
                type(params.get('clientInfo')) is not dict): return error(-32602,'Invalid initialization.',id)
            result = {'protocolVersion':params['protocolVersion'] if params['protocolVersion'] in VERSIONS else VERSIONS[0],
              'capabilities':{'tools':{'listChanged':False}}, 'serverInfo':{'name':'White Tower sandbox','version':'1.0.0'},
              'instructions':'Read the saved sandbox before narrating. Use sandbox_list to resume. Preview supported actions, respect player choice, commit once and narrate only the receipt. Unsupported mechanics are unavailable, not automatic successes. Use disposable data only.'}
        elif method=='ping': result = {}
        elif method=='tools/list':
            result = {'tools':[{**t,'securitySchemes':[{'type':'oauth2','scopes':['sandbox:read'] if t['annotations']['readOnlyHint'] else ['sandbox:read','sandbox:write']}]} for t in TOOLS]}
        elif method=='tools/call':
            if type(params.get('name')) is not str or type(params.get('arguments',{})) is not dict:
                return error(-32602,'Invalid tool call.',id)
            tool = next((t for t in TOOLS if t['name']==params['name']),None)
            if not tool: return error(-32602,'Unknown tool.',id,status=200)
            required = {'sandbox:read'} if tool['annotations']['readOnlyHint'] else {'sandbox:read','sandbox:write'}
            if not required.issubset(set(identity['scope'].split())): return challenge(403,' '.join(sorted(required)))
            try:
                value = call(store,identity['player_id'],tool['name'],params.get('arguments',{}))
                result = {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}], 'structuredContent':value,'isError':False}
            except Problem as exc:
                value = {'error':exc.code,'message':exc.message}
                result = {'content':[{'type':'text','text':json.dumps(value)}],'isError':True}
        else: return error(-32601,'Method not found.',id,status=200)
        return jsonify(jsonrpc='2.0',id=id,result=result)
