from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from mobile_game import sandbox, worldbuilding, npc_activity, world_commands, challenges
from mobile_game.sandbox_tools import call
from mobile_game.store import Problem
from tests_mobile.test_http import app, start
from tests_mobile.deployed_probe import validate_export
from tests_mobile.test_challenges import definition

PREP={'op':'establish','changes':[
 {'kind':'person','id':'courier','name':'Courier QA','location':'gallery','description':'An adult carrying out an ordinary public errand.'},
 {'kind':'person','id':'other','name':'Other QA','location':'gallery','description':'An adult sample NPC.'},
 {'kind':'object','id':'parcel','name':'Paper parcel','location':'gallery','weight_kg':0.5}]}
PLAN={'op':'npc_plan','id':'delivery','actor':'courier','purpose':'Deliver the sample parcel to the reading room.',
 'steps':[{'op':'take','target':'parcel'},{'op':'move','target':'library'},{'op':'drop','target':'parcel'}]}


def initial():return worldbuilding.resolve(sandbox.initial_state(),PREP)['state']
def scheduled():return npc_activity.resolve(initial(),PLAN)['state']
def advance(s,seconds):
 out=deepcopy(s);sandbox._advance(out,seconds);return out


def test_clock_custody_partial_arrival_and_completion_preserve_character():
 state=initial();before=deepcopy(state);out=npc_activity.resolve(state,PLAN)
 assert state==before and out['elapsed_seconds']==0
 state=out['state'];box=state['world']['sandbox']
 assert box['npc_plans']['delivery']['steps'][-1]['due_at']==32540
 assert npc_activity.activity(state,'courier')=={'op':'take','target':'parcel','from':'gallery','due_at':32410,'due_time':'Day 1 · 09:00:10','stopping':False}
 state=advance(state,9);assert state['world']['sandbox']['objects']['parcel']['location']=='gallery'
 state=advance(state,1);assert state['world']['sandbox']['objects']['parcel']['location']=='person:courier'
 assert 'take:parcel' not in {c['id'] for c in sandbox.choices(state)}
 assert sandbox.context(state)['people'][0]['carrying']==[{'id':'parcel','name':'Paper parcel'}]
 assert npc_activity.activity(state,'courier')['op']=='move'
 state=advance(state,119);assert state['world']['sandbox']['people']['courier']['location']=='gallery'
 state=advance(state,1);assert state['world']['sandbox']['people']['courier']['location']=='library'
 state=advance(state,10);box=state['world']['sandbox']
 assert box['objects']['parcel']['location']=='library' and box['npc_plans']['delivery']['status']=='completed'
 assert [r['at'] for r in npc_activity.events(state)]==[32410,32530,32540]
 assert state['clock']['fictional_seconds']==32540 and state['clock']['day_activity_seconds']==before['clock']['day_activity_seconds']
 for k in ('identity','attributes','skills','resources','channeling','progression'):assert state[k]==before[k]
 assert npc_activity.activity(state,'courier') is None
 # Reading and passing real wall time cannot advance a fictional plan.
 unchanged=deepcopy(state);sandbox.context(state);sandbox.choices(state);assert state==unchanged


def test_delivery_and_player_action_share_time_and_complete_without_extra_gm_turns():
 state=scheduled();result=sandbox.resolve(state,'wait');box=result['state']['world']['sandbox']
 assert result['elapsed_seconds']==600 and result['state']['clock']['fictional_seconds']==33000
 assert box['npc_plans']['delivery']['status']=='completed' and len(box['npc_plans']['delivery']['results'])==3
 assert 'Courier QA put down Paper parcel.' in result['narration']
 state=sandbox.resolve(result['state'],'travel:library')['state']
 state=sandbox.resolve(state,'take:parcel')['state']
 assert state['resources']['inventory'].count('Paper parcel')==1
 assert state['world']['sandbox']['objects']['parcel']['location']=='inventory'
 assert len(npc_activity.events(state))==3


def test_player_interference_stops_plan_without_taking_player_belongings():
 state=scheduled();result=sandbox.resolve(state,'take:parcel');box=result['state']['world']['sandbox']
 assert box['objects']['parcel']['location']=='inventory' and box['npc_plans']['delivery']['status']=='blocked'
 assert box['people']['courier']['location']=='gallery'
 assert result['elapsed_seconds']==10 and len(box['npc_plans']['delivery']['results'])==1
 later=advance(result['state'],3600)
 assert later['world']['sandbox']==box
 with pytest.raises(ValueError):npc_activity.resolve(later,{**PLAN,'id':'steal'})


def test_cancel_finishes_current_step_without_teleport_or_reversing_custody():
 state=advance(scheduled(),30) # courier is between rooms with the parcel
 stopped=npc_activity.resolve(state,{'op':'cancel_npc_plan','target':'delivery'})
 assert stopped['elapsed_seconds']==0
 state=advance(stopped['state'],100);box=state['world']['sandbox']
 assert box['npc_plans']['delivery']['status']=='cancelled' and box['npc_plans']['delivery']['cursor']==2
 assert box['people']['courier']['location']=='library' and box['objects']['parcel']['location']=='person:courier'
 assert advance(state,600)['world']['sandbox']==box
 with pytest.raises(ValueError):npc_activity.resolve(state,{'op':'cancel_npc_plan','target':'delivery'})
 state=npc_activity.resolve(state,{'op':'npc_plan','id':'put_down','actor':'courier','purpose':'Put down the carried parcel.','steps':[{'op':'drop','target':'parcel'}]})['state']
 assert advance(state,10)['world']['sandbox']['objects']['parcel']['location']=='library'


@pytest.mark.parametrize('patch',[
 {'actor':'elin_qa'}, {'actor':'unknown'}, {'id':'bad id'}, {'purpose':''}, {'steps':[]},
 {'steps':[{'op':'move','target':'common'}]}, {'steps':[{'op':'take','target':'wooden_token'}]},
 {'steps':[{'op':'take','target':'candle'}]}, {'steps':[{'op':'drop','target':'parcel'}]},
 {'steps':[{'op':'attack','target':'elin_qa'}]}, {'steps':[{'op':'move','target':'library','seconds':0}]},
 {'steps':[{'op':'take','target':'missing'}]}, {'steps':[{'op':'take','target':'parcel'}]*9},
 {'seconds':0}, {'grant_silver':100},
])
def test_invalid_plans_are_atomic(patch):
 state=initial();before=deepcopy(state)
 with pytest.raises(ValueError):npc_activity.resolve(state,{**PLAN,**patch})
 assert state==before


def test_no_duplicate_active_plan_contested_object_overweight_load_or_general_patch():
 state=scheduled()
 with pytest.raises(ValueError):npc_activity.resolve(state,{**PLAN,'id':'second'})
 with pytest.raises(ValueError):npc_activity.resolve(state,{**PLAN,'id':'second','actor':'other'})
 finished=advance(state,600)
 with pytest.raises(ValueError):npc_activity.resolve(finished,PLAN)
 for bad in ({'op':'attempt','target':'x'},{'op':[]},{'op':'set_state','silver':100}):
  with pytest.raises(ValueError):world_commands.resolve(state,bad)
 state=initial();state['world']['sandbox']['objects']['cloth']['weight_kg']=5
 with pytest.raises(ValueError):npc_activity.resolve(state,{**PLAN,'steps':[{'op':'take','target':'cloth'},{'op':'take','target':'parcel'}]})


def test_different_npc_plans_settle_in_timestamp_order_and_cross_midnight():
 state=initial();state['clock']['fictional_seconds']=86395
 first={**PLAN,'steps':[{'op':'take','target':'parcel'}]}
 second={**PLAN,'id':'walk','actor':'other','steps':[{'op':'move','target':'library'}]}
 state=npc_activity.resolve(npc_activity.resolve(state,first)['state'],second)['state']
 state=advance(state,120)
 assert state['clock']['fictional_seconds']==86515 and state['clock']['day_activity_seconds']==0
 assert [r['at'] for r in npc_activity.events(state)]==[86405,86515]
 assert {p['status'] for p in state['world']['sandbox']['npc_plans'].values()}=={'completed'}


def test_uncertain_action_previews_branch_events_without_dice_or_mutation():
 state=scheduled();state=worldbuilding.resolve(state,{'op':'establish','changes':[definition()]})['state'];before=deepcopy(state)
 previews=challenges.preview_outcomes(state,definition()['outcomes'])
 assert state==before and all(len(b['npc_events'])==1 for b in previews.values())
 result=sandbox.resolve(state,'attempt:sorting',[10,10])
 assert result['state']['clock']['fictional_seconds']==32460
 assert result['state']['world']['sandbox']['objects']['parcel']['location']=='person:courier'
 assert result['narration'].endswith('Courier QA picked up Paper parcel.')


def test_postgres_schedule_and_completion_rollback_retry_race_export_recovery(app):
 store=app.extensions['store'];client=app.test_client();_,_,credentials=start(client)
 with store.connect() as db:player=db.execute('SELECT id FROM mobile_players').fetchone()['id']
 packet=call(store,player,'sandbox_create',{'request_id':str(uuid.uuid4())});cid=packet['id']
 def preview(command,revision):return call(store,player,'sandbox_preview',{'campaign_id':cid,'action_id':str(uuid.uuid4()),'expected_revision':revision,'command':command})
 store.act(player,cid,preview(PREP,0)['request']);before=store.read(player,cid)
 planned=preview(PLAN,1);assert store.read(player,cid)==before
 assert planned['effects']['elapsed_seconds']==0 and planned['effects']['npc_plans'][0]['status']=='pending'
 def fault(stage):
  if stage=='after_event_insert':raise RuntimeError('interrupted save')
 with pytest.raises(RuntimeError):store.act(player,cid,planned['request'],fault)
 assert store.read(player,cid)==before
 request=planned['request']
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:store.act(player,cid,request),range(2)))
 assert sum(bool(r.get('replayed')) for r in results)==1
 before=store.read(player,cid)
 waiting=preview({'op':'wait'},2)
 assert len(waiting['effects']['npc_events'])==3 and store.read(player,cid)==before
 with pytest.raises(RuntimeError):store.act(player,cid,waiting['request'],fault)
 assert store.read(player,cid)==before
 saved=store.act(player,cid,waiting['request']);assert store.act(player,cid,waiting['request'])=={**saved,'replayed':True}
 assert saved['revision']==3 and len(saved['sandbox']['npc_events'])==3
 exported=store.export(player,cid);validate_export(exported,saved)
 assert exported['events'][2]['elapsed_seconds']==600
 assert exported['state']['resources']==exported['events'][0]['pre_state']['resources']
 fresh=app.test_client();assert fresh.post('/api/session/recover',json={'recovery_code':credentials['recovery_code']}).status_code==200
 assert fresh.get('/api/campaigns/'+cid).get_json()=={k:v for k,v in saved.items() if k!='replayed'}
 # Another episode cannot receive an NPC plan through a supplied command.
 other=store.create(player,str(uuid.uuid4()),'gallery-letter-v1')
 with pytest.raises(Problem):store.act(player,other['id'],{**request,'expected_revision':0})


def test_cancel_command_round_trips_through_atomic_tool_transaction(app):
 store=app.extensions['store'];client=app.test_client();start(client)
 with store.connect() as db:player=db.execute('SELECT id FROM mobile_players').fetchone()['id']
 packet=call(store,player,'sandbox_create',{'request_id':str(uuid.uuid4())});cid=packet['id']
 for command in (PREP,PLAN,{'op':'take','target':'cloth'},{'op':'cancel_npc_plan','target':'delivery'},{'op':'wait'}):
  preview=call(store,player,'sandbox_preview',{'campaign_id':cid,'action_id':str(uuid.uuid4()),'expected_revision':packet['revision'],'command':command})
  if command['op']=='cancel_npc_plan':assert len(preview['request']['choice_id'])==80
  packet=call(store,player,'sandbox_commit',{'campaign_id':cid,'request':preview['request']})
  assert call(store,player,'sandbox_commit',{'campaign_id':cid,'request':preview['request']})=={**packet,'replayed':True}
 assert packet['revision']==5 and packet['state']['fictional_seconds']==33010
 assert packet['sandbox']['npc_plans'][0]['status']=='cancelled'
 exported=store.export(player,cid);validate_export(exported,packet)
 assert exported['state']['world']['sandbox']['objects']['parcel']['location']=='person:courier'
 assert exported['state']['world']['sandbox']['people']['courier']['location']=='library'


def test_wait_for_errand_stops_at_completion_cancellation_or_failed_step():
 state=scheduled();before=deepcopy(state)
 assert npc_activity.finish_times(state)=={'delivery':32540} and state==before
 result=sandbox.resolve(state,'wait_for_npc:delivery')
 assert result['elapsed_seconds']==140 and result['state']['clock']['fictional_seconds']==32540
 assert result['state']['clock']['day_activity_seconds']==state['clock']['day_activity_seconds']
 assert result['state']['resources']==state['resources']
 assert 'wait_for_npc:delivery' not in {c['id'] for c in sandbox.choices(result['state'])}
 stopped=npc_activity.resolve(state,{'op':'cancel_npc_plan','target':'delivery'})['state']
 assert sandbox.resolve(stopped,'wait_for_npc:delivery')['elapsed_seconds']==10
 # A reachable future pickup can become invalid before its step starts.
 plan={**PLAN,'steps':[{'op':'move','target':'library'},{'op':'take','target':'parcel'},{'op':'drop','target':'parcel'}]}
 state=initial();state['world']['sandbox']['objects']['parcel']['location']='library'
 state=npc_activity.resolve(state,plan)['state']
 state['world']['sandbox']['objects']['parcel']['location']='inventory'
 state['resources']['inventory'].append('Paper parcel')
 result=sandbox.resolve(state,'wait_for_npc:delivery')
 assert result['elapsed_seconds']==130 # stops on failed pickup; does not charge the later drop
 assert result['state']['world']['sandbox']['npc_plans']['delivery']['status']=='blocked'
 assert result['state']['resources']['inventory'].count('Paper parcel')==1


def test_clock_labels_and_remote_custody_are_authoritative_public_projection():
 state=scheduled();state=sandbox.resolve(state,'wait_for_npc:delivery')['state']
 context=sandbox.context(state)
 assert context['fictional_time']=={'seconds':32540,'label':'Day 1 · 09:02:20'}
 assert context['npc_events'][1]['time']=='Day 1 · 09:02:10'
 assert next(o for o in context['object_custody'] if o['id']=='parcel')=={'id':'parcel','name':'Paper parcel','holder':'library','place_id':'library','carried_by':None}
 assert not any(o['id']=='parcel' for o in context['objects'])
 for value,label in ((32580,'Day 1 · 09:03:00'),(86399,'Day 1 · 23:59:59'),(86400,'Day 2 · 00:00:00')):
  assert npc_activity.clock_label(value)==label
