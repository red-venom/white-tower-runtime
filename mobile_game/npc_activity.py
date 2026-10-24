"""Public, non-conflict NPC errands on the existing fictional clock.

Plans never move the PC, take their belongings, apply harm, or grant abilities.
Their predictable background steps settle inside the same saved player action.
"""
from copy import deepcopy
from .world_schema import ID, TEXT, _id, _text

STEP={'type':'object','properties':{'op':{'type':'string','enum':['move','take','drop']},'target':ID},
      'required':['op','target'],'additionalProperties':False}
STEPS={'type':'array','minItems':1,'maxItems':8,'items':STEP}
OPS={'npc_plan','cancel_npc_plan'}


def holder(actor):
    return 'person:'+actor


def active_plan(box, actor):
    return next((p for p in box.get('npc_plans',{}).values() if p['actor']==actor and p['status']=='pending'),None)


def _perform(state, actor, step):
    from .sandbox import places
    box=state['world']['sandbox'];person=box.get('people',{}).get(actor)
    if person is None:raise ValueError('Use an established NPC; player characters cannot be directed.')
    op,target=step['op'],step['target'];location=person['location']
    if op=='move':
        route=places(state)[location]['exits'].get(target)
        if route is None:raise ValueError('NPC movement requires an established direct route.')
        person['location']=target
        return route,person['name']+' arrived at '+places(state)[target]['name']+'.'
    obj=box['objects'].get(target)
    if obj is None:raise ValueError('Use an established ordinary object.')
    if op=='take':
        if obj['location']!=location or not obj['portable'] or obj['elevated'] or obj['lit']:
            raise ValueError('The object is no longer reachable, safe and unheld at the NPC location.')
        load=sum(o['weight_kg'] for o in box['objects'].values() if o['location']==holder(actor))
        if load+obj['weight_kg']>5:raise ValueError('This ordinary-errand adapter supports at most 5 kg of carried props; heavier work needs other mechanics.')
        obj['location']=holder(actor)
        return 10,person['name']+' picked up '+obj['name']+'.'
    if op=='drop':
        if obj['location']!=holder(actor):raise ValueError('The NPC is not carrying that object.')
        obj['location']=location;obj['elevated']=False
        return 10,person['name']+' put down '+obj['name']+'.'
    raise ValueError('Only movement and ordinary pickup/drop are supported.')


def resolve(state, command):
    from .sandbox import validate
    validate(state)
    if type(command) is not dict:raise ValueError('Use a structured NPC command.')
    op=command.get('op')
    if op=='cancel_npc_plan':
        if set(command)!={'op','target'}:raise ValueError('Cancel a plan by its exact identifier.')
        _id(command['target']);out=deepcopy(state)
        plan=out['world']['sandbox'].get('npc_plans',{}).get(command['target'])
        if not plan or plan['status']!='pending' or plan.get('stop_after_current'):
            raise ValueError('That plan is not pending or is already stopping.')
        plan['stop_after_current']=True
        text='The NPC will finish the current step and stop. No time advanced and no completed action was undone.'
        return {'state':out,'narration':text,'elapsed_seconds':0,'roll':None}
    if op!='npc_plan' or set(command)!={'op','id','actor','purpose','steps'}:
        raise ValueError('A public NPC plan needs only id, actor, purpose and steps.')
    for k in ('id','actor'):_id(command[k])
    _text(command['purpose'])
    box=state['world']['sandbox'];plans=box.get('npc_plans',{})
    if command['id'] in plans:raise ValueError('Plan IDs are immutable; do not overwrite or replay a completed errand.')
    if len(plans)>=400:raise ValueError('This disposable sandbox has reached its NPC plan capacity.')
    if command['actor'] not in box.get('people',{}):raise ValueError('Use an established NPC; player characters cannot be directed.')
    if active_plan(box,command['actor']):raise ValueError('This NPC already has an active plan.')
    steps=command['steps']
    if type(steps) is not list or not 1<=len(steps)<=8:raise ValueError('Declare one to eight ordinary steps.')
    for step in steps:
        if type(step) is not dict or set(step)!={'op','target'} or step['op'] not in ('move','take','drop'):
            raise ValueError('Use exact move, take or drop steps.')
        _id(step['target'])
    reserved={s['target'] for p in plans.values() if p['status']=='pending' for s in p['steps'][p['cursor']:p['cursor']+1 if p['stop_after_current'] else len(p['steps'])] if s['op']!='move'}
    if reserved & {s['target'] for s in steps if s['op']!='move'}:
        raise ValueError('Another NPC plan already uses this object. Contested actions need their own resolution.')
    probe=deepcopy(state);due=state['clock']['fictional_seconds'];scheduled=[]
    for step in steps:
        origin=probe['world']['sandbox']['people'][command['actor']]['location']
        seconds,_=_perform(probe,command['actor'],step)
        due+=seconds
        if due>2**53-1:raise ValueError('NPC plan exceeds the supported clock.')
        scheduled.append({**step,'from':origin,'seconds':seconds,'due_at':due})
    out=deepcopy(state)
    out['world']['sandbox'].setdefault('npc_plans',{})[command['id']]={
        'actor':command['actor'],'purpose':command['purpose'],'started_at':state['clock']['fictional_seconds'],
        'steps':scheduled,'cursor':0,'status':'pending','results':[],'stop_after_current':False}
    text=box['people'][command['actor']]['name']+' will carry out the declared ordinary errand as fictional time advances. No time or player resources changed.'
    return {'state':out,'narration':text,'elapsed_seconds':0,'roll':None}


def settle(state, end):
    """Called only inside a clock transition; never from a read or wall-clock timer."""
    box=state['world']['sandbox']
    while True:
        due=[(p['steps'][p['cursor']]['due_at'],id,p) for id,p in box.get('npc_plans',{}).items() if p['status']=='pending' and p['steps'][p['cursor']]['due_at']<=end]
        if not due:return
        at,id,plan=min(due,key=lambda d:(d[0],d[1]));step=plan['steps'][plan['cursor']]
        try:
            if box['people'][plan['actor']]['location']!=step['from']:raise ValueError('The NPC is no longer at the expected location.')
            _,text=_perform(state,plan['actor'],step)
        except ValueError as exc:
            plan['status']='blocked'
            plan['results'].append({'at':at,'step':plan['cursor'],'status':'blocked','text':box['people'][plan['actor']]['name']+' could not complete the errand: '+str(exc)})
            continue
        plan['results'].append({'at':at,'step':plan['cursor'],'status':'completed','text':text})
        plan['cursor']+=1
        if plan['stop_after_current']:plan['status']='cancelled'
        elif plan['cursor']==len(plan['steps']):plan['status']='completed'


def activity(state, actor):
    plan=active_plan(state['world']['sandbox'],actor)
    if plan is None:return None
    step=plan['steps'][plan['cursor']]
    return {'op':step['op'],'target':step['target'],'from':step['from'],'due_at':step['due_at'],'stopping':plan['stop_after_current']}


def events(state):
    return sorted([{'plan_id':id,'actor':p['actor'],**deepcopy(r)} for id,p in state['world']['sandbox'].get('npc_plans',{}).items() for r in p['results']],key=lambda r:(r['at'],r['plan_id'],r['step']))


def new_events(before, after):
    old={(r['plan_id'],r['step']) for r in events(before)}
    return [r for r in events(after) if (r['plan_id'],r['step']) not in old]


def choice(state, command):
    from .store import digest
    result=resolve(state,command)
    return {'id':command['op']+':'+digest(command),'label':'Direct an ordinary NPC errand' if command['op']=='npc_plan' else 'Stop after the current NPC step',
        'description':result['narration'],'stakes':'Public background activity only. No immediate time, player resource, decision or ability changes. Future steps settle with fictional time and stop if preconditions fail.',
        'requires_roll':False,'command':deepcopy(command)}


def narration(before, after):
    results=new_events(before,after)
    text=' '.join(r['text'] for r in results[:8])
    if len(results)>8:text+=' Further NPC results are recorded in the world activity journal.'
    return (' '+text) if text else ''
