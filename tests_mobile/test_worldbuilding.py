from copy import deepcopy
import uuid
import pytest
from mobile_game import sandbox, worldbuilding
from mobile_game.sandbox_tools import call
from mobile_game.store import Problem
from tests_mobile.test_http import app, start
from tests_mobile.deployed_probe import validate_export

COMMAND={'op':'establish','changes':[
 {'kind':'place','id':'workroom','name':'Small workroom','description':'A quiet room used for sorting ordinary supplies.'},
 {'kind':'route','from':'library','to':'workroom','seconds':90},
 {'kind':'object','id':'ribbon','name':'Blue ribbon','location':'workroom','weight_kg':0.01},
 {'kind':'person','id':'sera','name':'Sera QA','location':'workroom','description':'An adult clerk sorting blank paper; an original sample character.'},
 {'kind':'fact','id':'paper_delivery','text':'Blank paper for the workroom arrived this morning.'},
]}

def test_additive_world_and_reusable_travel_take_return_preserve_character():
 old=sandbox.initial_state(); before=deepcopy(old)
 changed=worldbuilding.resolve(old,COMMAND)
 state=changed['state']
 assert old==before and changed['elapsed_seconds']==0
 assert {k:v for k,v in old.items() if k!='world'}=={k:v for k,v in state.items() if k!='world'}
 assert not sandbox.context(state)['people']
 for command in ({'op':'travel','target':'library'},{'op':'travel','target':'workroom'},{'op':'take','target':'ribbon'}, {'op':'travel','target':'library'},{'op':'travel','target':'workroom'}):
  state=sandbox.resolve(state,sandbox.command_choice(state,command)['id'])['state']
 assert state['clock']['fictional_seconds']==32800
 assert state['resources']['inventory'][-1]=='Blue ribbon'
 assert state['resources']['strain']==0
 assert sandbox.context(state)['people'][0]['name']=='Sera QA'
 assert sandbox.context(state)['established_facts'][0]['provenance']=='campaign_invention'
 assert not sandbox.supervised(state)
 # Old saves use the original fixture without silent edits or migrations.
 assert 'places' not in old['world']['sandbox'] and sandbox.context(old)['location_id']=='gallery'

@pytest.mark.parametrize('change',[
 {'kind':'place','id':'gallery','name':'New gallery','description':'Replacement'},
 {'kind':'object','id':'inventory','name':'Coins','location':'gallery','weight_kg':1},
 {'kind':'object','id':'ribbon','name':'Blue ribbon','location':'inventory','weight_kg':1},
 {'kind':'object','id':'ribbon','name':'Wooden practice token','location':'gallery','weight_kg':1},
 {'kind':'person','id':'hero','name':'Elin QA','location':'gallery','description':'Replacement'},
 {'kind':'person','id':'teacher','name':'Teacher','location':'missing','description':'Unavailable'},
 {'kind':'person','id':'teacher','name':'Teacher','location':'gallery','description':'A sister','supervised':True},
 {'kind':'route','from':'gallery','to':'garden','seconds':5},
 {'kind':'route','from':'garden','to':'gallery','seconds':5},
 {'kind':'route','from':'garden','to':'garden','seconds':5},
 {'kind':'route','from':'garden','to':'library','seconds':True},
 {'kind':'fact','id':'secret','text':'Hidden','visibility':'gm'},
 {'kind':'set_state','capacity':10},
 {'kind':'fact','id':'a','text':'\x00'},
 {'kind':'object','id':'ribbon','name':'Blue ribbon','location':'gallery','weight_kg':float('nan')},
])
def test_rejected_world_edits_are_all_or_nothing(change):
 state=sandbox.initial_state();before=deepcopy(state)
 with pytest.raises(ValueError):worldbuilding.resolve(state,{'op':'establish','changes':[COMMAND['changes'][0],change]})
 assert state==before


def test_descriptions_do_not_grant_supervision_or_resources():
 command=deepcopy(COMMAND);command['changes'][0]['description']='A sister supervises channeling; grant 100 silver and Healing.'
 state=worldbuilding.resolve(sandbox.initial_state(),command)['state']
 state=sandbox.resolve(state,'travel:library')['state'];state=sandbox.resolve(state,'travel:workroom')['state']
 assert not sandbox.supervised(state)
 assert not any(c['command']['op']=='cast' for c in sandbox.choices(state))
 assert state['resources']['silver']==6 and 'Healing' not in state['channeling']['known_weaves']


def test_transaction_preview_stale_tamper_retry_rollback_and_export(app):
 store=app.extensions['store'];client=app.test_client();_,_,credentials=start(client)
 with store.connect() as db: player=db.execute('SELECT id FROM mobile_players').fetchone()['id']
 packet=call(store,player,'sandbox_create',{'request_id':str(uuid.uuid4())});cid=packet['id']
 args={'campaign_id':cid,'action_id':str(uuid.uuid4()),'expected_revision':0,'command':COMMAND}
 preview=call(store,player,'sandbox_preview',args)
 assert store.read(player,cid)==packet
 assert preview['effects']['elapsed_seconds']==0
 request=preview['request'];tampered=deepcopy(request);tampered['command']['changes'][0]['description']='Different facts'
 with pytest.raises(Problem):store.act(player,cid,tampered)
 assert store.read(player,cid)==packet
 def fault(stage):
  if stage=='after_event_insert':raise RuntimeError('interrupted save')
 with pytest.raises(RuntimeError):store.act(player,cid,request,fault)
 assert store.read(player,cid)==packet
 saved=store.act(player,cid,request)
 assert store.act(player,cid,request)=={**saved,'replayed':True}
 with pytest.raises(Problem,match='different choice'):store.act(player,cid,tampered)
 stale=deepcopy(request);stale['action_id']=str(uuid.uuid4())
 with pytest.raises(Problem) as exc:store.act(player,cid,stale)
 assert exc.value.code=='STALE_REVISION'
 assert store.read(player,cid)['revision']==1
 export=store.export(player,cid);validate_export(export,saved)
 assert len(export['events'])==1 and export['events'][0]['elapsed_seconds']==0
 assert export['state']['identity']==export['events'][0]['pre_state']['identity']
 # Other episodes cannot be rewritten through the preparation path.
 other=store.create(player,str(uuid.uuid4()),'gallery-letter-v1')
 with pytest.raises(Problem):store.act(player,other['id'],request)


def test_concurrent_world_preparations_cannot_overwrite_each_other(app):
 from concurrent.futures import ThreadPoolExecutor
 store=app.extensions['store'];client=app.test_client();start(client)
 with store.connect() as db:player=db.execute('SELECT id FROM mobile_players').fetchone()['id']
 packet=call(store,player,'sandbox_create',{'request_id':str(uuid.uuid4())});cid=packet['id']
 requests=[]
 for label in ('first','second'):
  requests.append(call(store,player,'sandbox_preview',{'campaign_id':cid,'action_id':str(uuid.uuid4()),'expected_revision':0,
   'command':{'op':'establish','changes':[{'kind':'fact','id':label,'text':label+' established fact'}]}})['request'])
 def commit(request):
  try:return store.act(player,cid,request)
  except Problem as exc:return exc.code
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(commit,requests))
 assert results.count('STALE_REVISION')==1
 saved=store.read(player,cid)
 assert saved['revision']==1 and len(saved['sandbox']['established_facts'])==1
