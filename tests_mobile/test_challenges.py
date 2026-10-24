"""Declared stakes, real dice at commit, exact bands and durable outcomes."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from itertools import product
import uuid
import pytest
from mobile_game import sandbox, worldbuilding, challenges
from mobile_game.sandbox_tools import call
from mobile_game.store import Problem
from tests_mobile.test_http import app, start
from tests_mobile.deployed_probe import validate_export


def definition(id='sorting', difficulty=14):
    branches={
        'clean':{'summary':'The sample labels are sorted correctly. The task is finished.','seconds':60,'supply_cost':0,'silver_cost':0},
        'costly':{'summary':'The labels are sorted correctly after replacing a damaged wrapper. The task is finished.','seconds':120,'supply_cost':1,'silver_cost':0},
        'setback':{'summary':'The faded label cannot be read; it is set aside for the clerk, leaving a clear alternative.','seconds':90,'supply_cost':0,'silver_cost':1}}
    if difficulty is None: branches={b:deepcopy(branches['clean']) for b in branches}
    return {'kind':'challenge','id':id,'scene_id':'labels','location':'gallery','name':'Sort sample labels '+id,
        'goal':'Identify the faded label '+id,'method':'Compare the surviving letters with the sample index.',
        'uncertainty':'The label is damaged. A failed comparison requires the clerk to identify it.',
        'alternative':'Leave the uncertain label for the clerk without attempting a check.',
        'attribute':'wits','skill':'scholarship','difficulty':difficulty,'help_fact':None,'obstacle_fact':None,'outcomes':branches}


def prepare(state=None, records=None):
    return worldbuilding.resolve(state or sandbox.initial_state(),{'op':'establish','changes':records or [definition()]})['state']


def test_all_dice_bands_ratings_and_single_modifier_combinations():
    for difficulty, help_, obstacle in product((14,18,22),(False,True),(False,True)):
        d=definition(difficulty=difficulty)
        d.update(help_fact='index' if help_ else None,obstacle_fact='fading' if obstacle else None)
        state=prepare(records=[{'kind':'fact','id':'index','text':'A sample index is available.'},
            {'kind':'fact','id':'fading','text':'The ink is badly faded.'},d])
        state['attributes']['wits']=3;state['skills']['scholarship']=4
        before=deepcopy(state);bonus=7+2*help_-2*obstacle
        choice=sandbox.command_choice(state,{'op':'attempt','target':'sorting'})
        assert choice['check']['modifier']==2*help_-2*obstacle
        assert f'Possible total {2+bonus}–{20+bonus}' in choice['stakes']
        for dice in product(range(1,11),repeat=2):
            result=sandbox.resolve(state,'attempt:sorting',list(dice))
            total=sum(dice)+bonus
            expected='clean' if total>=difficulty else 'costly' if total>=difficulty-3 else 'setback'
            branch=d['outcomes'][expected];after=result['state']
            assert result['roll']['dice']==list(dice) and result['roll']['total']==total
            assert result['roll']['outcome']==expected and result['narration']==branch['summary']
            assert after['resources']['supply']==4-branch['supply_cost']
            assert after['resources']['silver']==6-branch['silver_cost']
            assert after['clock']['fictional_seconds']==32400+branch['seconds']
            assert after['identity']==state['identity'] and after['channeling']==state['channeling']
            assert sandbox.context(after)['challenge_results'][0]['roll']==result['roll']
            assert not any(c['id']=='attempt:sorting' for c in sandbox.choices(after))
            with pytest.raises(ValueError):sandbox.resolve(after,'attempt:sorting',list(dice))
        assert state==before


def test_routine_is_automatic_and_three_test_cap_is_per_scene():
    records=[definition('test_'+str(i)) for i in range(4)]+[definition('routine',None)]
    state=prepare(records=records)
    for i in range(3):state=sandbox.resolve(state,'attempt:test_'+str(i),[10,10])['state']
    assert 'attempt:test_3' not in {c['id'] for c in sandbox.choices(state)}
    routine=sandbox.resolve(state,'attempt:routine')
    assert routine['roll'] is None
    assert routine['state']['world']['sandbox']['challenge_results']['routine']['outcome']=='routine'
    with pytest.raises(ValueError):sandbox.resolve(state,'attempt:routine',[1,1])
    different=definition('other');different['scene_id']='another_scene'
    later=prepare(routine['state'],[different])
    assert 'attempt:other' in {c['id'] for c in sandbox.choices(later)}


@pytest.mark.parametrize('field,value',[
    ('difficulty',True),('difficulty',15),('attribute',[]),('skill','medicine'),('skill','channeling'),
    ('help_fact','missing'),('scene_id',''),('location','missing'),('outcomes',{}),('name','Elin QA'),
])
def test_reject_invalid_definitions_without_mutation(field,value):
    state=sandbox.initial_state();before=deepcopy(state);d=definition();d[field]=value
    with pytest.raises(ValueError):prepare(state,[d])
    assert state==before


def test_no_redefined_stakes_duplicate_situation_or_unaffordable_gamble():
    state=prepare();before=deepcopy(state)
    for d in (definition(),definition('renamed')):
        d['goal']=definition()['goal'];d['method']=definition()['method']
        with pytest.raises(ValueError):prepare(state,[d])
    assert state==before
    state['resources']['supply']=0
    assert not challenges.choices(state) # even a lucky roll cannot fund an unaffordable branch
    state=prepare();state['clock']['day_activity_seconds']=28800-100
    assert not challenges.choices(state) # longest possible branch must fit
    state=prepare();state['channeling']['embraced']=True
    with pytest.raises(ValueError):challenges.resolve(state,'sorting',[10,10])


@pytest.mark.parametrize('dice',[None,[],[0,1],[11,1],[True,1],[1],[1,2,3],(1,2),[1.0,2]])
def test_exact_dice_required(dice):
    with pytest.raises(ValueError):sandbox.resolve(prepare(),'attempt:sorting',dice)


def test_distinct_stakes_and_no_client_supplied_ratings():
    for d in (definition(),definition(difficulty=None)):
        if d['difficulty'] is None:d['outcomes']['setback']['seconds']=99
        else:d['outcomes']['setback']=deepcopy(d['outcomes']['clean'])
        with pytest.raises(ValueError):prepare(records=[d])
    d=definition();d['attribute_rating']=99
    with pytest.raises(ValueError):prepare(records=[d])
    d=definition();d['outcomes']['costly']['silver_cost']=True
    with pytest.raises(ValueError):prepare(records=[d])


def test_postgres_preview_no_dice_rollback_retry_concurrency_and_recovery(app,monkeypatch):
    store=app.extensions['store'];client=app.test_client();_,_,credentials=start(client)
    with store.connect() as db:player=db.execute('SELECT id FROM mobile_players').fetchone()['id']
    packet=call(store,player,'sandbox_create',{'request_id':str(uuid.uuid4())});cid=packet['id']
    args={'campaign_id':cid,'action_id':str(uuid.uuid4()),'expected_revision':0,
        'command':{'op':'establish','changes':[definition()]}}
    preview=call(store,player,'sandbox_preview',args)
    store.act(player,cid,preview['request'])
    packet=store.read(player,cid)
    original_dice=store.dice;rolls=[]
    def dice(*args):
        value=original_dice(*args);rolls.append(value);return value
    monkeypatch.setattr(store,'dice',dice)
    attempt={'campaign_id':cid,'action_id':str(uuid.uuid4()),'expected_revision':1,'command':{'op':'attempt','target':'sorting'}}
    preview=call(store,player,'sandbox_preview',attempt)
    assert not rolls and store.read(player,cid)==packet and not preview['committed']
    assert set(preview['effects']['possible_outcomes'])=={'clean','costly','setback'}
    request=preview['request'];tampered={**request,'choice_hash':'tampered'}
    with pytest.raises(Problem) as exc:store.act(player,cid,tampered)
    assert exc.value.code=='STAKES_CHANGED' and not rolls
    def fault(stage):
        if stage=='after_event_insert':raise RuntimeError('interrupted save')
    with pytest.raises(RuntimeError):store.act(player,cid,request,fault)
    assert store.read(player,cid)==packet
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:store.act(player,cid,request),range(2)))
    saved=next(r for r in results if not r.get('replayed'))
    assert next(r for r in results if r.get('replayed'))=={**saved,'replayed':True}
    assert len(rolls)==2 and rolls[0]==rolls[1] # rollback retry uses original dice; committed duplicate never rolls
    assert saved['revision']==2 and len(saved['sandbox']['challenge_results'])==1
    assert store.act(player,cid,request)=={**saved,'replayed':True} and len(rolls)==2
    export=store.export(player,cid);validate_export(export,saved)
    result=saved['sandbox']['challenge_results'][0]
    assert result['roll']['dice']==rolls[0]
    with pytest.raises(Problem):call(store,player,'sandbox_preview',{**attempt,'action_id':str(uuid.uuid4()),'expected_revision':2})
    fresh=app.test_client()
    assert fresh.post('/api/session/recover',json={'recovery_code':credentials['recovery_code']}).status_code==200
    assert fresh.get('/api/campaigns/'+cid).get_json()=={k:v for k,v in saved.items() if k!='replayed'}
