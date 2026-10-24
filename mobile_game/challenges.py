"""Persistent mundane challenges under notion-manual-v2, section 1.

The storyteller judges fictional uncertainty and declares stakes. The engine owns
ratings, dice, bands, costs, one resolution per situation, and the three-test cap.
"""
from copy import deepcopy
from .world_schema import ID, TEXT, NAME, variant, _text, _id

SKILLS={'athletics','stealth','survival','notice','scholarship','persuasion','insight','leadership','composure'}
ATTRIBUTES={'body','grace','wits','will','presence'}
BANDS=('clean','costly','setback')
OUTCOME={'type':'object','properties':{'summary':TEXT,'seconds':{'type':'integer','minimum':10,'maximum':3600},
 'supply_cost':{'type':'integer','minimum':0,'maximum':6},'silver_cost':{'type':'integer','minimum':0,'maximum':100}},
 'required':['summary','seconds','supply_cost','silver_cost'],'additionalProperties':False}
DEFINITION=variant('challenge',{'id':ID,'scene_id':ID,'location':ID,'name':NAME,'goal':TEXT,'method':TEXT,
 'uncertainty':TEXT,'alternative':TEXT,'attribute':{'type':'string','enum':sorted(ATTRIBUTES)},
 'skill':{'type':'string','enum':sorted(SKILLS)},'difficulty':{'type':['integer','null'],'enum':[None,14,18,22]},
 'help_fact':{'type':['string','null']},'obstacle_fact':{'type':['string','null']},
 'outcomes':{'type':'object','properties':{band:OUTCOME for band in BANDS},'required':list(BANDS),'additionalProperties':False}})


def validate_definition(state, record):
 from . import sandbox
 if type(record) is not dict or set(record)!=set(DEFINITION['required']):raise ValueError('Use the exact challenge definition schema.')
 for k in ('id','scene_id','location'):_id(record[k])
 for k in ('name','goal','method','uncertainty','alternative'):_text(record[k],100 if k=='name' else 1000)
 if record['location'] not in sandbox.places(state):raise ValueError('A challenge needs an established place.')
 if type(record['attribute']) is not str or type(record['skill']) is not str or record['attribute'] not in ATTRIBUTES or record['skill'] not in SKILLS:raise ValueError('Use a supported mundane Attribute and Skill. Combat, Medicine and channeling need their own mechanics.')
 difficulty=record['difficulty']
 if difficulty is not None and (type(difficulty) is not int or difficulty not in (14,18,22)):raise ValueError('Use difficulty 14, 18 or 22; null means a safe routine task without dice.')
 facts=state['world']['sandbox'].get('facts',{})
 for k in ('help_fact','obstacle_fact'):
  if record[k] is not None:
   _id(record[k])
   if record[k] not in facts:raise ValueError('Help and obstacles must reference established public facts.')
 if record['help_fact'] is not None and record['help_fact']==record['obstacle_fact']:raise ValueError('The same fact cannot be both help and obstacle.')
 outcomes=record['outcomes']
 if type(outcomes) is not dict or set(outcomes)!=set(BANDS):raise ValueError('Declare every outcome before a test.')
 for outcome in outcomes.values():
  if type(outcome) is not dict or set(outcome)!=set(OUTCOME['required']):raise ValueError('Use an exact outcome summary, duration and costs.')
  _text(outcome['summary'])
  for k,lo,hi in (('seconds',10,3600),('supply_cost',0,6),('silver_cost',0,100)):
   if type(outcome[k]) is not int or not lo<=outcome[k]<=hi:raise ValueError('Invalid outcome duration or resource cost.')
 if difficulty is None:
  if any(outcomes[b]!=outcomes['clean'] for b in BANDS):raise ValueError('A routine task has one certain result, not hidden adverse branches.')
 elif outcomes['costly']==outcomes['clean'] or outcomes['setback']==outcomes['clean']:
  raise ValueError('A test must declare distinct costly and setback consequences. Use routine work when uncertainty is immaterial.')
 signature=(record['scene_id'],record['location'],record['goal'].casefold().strip(),record['method'].casefold().strip())
 for old in state['world']['sandbox'].get('challenges',{}).values():
  if signature==(old['scene_id'],old['location'],old['goal'].casefold().strip(),old['method'].casefold().strip()):
   raise ValueError('This scene already has that challenge. Do not re-roll an unchanged situation under a new ID.')


def check(state, definition):
 attribute,skill=definition['attribute'],definition['skill']
 a,b=state['attributes'][attribute],state['skills'][skill]
 if type(a) is not int or not 0<=a<=3 or type(b) is not int or not 0<=b<=4:raise ValueError('Invalid saved character ratings.')
 modifier=(2 if definition['help_fact'] else 0)-(2 if definition['obstacle_fact'] else 0)
 return {'formula':'2d10 + Attribute + Skill + situational modifier','attribute':attribute,'attribute_rating':a,
  'skill':skill,'skill_rating':b,'modifier':modifier,'difficulty':definition['difficulty'],
  'help_fact':definition['help_fact'],'obstacle_fact':definition['obstacle_fact']}


def available(state, definition):
 from .sandbox import _advance
 box=state['world']['sandbox']
 caster=state['channeling']
 if caster['embraced'] or caster['held_weaves'] or caster['pending_cast']:return False
 if box['location_id']!=definition['location'] or definition['id'] in box.get('challenge_results',{}):return False
 if definition['difficulty'] is not None:
  count=sum(r['requires_roll'] and r['scene_id']==definition['scene_id'] for r in box.get('challenge_results',{}).values())
  if count>=3:return False
 for branch in definition['outcomes'].values():
  if state['resources']['supply']<branch['supply_cost'] or state['resources']['silver']<branch['silver_cost']:return False
  try:_advance(deepcopy(state),branch['seconds'],True)
  except ValueError:return False
 check(state,definition)
 return True


def choices(state):
 from .sandbox import _choice
 out=[]
 for definition in state['world']['sandbox'].get('challenges',{}).values():
  if not available(state,definition):continue
  test=check(state,definition);bonus=test['attribute_rating']+test['skill_rating']+test['modifier']
  if definition['difficulty'] is None:stakes='Routine: no roll. '
  else:
   dc=definition['difficulty'];stakes=f"2d10 + {test['attribute']} {test['attribute_rating']} + {test['skill']} {test['skill_rating']} + modifier {test['modifier']} = bonus {bonus:+d}. Difficulty {dc}. Clean {dc}+, costly {dc-3}–{dc-1}, setback {dc-4} or below. Possible total {2+bonus}–{20+bonus}. "
  stakes+=' '.join(f"{b}: {v['summary']} ({v['seconds']} seconds, {v['supply_cost']} Supply, {v['silver_cost']} silver)." for b,v in definition['outcomes'].items() if b=='clean' or definition['difficulty'] is not None)
  c=_choice({'op':'attempt','target':definition['id']},definition['name'],definition['goal']+' Method: '+definition['method']+' Alternative: '+definition['alternative'],stakes)
  c.update(requires_roll=definition['difficulty'] is not None,check=test,outcomes=deepcopy(definition['outcomes']))
  out.append(c)
 return out


def resolve(state, target, dice=None):
 from .sandbox import _advance,validate
 definition=state['world']['sandbox'].get('challenges',{}).get(target)
 if definition is None or not available(state,definition):raise ValueError('Challenge unavailable or already resolved. Do not repeat unchanged tests.')
 test=check(state,definition);roll=None
 if definition['difficulty'] is None:
  if dice not in (None,[]):raise ValueError('Routine actions do not use dice.')
  band='clean';outcome='routine'
 else:
  if type(dice) is not list or len(dice)!=2 or any(type(d) is not int or not 1<=d<=10 for d in dice):raise ValueError('A committed test requires exactly two server d10 results.')
  total=sum(dice)+test['attribute_rating']+test['skill_rating']+test['modifier']
  gap=test['difficulty']-total;band='clean' if gap<=0 else 'costly' if gap<=3 else 'setback';outcome=band
  roll={**test,'dice':list(dice),'total':total,'outcome':band}
 branch=definition['outcomes'][band];out=deepcopy(state)
 out['resources']['supply']-=branch['supply_cost'];out['resources']['silver']-=branch['silver_cost']
 _advance(out,branch['seconds'],True)
 out['world']['sandbox'].setdefault('challenge_results',{})[target]={'scene_id':definition['scene_id'],'requires_roll':roll is not None,
  'outcome':outcome,'summary':branch['summary'],'goal':definition['goal'],'roll':roll,'elapsed_seconds':branch['seconds']}
 validate(out)
 from . import npc_activity
 return {'state':out,'narration':branch['summary']+npc_activity.narration(state,out),'roll':roll,'elapsed_seconds':branch['seconds']}


def preview_outcomes(state, outcomes):
 from .sandbox import _advance
 from . import npc_activity
 results={}
 for band,branch in outcomes.items():
  probe=deepcopy(state)
  _advance(probe,branch['seconds'],True)
  results[band]={**deepcopy(branch),'npc_events':npc_activity.new_events(state,probe)}
 return results
