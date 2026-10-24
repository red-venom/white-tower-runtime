"""Connected play must preserve character continuity and actual scene endings."""
from copy import deepcopy
import pytest
from mobile_game import adventure as a, garden, rules


def step(s, action):
    before=deepcopy(s);r=rules.resolve(s, action)
    assert s==before
    assert r['state']['clock']['fictional_seconds']-s['clock']['fictional_seconds']==r['elapsed_seconds']
    assert r['roll'] is None
    return r['state']


def completed():
    s=step(a.initial_state(),'look_gallery');s=step(s,'air_letter');s=step(s,'study_block')
    s['extension']={'must_survive':[1,True,None]}
    return s


def test_transition_preserves_entire_character_and_original_completed_chapter():
    old=completed()
    # Release any active source before the explicitly disclosed time skip.
    if old['channeling']['embraced']:old=step(old,'release_source')
    new=step(old,'next_chapter')
    for key in old.keys()-{'world','clock'}:assert new[key]==old[key]
    assert {k:v for k,v in new['world']['episode'].items() if k!=garden.KEY}==old['world']['episode']
    assert new['world']['known_facts']==old['world']['known_facts']
    assert new['world']['npcs'][:2]==old['world']['npcs']
    assert new['clock']['fictional_seconds']==54000
    assert new['clock']['day_activity_seconds']==old['clock']['day_activity_seconds']
    assert a.view(new)['chapter']['number']==2 and not a.view(new)['completed']
    assert a.companion(new)['chapters'][0]['completed']
    assert not any(c['id'] in {'next_chapter','look_gallery','air_letter','study_block'} for c in a.choices(new))
    with pytest.raises(ValueError):step(new,'next_chapter')


@pytest.mark.parametrize('mutation',[
    lambda s:s['channeling'].update(embraced=True),
    lambda s:s['channeling'].update(held_weaves=[{'id':'preserve','load':1}]),
    lambda s:s['channeling'].update(pending_cast={'id':'preserve'}),
])
def test_time_skip_does_not_silently_expire_active_channeling(mutation):
    s=step(a.initial_state(),'decline_letter');mutation(s)
    assert not garden.can_start(s)
    assert 'next_chapter' not in {c['id'] for c in a.choices(s)}
    with pytest.raises(ValueError):step(s,'next_chapter')


def test_refusal_can_continue_and_time_never_moves_backwards():
    s=step(a.initial_state(),'decline_letter');s['clock']['fictional_seconds']=16*3600
    s['clock']['day_activity_seconds']=28800
    out=step(s,'next_chapter')
    assert out['clock']['fictional_seconds']==86400+54000
    assert out['clock']['day_activity_seconds']==0
    assert out['resources']==s['resources']
    assert 'no complaint' in a.view(out)['story']
    assert out['world']['episode']['result']=='declined'


@pytest.mark.parametrize('route',['garden_private','garden_welcome','garden_nera','garden_alone'])
@pytest.mark.parametrize('listen',[False,True])
def test_each_social_route_finishes_without_dice_penalty_or_repeat_prompt(route,listen):
    s=step(step(a.initial_state(),'decline_letter'),'next_chapter')
    initial=deepcopy(s)
    if listen:
        s=step(s,'garden_listen');assert s['clock']['fictional_seconds']==54120
        assert 'garden_listen' not in {c['id'] for c in a.choices(s)}
    s=step(s,route)
    assert a.view(s)['completed']
    assert s['world']['episode']['result']=='declined'
    for key in initial.keys()-{'clock','world'}:assert s[key]==initial[key]
    with pytest.raises(ValueError):step(s,route)
    if route!='garden_alone':
        assert {c['id'] for c in a.choices(s)}=={'garden_finish'}
        s=step(s,'garden_finish')
    assert s['clock']['fictional_seconds']==55800 and a.choices(s)==[]
    assert all(not n['present'] for n in a.companion(s)['people'])
    assert 'free interval has ended' in a.view(s)['story'].lower() or route=='garden_alone'


def test_questions_and_negated_or_compound_commands_preserve_agency():
    s=step(step(a.initial_state(),'decline_letter'),'next_chapter');before=deepcopy(s)
    for prompt in ['What can I do?','Can I cast Air?','Maybe invite Nera','Do not invite Nera','Invite Nera and read the letter','I promise to meet tomorrow']:
        assert a.interpret(s,prompt)['kind']!='proposal'
    assert a.interpret(s,'Hear them out')['choice_id']=='garden_listen'
    assert a.interpret(s,'Invite Nera')['choice_id']=='garden_welcome'
    assert s==before
    assert 'no casting action' in a.interpret(s,'Can I cast Air?')['message']
    assert not next(n for n in a.companion(s)['people'] if n['name']=='Maerin Sedai')['present']


def test_completion_question_lists_only_actual_available_activities():
    s=step(a.initial_state(),'decline_letter');s['clock']['fictional_seconds']=40000
    reply=a.interpret(s,'What next?')['message']
    assert 'Continue with the same character' in reply
    assert 'Study until' not in reply
