"""Real DB: browser consent -> OAuth/PKCE -> MCP -> sandbox -> refresh/revoke."""
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit,parse_qs,urlencode

import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from mobile_game.oauth import REDIRECT,SCOPES
from tests_mobile.test_http import app, start

ORIGIN='https://tower.example'

@pytest.fixture
def connected(app,monkeypatch):
    from mobile_game.app import create_app
    monkeypatch.setenv('PUBLIC_ORIGIN',ORIGIN)
    monkeypatch.setenv('WOT_MCP_ENABLED','1')
    application=create_app(app.extensions['store'].url,testing=True)
    return application

def registration(client):
    reply=client.post('/oauth/register',json={'redirect_uris':[REDIRECT],'token_endpoint_auth_method':'none'})
    assert reply.status_code==201
    return reply.json['client_id']

def authorize(app,scope=SCOPES):
    owner=app.test_client();_,headers,credentials=start(owner)
    client_id=registration(owner);verifier=secrets.token_urlsafe(48)
    value={'client_id':client_id,'redirect_uri':REDIRECT,'response_type':'code','scope':scope,
      'resource':ORIGIN+'/mcp','code_challenge_method':'S256','code_challenge':create_s256_code_challenge(verifier),'state':secrets.token_urlsafe(24)}
    page=owner.get('/oauth/authorize?'+urlencode(value));assert page.status_code==200
    response=owner.post('/api/oauth/authorize',json={'authorization':value,'allow':True},headers=headers)
    assert response.status_code==200,response.json
    query=parse_qs(urlsplit(response.json['redirect']).query)
    assert query['state']==[value['state']] and query['iss']==[ORIGIN]
    exchange={'grant_type':'authorization_code','client_id':client_id,'code':query['code'][0],
      'code_verifier':verifier,'redirect_uri':REDIRECT,'resource':ORIGIN+'/mcp'}
    return owner,headers,credentials,value,exchange

def issue(app,scope=SCOPES):
    owner,headers,credentials,value,exchange=authorize(app,scope)
    result=app.test_client().post('/oauth/token',data=exchange)
    assert result.status_code==200,result.json
    return owner,headers,credentials,value,exchange,result.json

def rpc(client,token,method,params=None,id=1,**extra):
    body={'jsonrpc':'2.0','method':method,'params':params or {}}
    if id is not None:body['id']=id
    headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25',**extra}
    return client.post('/mcp',json=body,headers=headers)

def tool(client,token,name,args):
    response=rpc(client,token,'tools/call',{'name':name,'arguments':args})
    assert response.status_code==200,response.json
    result=response.json['result'];assert not result['isError'],result
    return result['structuredContent']

def test_complete_oauth_mcp_game_and_fresh_client(connected):
    owner,headers,credentials,value,exchange,tokens=issue(connected)
    remote=connected.test_client();token=tokens['access_token']
    init=rpc(remote,token,'initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'QA','version':'1'}})
    assert init.json['result']['protocolVersion']=='2025-11-25'
    assert rpc(remote,token,'notifications/initialized',id=None).status_code==202
    names={t['name'] for t in rpc(remote,token,'tools/list').json['result']['tools']}
    assert names=={'sandbox_list','sandbox_create','sandbox_read','sandbox_preview','sandbox_commit'}
    assert tool(remote,token,'sandbox_list',{})=={'campaigns':[]}
    packet=tool(remote,token,'sandbox_create',{'request_id':str(uuid.uuid4())})
    preview=tool(remote,token,'sandbox_preview',{'campaign_id':packet['id'],'action_id':str(uuid.uuid4()),'expected_revision':0,'command':{'op':'take','target':'cloth'}})
    assert tool(remote,token,'sandbox_read',{'campaign_id':packet['id']})==packet
    args={'campaign_id':packet['id'],'request':preview['request']}
    saved=tool(remote,token,'sandbox_commit',args)
    assert tool(remote,token,'sandbox_commit',args)=={**saved,'replayed':True}
    assert owner.get('/api/campaigns/'+packet['id']).json=={k:v for k,v in saved.items() if k!='replayed'}
    fresh=connected.test_client()
    found=tool(fresh,token,'sandbox_list',{})['campaigns']
    assert len(found)==1 and found[0]['id']==packet['id'] and found[0]['revision']==1
    assert tool(fresh,token,'sandbox_read',{'campaign_id':found[0]['id']})['revision']==1

def test_discovery_and_fail_closed(connected,app):
    c=connected.test_client()
    meta=c.get('/.well-known/oauth-protected-resource/mcp').json
    assert meta['resource']==ORIGIN+'/mcp' and meta['authorization_servers']==[ORIGIN]
    auth=c.get('/.well-known/oauth-authorization-server').json
    assert auth['code_challenge_methods_supported']==['S256']
    for method in ('get','delete','post'):
        denied=getattr(c,method)('/mcp')
        assert denied.status_code==401 and 'resource_metadata=' in denied.headers['WWW-Authenticate']
    assert app.test_client().post('/mcp').status_code==503

@pytest.mark.parametrize('change',[{'resource':'https://elsewhere.example/mcp'},{'redirect_uri':'https://attacker.example/'},{'code_challenge_method':'plain'},{'code_challenge':''},{'scope':'admin'},{'response_type':'token'}])
def test_invalid_authorization_and_callbacks(connected,change):
    owner,headers,_,value,_=authorize(connected)
    rejected=owner.post('/api/oauth/authorize',json={'authorization':{**value,**change},'allow':True},headers=headers)
    assert rejected.status_code==400 and 'redirect' not in rejected.json
    bad=owner.post('/oauth/register',json={'redirect_uris':[change.get('redirect_uri','https://attacker.example/') ]})
    assert bad.status_code==400

def test_consent_requires_owner_csrf_and_denial_keeps_state(connected):
    owner,headers,_,value,_=authorize(connected)
    payload={'authorization':value,'allow':True}
    assert connected.test_client().post('/api/oauth/authorize',json=payload,headers=headers).status_code==401
    assert owner.post('/api/oauth/authorize',json=payload).status_code==403
    assert owner.post('/api/oauth/authorize',json=payload,headers={**headers,'Origin':'https://evil.example'}).status_code==403
    denied=owner.post('/api/oauth/authorize',json={**payload,'allow':False},headers=headers)
    query=parse_qs(urlsplit(denied.json['redirect']).query)
    assert query['error']==['access_denied'] and query['iss']==[ORIGIN]

def test_pkce_resource_client_and_code_replay(connected):
    owner,headers,_,value,exchange=authorize(connected)
    remote=connected.test_client()
    for field,new in [('code_verifier',secrets.token_urlsafe(48)),('resource','https://evil.example'),('redirect_uri','https://evil.example'),('client_id',registration(remote))]:
        assert remote.post('/oauth/token',data={**exchange,field:new}).status_code==400
    result=remote.post('/oauth/token',data=exchange);assert result.status_code==200
    assert rpc(remote,result.json['access_token'],'ping').status_code==200
    assert remote.post('/oauth/token',data=exchange).status_code==400
    assert rpc(remote,result.json['access_token'],'ping').status_code==401

def test_refresh_rotation_scope_and_replay_revokes_family(connected):
    _,_,_,value,_,tokens=issue(connected)
    remote=connected.test_client()
    refresh={'grant_type':'refresh_token','client_id':value['client_id'],'refresh_token':tokens['refresh_token'],'resource':ORIGIN+'/mcp'}
    assert remote.post('/oauth/token',data={**refresh,'scope':'admin'}).status_code==400
    rotated=remote.post('/oauth/token',data=refresh);assert rotated.status_code==200,rotated.json
    assert rotated.json['refresh_token']!=tokens['refresh_token']
    assert rpc(remote,tokens['access_token'],'ping').status_code==401
    assert rpc(remote,rotated.json['access_token'],'ping').status_code==200
    assert remote.post('/oauth/token',data=refresh).status_code==400
    assert rpc(remote,rotated.json['access_token'],'ping').status_code==401

def test_scopes_owner_isolation_and_disconnect(connected):
    owner,headers,_,_,_,tokens=issue(connected,'sandbox:read')
    remote=connected.test_client();token=tokens['access_token']
    assert tool(remote,token,'sandbox_list',{})=={'campaigns':[]}
    denied=rpc(remote,token,'tools/call',{'name':'sandbox_create','arguments':{'request_id':str(uuid.uuid4())}})
    assert denied.status_code==403 and 'insufficient_scope' in denied.headers['WWW-Authenticate']
    stranger,_,_=start(connected.test_client())
    denied=rpc(remote,token,'tools/call',{'name':'sandbox_read','arguments':{'campaign_id':stranger['id']}})
    assert denied.json['result']['isError'] and 'CAMPAIGN_NOT_FOUND' in str(denied.json)
    assert owner.post('/api/oauth/disconnect',json={},headers=headers).json=={'disconnected':True}
    assert rpc(remote,token,'ping').status_code==401

def test_expiration_and_malformed_protocol(connected):
    _,_,_,_,_,tokens=issue(connected);token=tokens['access_token'];c=connected.test_client()
    assert rpc(c,token,'ping',Origin='https://evil.example').status_code==403
    assert rpc(c,token,'ping',**{'MCP-Protocol-Version':'invalid'}).status_code==400
    assert rpc(c,token,'ping',Accept='application/json').status_code==406
    assert c.post('/mcp',json=[],headers={'Authorization':'Bearer '+token,'Accept':'application/json,text/event-stream'}).status_code==400
    assert rpc(c,token,'tools/call',{'name':'sandbox_create'},id=None).status_code==400
    assert c.get('/mcp',headers={'Authorization':'Bearer '+token}).status_code==405
    with connected.extensions['store'].connect() as db:db.execute("UPDATE mobile_oauth_tokens SET expires_at=now()-interval '1 second'")
    assert rpc(c,token,'ping').status_code==401

def test_simultaneous_code_exchange_only_one_succeeds(connected):
    _,_,_,_,exchange=authorize(connected)
    def exchange_once(_):return connected.test_client().post('/oauth/token',data=exchange).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(exchange_once,range(2)))
    assert sorted(results)==[200,400]
