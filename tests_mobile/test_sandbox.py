from copy import deepcopy
import pytest
from mobile_game import rules, sandbox as s


def step(state,command):
 before=deepcopy(state);choice=s.command_choice(state,command);result=rules.resolve(state,choice['id'])
 assert state==before and result['roll'] is None
 assert result['elapsed_seconds']==result['state']['clock']['fictional_seconds']-state['clock']['fictional_seconds']
 return result['state']


def test_persistent_world_operations_without_scripted_chapters():
 state=s.initial_state();state['extension']={'preserve':True}
 state=step(state,{'op':'cast','weave':'W02','target':'wooden_token'})
 assert state['resources']['strain']==1 and 'Wooden practice token' in state['resources']['inventory']
 for cmd in [{'op':'travel','target':'garden'},{'op':'drop','target':'wooden_token'}, {'op':'travel','target':'common'}, {'op':'travel','target':'garden'}]:state=step(state,cmd)
 assert state['world']['sandbox']['objects']['wooden_token']['location']=='garden'
 assert 'Wooden practice token' not in state['resources']['inventory']
 state=step(state,{'op':'take','target':'wooden_token'})
 assert state['resources']['inventory'].count('Wooden practice token')==1
 assert state['extension']=={'preserve':True}
 assert not s.view(state)['completed'] and state['progression']==s.initial_state()['progression']


@pytest.mark.parametrize('cmd',[
 {'op':'travel','target':'common'}, {'op':'travel','target':'Shayol Ghul'},
 {'op':'take','target':'wooden_token'}, {'op':'take','target':'candle'},
 {'op':'cast','weave':'W02','target':'Maerin'}, {'op':'cast','weave':'Healing','target':'self'},
 {'op':'cast','weave':'W01','target':'cloth','supervised':True},
 {'op':'wait','seconds':99999}, {'op':'set_state','capacity':10}, {'op':'rest','reward':100},
])
def test_unknown_or_forged_commands_do_not_mutate(cmd):
 state=s.initial_state();before=deepcopy(state)
 with pytest.raises(ValueError):s.command_choice(state,cmd)
 assert state==before


def test_casting_uses_world_supervision_and_deadline_not_client_claims():
 state=s.initial_state();state['clock']['fictional_seconds']=39590
 assert not any(c['command']['op']=='cast' for c in s.choices(state))
 state=step(state,{'op':'wait'})
 assert not s.context(state)['supervised_practice_available']
 state=step(state,{'op':'travel','target':'library'})
 assert not any(c['command']['op']=='cast' for c in s.choices(state))


def test_recovery_cooldown_and_no_automatic_time_recovery():
 state=s.initial_state();state['resources']['strain']=4
 state=step(state,{'op':'wait'});assert state['resources']['strain']==4
 state=step(state,{'op':'rest'});assert state['resources']['strain']==2
 with pytest.raises(ValueError):s.command_choice(state,{'op':'rest'})
 for _ in range(5):state=step(state,{'op':'wait'})
 state=step(state,{'op':'rest'});assert state['resources']['strain']==0


def test_objects_and_original_state_survive_return_and_no_recast_charge():
 state=step(s.initial_state(),{'op':'cast','weave':'W01','target':'candle'})
 assert state['world']['sandbox']['objects']['candle']['lit']
 with pytest.raises(ValueError):s.command_choice(state,{'op':'cast','weave':'W01','target':'candle'})
 for cmd in [{'op':'travel','target':'garden'}, {'op':'travel','target':'gallery'}]:state=step(state,cmd)
 assert state['world']['sandbox']['objects']['candle']['lit'] and state['resources']['strain']==1
 state=step(state,{'op':'extinguish','target':'candle'});assert not state['world']['sandbox']['objects']['candle']['lit']


def test_public_context_excludes_remote_and_private_fields():
 state=s.initial_state();state['secret']='PRIVATE';state['attributes']['secret']='PRIVATE'
 state['world']['sandbox']['objects']['candle']['secret']='PRIVATE'
 state['world']['sandbox']['objects']['cloth']['location']='garden'
 assert 'PRIVATE' not in str(s.context(state))
 assert 'cloth' not in {o['id'] for o in s.context(state)['objects']}


def test_exhausted_day_permits_wait_and_recovery_but_not_active_actions():
 state=s.initial_state();state['clock']['day_activity_seconds']=28800
 assert {c['command']['op'] for c in s.choices(state)}=={'wait'}
 state['clock']['fictional_seconds']=86300
 state=step(state,{'op':'wait'})
 assert state['clock']['day_activity_seconds']==0 and state['clock']['fictional_seconds']==86900


def test_active_workings_are_not_silently_expired_by_wait_or_travel():
 state=s.initial_state();state['channeling']['embraced']=True
 assert {c['id'] for c in s.choices(state)}=={'release'}
 state=step(state,{'op':'release'});assert not state['channeling']['embraced']
