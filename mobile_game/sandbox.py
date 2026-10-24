"""Story-independent disposable world. Narrative is not an authority to mutate it."""
from copy import deepcopy
from .channeling import WEAVES, safe_cast
from . import challenges, npc_activity

EPISODE_ID='tower-sandbox-v1'
PLACES={
 'gallery':{'name':'Practice gallery','exits':{'library':120,'garden':180},'description':'A practice table, a candle and a high shelf. Supervised practice is available here from 09:00 to 11:00 each day.'},
 'library':{'name':'Reading room','exits':{'gallery':120,'common':60},'description':'A quiet reading room. No practice supervisor is present.'},
 'garden':{'name':'Garden terrace','exits':{'gallery':180,'common':120},'description':'A sheltered terrace with benches. No assigned task or story outcome is attached to this place.'},
 'common':{'name':'Novices’ common room','exits':{'library':60,'garden':120},'description':'A quiet room where you can pause between activities.'},
}


def initial_state():
 from . import rules
 s=rules.initial_state()
 s['world'].update(location=PLACES['gallery']['name'],scene='Open sandbox',known_facts=[],npcs=[],commitments=[],due_events=[])
 s['world']['episode']={'id':EPISODE_ID,'completed':False}
 s['world']['sandbox']={'location_id':'gallery','objects':{
   'candle':{'name':'Practice candle','location':'gallery','portable':False,'weight_kg':.2,'elevated':False,'lit':False,'dry_fuel':True},
   'wooden_token':{'name':'Wooden practice token','location':'gallery','portable':True,'weight_kg':.1,'elevated':True,'lit':False,'dry_fuel':False},
   'cloth':{'name':'Practice cloth','location':'gallery','portable':True,'weight_kg':.05,'elevated':False,'lit':False,'dry_fuel':False},
 },'last_cast':None}
 return s


def places(s):
 return s['world']['sandbox'].get('places',PLACES)


def validate(s):
 if s.get('disposable') is not True or s.get('rules_edition')!='notion-manual-v2' or s['world']['episode']['id']!=EPISODE_ID:
  raise ValueError('Only the disposable sandbox is supported.')
 box=s['world']['sandbox'];clock=s['clock'];locations=places(s)
 if box['location_id'] not in locations:raise ValueError('Unknown location.')
 for person in box.get('people',{}).values():
  if person['location'] not in locations:raise ValueError('Invalid NPC location.')
 if any(type(clock[k]) is not int or not 0<=clock[k]<=2**53-1 for k in ('fictional_seconds','day_activity_seconds')) or clock['day_activity_seconds']>28800:
  raise ValueError('Invalid clock.')
 c=s['channeling'];r=s['resources']
 for value,low,high in ((c['current_capacity'],1,10),(c['control'],1,4),(r['strain'],0,2*c['current_capacity']),(r['vitality'],0,r['max_vitality']),(r['wounds'],0,3)):
  if type(value) is not int or not low<=value<=high:raise ValueError('Invalid character boundary.')
 for obj in box['objects'].values():
  if obj['location'] not in (*locations,'inventory',*(npc_activity.holder(k) for k in box.get('people',{}))):raise ValueError('Invalid object location.')


def supervised(s,seconds=0):
 t=s['clock']['fictional_seconds']%86400
 return s['world']['sandbox']['location_id']=='gallery' and 32400<=t and t+seconds<=39600 and t<39600


def _advance(s,seconds,active=False):
 start=s['clock']['fictional_seconds'];first=min(seconds,86400-start%86400)
 if active and s['clock']['day_activity_seconds']+first>28800:raise ValueError('The daily activity allowance is exhausted. Rest or wait instead.')
 s['clock']['fictional_seconds']+=seconds
 if start//86400!=s['clock']['fictional_seconds']//86400:
  s['clock']['day_activity_seconds']=s['clock']['fictional_seconds']%86400 if active else 0
 elif active:s['clock']['day_activity_seconds']+=seconds
 npc_activity.settle(s,s['clock']['fictional_seconds'])


def _choice(command,label,description,stakes):
 id=':'.join(str(command[k]) for k in ('op','weave','target') if k in command)
 return {'id':id,'label':label,'description':description,'stakes':stakes,'requires_roll':False,'command':command}


def choices(s):
 validate(s);box=s['world']['sandbox'];loc=box['location_id'];locations=places(s);out=[];clock=s['clock'];caster=s['channeling']
 if caster['embraced'] or caster['held_weaves'] or caster['pending_cast']:
  return [_choice({'op':'release'},'Release the Source','End active channeling before other sandbox activity.','No time or refund of previously spent Strain.')]
 def add(cmd,label,description,seconds,active=False,cost='No roll or resource cost.'):
  probe=deepcopy(s)
  try:_advance(probe,seconds,active)
  except ValueError:return
  out.append(_choice(cmd,label,description,f'{seconds} seconds. {cost}'))
 for target,seconds in locations[loc]['exits'].items():
  add({'op':'travel','target':target},'Go to '+locations[target]['name'],'Follow an established route. The sandbox keeps your belongings and character.',seconds,True)
 add({'op':'wait'},'Let ten minutes pass','Advance the clock without inventing an event or recovery.',600)
 if s['resources']['strain'] or s['resources']['vitality']<s['resources']['max_vitality']:
  if clock['last_break_end'] is None or clock['fictional_seconds']+600-clock['last_break_end']>=3600:
   add({'op':'rest'},'Take a recovery break','Rest safely. Restore up to 2 Vitality and remove up to 2 Strain; no Wound healing.',600,cost='No roll. Recovery cooldown applies.')
 for id,obj in box['objects'].items():
  if obj['location']=='inventory':
   add({'op':'drop','target':id},'Put down '+obj['name'],'Place the carried object here.',10,True);continue
  if obj['location']!=loc:continue
  if obj['portable'] and not obj['elevated']:
   add({'op':'take','target':id},'Pick up '+obj['name'],'Take the reachable object.',10,True)
  if obj['lit']:
   add({'op':'extinguish','target':id},'Snuff the candle','Use the snuffer on the practice table.',10,True)
  for weave in WEAVES:
   eligible=(weave=='W01' and obj['dry_fuel'] and not obj['lit']) or (weave=='W02' and obj['portable'])
   if not eligible:continue
   try:
    _,receipt=safe_cast(s,weave,supervised=supervised(s),range_paces=4,weight_kg=obj['weight_kg'],dry_fuel=obj['dry_fuel'])
    if not supervised(s,receipt['elapsed_seconds']):continue
   except ValueError:continue
   effect='Light the practice candle.' if weave=='W01' else 'Bring the practice object into your hand.'
   add({'op':'cast','weave':weave,'target':id},WEAVES[weave]['name']+': '+obj['name'],effect+' The supervisor, target and limits come from saved world state.',receipt['elapsed_seconds'],True,'1 Strain. No roll; the working is released after use.')
 out.extend(challenges.choices(s))
 return out


def command_choice(s,command):
 if type(command) is not dict:raise ValueError('Supply a structured command.')
 from . import world_commands
 if type(command.get('op')) is str and command['op'] in world_commands.OPS:return world_commands.choice(s,command)
 for c in choices(s):
  if c['command']==command:return c
 raise ValueError('Unsupported or unavailable command. Read the current world and available actions; do not substitute a different action.')


def resolve(s,choice_id,dice=None):
 available={c['id']:c for c in choices(s)}
 if choice_id not in available:raise ValueError('Action is unavailable in this world state.')
 c=available[choice_id]['command'];op=c['op']
 if op=='attempt':return challenges.resolve(s,c['target'],dice)
 if dice not in (None,[]):raise ValueError('These sandbox operations do not require dice.')
 out=deepcopy(s);box=out['world']['sandbox'];seconds=10;receipt=None
 if op=='travel':
  locations=places(out);seconds=locations[box['location_id']]['exits'][c['target']];box['location_id']=c['target'];out['world']['location']=locations[c['target']]['name']
  text='Arrived at '+out['world']['location']+'.'
 elif op=='wait':seconds=600;text='Ten minutes passed. No story event or recovery was inferred.'
 elif op=='rest':
  seconds=600;out['resources']['strain']=max(0,out['resources']['strain']-2);out['resources']['vitality']=min(out['resources']['max_vitality'],out['resources']['vitality']+2)
  out['clock']['last_break_end']=out['clock']['fictional_seconds']+600;text='Recovery break completed. Wounds are unchanged.'
 elif op=='release':
  seconds=0;out['channeling'].update(embraced=False,held_weaves=[],pending_cast=None);text='Active channeling released. Spent Strain is unchanged.'
 else:
  obj=box['objects'][c['target']]
  if op=='cast':
   out,receipt=safe_cast(out,c['weave'],supervised=supervised(out),range_paces=4,weight_kg=obj['weight_kg'],dry_fuel=obj['dry_fuel'])
   box=out['world']['sandbox'];obj=box['objects'][c['target']];box['last_cast']=receipt;seconds=receipt['elapsed_seconds']
   if c['weave']=='W01':obj['lit']=True;text='The practice candle is lit.'
   else:obj['location']='inventory';obj['elevated']=False;out['resources']['inventory'].append(obj['name']);text='Air Hand brought '+obj['name']+' into your hand.'
  elif op=='take':obj['location']='inventory';out['resources']['inventory'].append(obj['name']);text='Picked up '+obj['name']+'.'
  elif op=='drop':obj['location']=box['location_id'];obj['elevated']=False;out['resources']['inventory'].remove(obj['name']);text='Put down '+obj['name']+' here.'
  else:obj['lit']=False;text='The practice candle is extinguished.'
 _advance(out,seconds,op not in ('wait','rest','release'));validate(out)
 return {'state':out,'narration':text+npc_activity.narration(s,out),'roll':None,'elapsed_seconds':seconds}


def context(s):
 validate(s);box=s['world']['sandbox'];loc=box['location_id'];locations=places(s)
 fields=('name','location','portable','weight_kg','elevated','lit','dry_fuel')
 return {'schema':'white-tower-sandbox-context-v1','location_id':loc,'location':locations[loc]['name'],
  'description':locations[loc]['description'],'supervised_practice_available':supervised(s),
  'exits':[{'target':k,'name':locations[k]['name'],'seconds':v} for k,v in locations[loc]['exits'].items()],
  'objects':[{'id':id,**{k:deepcopy(o[k]) for k in fields},'provenance':o.get('provenance','disposable_fixture')} for id,o in box['objects'].items() if o['location'] in (loc,'inventory')],
  'known_places':[{'id':k,'name':p['name'],'description':p['description'],'exits':deepcopy(p['exits']),'provenance':p.get('provenance','disposable_fixture')} for k,p in locations.items()],
  'people':[{'id':k,**{f:p[f] for f in ('name','location','description','provenance')},'activity':npc_activity.activity(s,k),'carrying':[{'id':oid,'name':o['name']} for oid,o in box['objects'].items() if o['location']==npc_activity.holder(k)]} for k,p in box.get('people',{}).items() if p['location']==loc],
  'known_people':[{'id':k,'name':p['name'],'location':p['location'],'activity':npc_activity.activity(s,k)} for k,p in box.get('people',{}).items()],
  'npc_plans':[{'id':id,'actor':p['actor'],'purpose':p['purpose'],'status':p['status'],'completed_steps':p['cursor'],'total_steps':len(p['steps']),'next_step':deepcopy(p['steps'][p['cursor']]) if p['status']=='pending' else None,'stopping':p['stop_after_current']} for id,p in box.get('npc_plans',{}).items() if p['status']=='pending' or id in list(box.get('npc_plans',{}))[-10:]],
  'npc_events':npc_activity.events(s)[-12:],
  'established_facts':[{'id':k,'text':f['text'],'provenance':f['provenance']} for k,f in box.get('facts',{}).items()],
  'challenges':[deepcopy(d) for d in box.get('challenges',{}).values() if d['location']==loc and d['id'] not in box.get('challenge_results',{})],
  'challenge_results':[{'id':k,**deepcopy(r)} for k,r in box.get('challenge_results',{}).items()],
  'world_record_ids':{'objects':list(box['objects']),'people':list(box.get('people',{}))},
  'character':{'name':s['identity']['name'],'rank':s['rank'],'attributes':{k:s['attributes'][k] for k in ('body','grace','wits','will','presence')},'skills':{k:s['skills'][k] for k in ('athletics','melee','marksmanship','stealth','survival','notice','scholarship','medicine','persuasion','insight','leadership','composure')},
    'known_weaves':list(s['channeling']['known_weaves']),'capacity':s['channeling']['current_capacity'],'control':s['channeling']['control'],'flows':{k:s['channeling']['flows'][k] for k in ('air','earth','fire','water','spirit')},
    'inventory':list(s['resources']['inventory'])},
  'last_cast':deepcopy(box['last_cast']),
  'limits':['Disposable fixture; room layout and daily supervisor schedule are sandbox fixtures, not canonical Tower geography.',
   'No combat, Healing, opposed checks, NPC combat or channeling, curriculum progression or live-character import is implemented.',
   'Public world preparation is additive and labelled campaign invention. Descriptions confer no abilities, supervision, rewards or completed player actions. Secret preparation and retcons are not supported.',
   'Mundane challenges use saved ratings and server 2d10, fixed consequences and at most three rolled checks per declared scene. Routine work uses no dice. The storyteller must judge uncertainty, source access and modifier relevance, preserve scene identity and honour completed goals; the engine cannot verify prose semantics.',
   'Public NPC errands support movement along established routes and safe pickup/drop, carrying at most 5 kg of ordinary props. Plans resolve on fictional time, never wall time; no conflict, secrets, PC control or interaction requiring a player decision. In transit, location is the departure point until arrival; inspect activity. Player actions claim their immediate effects before background completion. Full journals retain every result.',
   'The storyteller supplies prose. Only committed engine actions change state. Unsupported actions must be reported, not invented.']}


def view(s):
 ctx=context(s)
 return {'title':'White Tower sandbox','episode_id':EPISODE_ID,'rules_edition':'notion-manual-v2','disposable':True,
  'character':{'name':s['identity']['name'],'age':s['identity']['age'],'rank':s['rank']},
  'location':ctx['location'],'story':ctx['description'],'objective':'No assigned story. Explore and use the available world operations.',
  'choices':choices(s),'status':'in_progress','completed':False,'result':None,
  'resources':{k:s['resources'][k] for k in ('vitality','max_vitality','wounds','strain','supply','silver')},
  'fictional_seconds':s['clock']['fictional_seconds'],'sample_notice':'Story-independent disposable sandbox. Narration is supplied separately.'}
