"""Deterministic full catalogue effects. Authored state supplies facts and risks.

No prose-to-power conversion, random draws, network calls, or persistent writes.
The dispatcher passes a clone and freezes the returned branches before rolling.
"""
from copy import deepcopy
from .catalogue import WEAVES, prerequisites
from .contracts import canonical, digest, normalize
from .rules import RuleError, _require, _integer
from .oaths import adjudicate, public_view

BANDS = ('clean', 'costly', 'setback')
ATTACKS = {'W01','W02','W03','W32','W33','W34','W35'}
BONUSES = {'W13':('notice','survival'), 'W15':('stealth',),
           'W17':('notice','scholarship'), 'W18':('notice',),
           'W24':('survival',), 'W30':('athletics','survival'),
           'W31':('stealth','athletics')}
VERBS = {'cast','embrace','release','tie','untie','move','continue_cast',
         'magic_prepare','magic_use','treatment_recovery','shield_struggle','circle_train','companion_embrace','circle_form','circle_end','attune_angreal','remove_angreal','oath_defence'}


def handles(intent):
    return type(intent) is dict and intent.get('verb') in VERBS


def _closed(intent, required=(), optional=()):
    _require(type(intent) is dict and set(intent) <= {'verb',*required,*optional}
             and set(required) <= set(intent), 'Unknown or missing magic intent fields.')
    normalize(intent)
    for key in ('weave_id','target_id','mode','cost','concentration','material_id','held_id','tied_id','operation','skill_id','cost_actor_id','leader_id'):
        if key in intent: _require(type(intent[key]) is str and 0<len(intent[key])<=128, 'Invalid identifier or option: '+key)


def _meta(record):
    return record.get('magic', {})


def _target(state, target_id, range_m):
    _require(type(target_id) is str and target_id in state, 'Unknown target.')
    target = state[target_id]
    if target_id not in ('pc','world'):
        _require(target.get('visible') is True, 'The target must be visible.')
        _require(_integer(target.get('distance_m'), 0, range_m), 'Target is outside range.')
        _require(target.get('location', state['world']['location']) == state['world']['location'], 'Target is elsewhere.')
    _require(_meta(target).get('clear_route', True), 'The route to the target is blocked.')
    return target


def _instance(key, weave, target_id, now, area=0):
    return {'id':key,'weave_id':weave['weave_id'],'load':weave['load'],
            'target_id':target_id,'binding_contribution':0,
            'expires_at':now+weave['max_duration_seconds'] if weave['max_duration_seconds'] else None,
            'area_metres':area}


def initialize(state, fixtures=False):
    """Add fixed fields and optional practice objects to a NEW versioned genesis."""
    p,w = state['pc'],state['world']
    p['magic'] = {'pending':None,'effects':{},'progress':{},'attempts':[],
                  'methods':{},'progress_source':{},'observation':None,'oath_result':None,
                  'oath_beliefs':[],'oath_evidence':[], 'shielded_by':None,
                  'mass_grams':70000,'last_interruption':None,'circle':None,'circle_trained':False,
                  'power_side':'saidar','angreal_id':None,'circle_training':None}
    p['magic_status'] = {}
    p.setdefault('warning_ready',False)
    w['magic'] = {'opponent_id':None,'area_metres':10,'crossings':0}
    for target in state.values():
        if target is not p and target is not w:
            target.setdefault('magic', {})
            if target.get('kind') == 'object':
                target.setdefault('location', w['location'])
    records=_fixture_records(w['location'])
    if fixtures:
        state.update(records)
    else:
        # One fixed record can represent an authored nonliving practice object.
        template={}
        for item in records.values():
            for key,value in item.items(): template.setdefault(key,deepcopy(value))
        template.update(deepcopy(records['magic-W01']))
        template['magic']['configured_weave']='W01'
        state['magic-practice']=template
    mentor=state.get('npc-mentor')
    if mentor is not None:
        for key,value in {'control':3,'capacity':6,'flows':dict.fromkeys(('air','earth','fire','water','spirit'),2),
                          'strain':0,'embraced':False,'held':[],'tied':[]}.items():
            mentor.setdefault(key,deepcopy(value))
    state['magic-angreal']={'name':'Institutional practice angreal','kind':'object','visible':True,
        'distance_m':0,'location':w['location'],'magic':{'angreal_bonus':2,'loan_permitted':True,'attuned_to':None}}
    for rid in ('npc-mentor','npc-peer'):
        actor=state.get(rid)
        if actor is not None:
            for key,value in {'control':3 if rid=='npc-mentor' else 1,'capacity':6 if rid=='npc-mentor' else 3,
                'flows':dict.fromkeys(('air','earth','fire','water','spirit'),2 if rid=='npc-mentor' else 1),
                'strain':0,'embraced':False,'held':[],'tied':[], 'known_weaves':list(WEAVES) if rid=='npc-mentor' else ['W01','W02'],
                'attributes':{'will':2},'skills':{},'support_pending':None}.items(): actor.setdefault(key,deepcopy(value))
            actor.setdefault('oaths_active',False)
            actor.setdefault('oaths_source_event','genesis')
            actor['magic'].update(channeler=True,circle_trained=rid=='npc-mentor',power_side='saidar',circle_id=None,
                angreal_id=None,oath_beliefs=[],oath_evidence=[])
    refresh(state)


def _fixture_records(location):
    records={}
    common = {'kind':'object','visible':True,'distance_m':0,'location':location}
    fixtures = {
      'W01':{'dry_tinder':True,'lit':False,'mass_grams':50},
      'W02':{'mass_grams':2000,'distance_m':6},
      'W03':{'kind':'person','ordinary_target':True,'consenting':True},
      'W04':{'magic':{'area_metres':10}},
      'W05':{'kind':'person'}, 'W06':{'kind':'person'},
      'W07':{'magic':{'fixed_point':True}},
      'W08':{'magic':{'water_ml':10000,'temperature_c':20,'open_vessel':True}},
      'W09':{'magic':{'water_ml':10000,'temperature_c':35,'open_vessel':True}},
      'W10':{'mass_grams':2000,'magic':{'material':'fabric','water_ml':1000,'unattended':True}},
      'W11':{'magic':{'water_ml':20000,'container_ml':10000,'received_ml':0,'rise_metres':0,'open_source':True}},
      'W12':{'magic':{'water_ml':20000,'open_vessel':True,'visible_sediment':True,'settled':False}},
      'W13':{'magic':{'area_metres':3,'visible_particles':True}},
      'W14':{'magic':{'small_sail':True,'occupants':4,'still_water':True,'distance_moved_cm':0}},
      'W15':{'magic':{'area_metres':2}}, 'W16':{'distance_m':60,'magic':{'receiving_point':True,'messages':[]}},
      'W17':{'magic':{'surface':True,'adequate_light':True}},
      'W18':{'distance_m':500,'magic':{'object_metres':1,'adequate_light':True,'fog':False}},
      'W19':{'kind':'person','magic':{'existing_air':True,'depth_metres':2}},
      'W20':{'kind':'person','mass_grams':70000,'magic':{'fall_metres':4}},
      'W21':{'magic':{'stable_supports':True,'gap_metres':3,'supported_grams':0,'crossings':0}},
      'W22':{'mass_grams':100000,'magic':{'height_metres':0,'drop_harm':3,'area_metres':2}},
      'W23':{'magic':{'door_metres':2,'closure_harm':0}},
      'W24':{'magic':{'area_metres':3,'severe_weather':False}},
      'W25':{'magic':{'material':'cord','knot_visible':True,'weight_supported':True,'knotted':True}},
      'W26':{'magic':{'material':'soil','soil_litres':250,'exposed':True,'supports_safe':True,'loose':False}},
      'W27':{'magic':{'material':'stone','scan_depth_cm':100,'voids':[{'width_cm':20,'depth_cm':50}]}},
      'W28':{'mass_grams':8000,'magic':{'material':'stone','aligned':True,'clean_fracture':True,'load_bearing':False,'special':False,'mended':False,'missing_chip':True}},
      'W29':{'mass_grams':1000,'magic':{'material':'metal','unattended':True,'special':False,'hot':False,'intended_human_killing':False}},
      'W30':{'magic':{'area_metres':5,'shallow':True,'moderate_current':True}},
      'W31':{'magic':{'water_ml':1000,'area_metres':3}},
      'W32':{'mass_grams':20000,'magic':{'open_surface':True,'pushed_metres':0}},
      'W33':{'kind':'person','hostile':True,'guard':14,'harm':2,'harm_source':'melee','resistance':6,'max_resistance':6,'defeated':False},
      'W34':{'kind':'person','hostile':True,'guard':14,'harm':2,'harm_source':'melee','resistance':6,'max_resistance':6,'defeated':False},
      'W35':{'magic':{'material':'rope','diameter_mm':15,'unworn':True,'cut_safe':True,'cut':False}},
      'W36':{'lit':True,'magic':{'ordinary_fire':True,'fire_metres':2,'hot':True}},
      'W37':{'kind':'weave','magic':{'owner_id':'magic-channeler','instance_id':'foreign-guard'}},
      'W38':{'kind':'person','control':3,'capacity':6,'embraced':True,'held':[],'tied':[], 'magic':{'channeler':True,'shielded_by':None}},
      'W39':{'kind':'person','wounds':2},
      'W40':{'kind':'weave','magic':{'owner_id':'magic-channeler','instance_id':'foreign-ward'}},
    }
    for weave_id, changes in fixtures.items():
        target = {**deepcopy(common),'name':'Practice: '+WEAVES[weave_id]['name'],
                  'mass_grams':1000,'magic':{},**deepcopy(changes)}
        if target['kind']=='person':
            for key,value in {'alive':True,'consenting':True,'vitality':3,'max_vitality':8,'wounds':1,'healing_used':False,'firstaid_used':False,'restrained':False,'ordinary_target':True}.items():
                target.setdefault(key,value)
        target['magic'].setdefault('practice_fixture',True)
        target['magic'].setdefault('difficulty',None)
        target['magic'].setdefault('treatment',None)
        target['magic'].setdefault('treatment_completed_at',None)
        records['magic-'+weave_id] = target
    records['magic-pebble'] = {**common,'name':'Practice pebble','mass_grams':50,
                             'magic':{'material':'stone','available':True,'impact_target':None}}
    records['magic-channeler'] = {**common,'name':'Authored practice channeler','kind':'person',
        'control':3,'capacity':6,'embraced':True,'alive':True,'consenting':True,
        'vitality':8,'max_vitality':8,'wounds':0,'healing_used':False,'firstaid_used':False,
        'held':[_instance('foreign-guard',WEAVES['W05'],'magic-channeler',0)],
        'tied':[{**_instance('foreign-ward',WEAVES['W04'],'magic-channeler',0),'expires_at':3600}],
        'magic':{'shielded_by':None}}
    return records


def refresh(state):
    p=state['pc']; m=p['magic']; pending=m['pending']
    p['magic_status'] = {
      'pending':None if pending is None else {'weave_id':pending['weave_id'],
          'target_id':pending['intent']['target_id'],'remaining_seconds':pending['required_seconds']-pending['elapsed_seconds'],
          'reserved_load':WEAVES[pending['weave_id']]['load']},
      'observation':deepcopy(m['observation']), 'oath_result':deepcopy(m['oath_result']),
      'shielded':m.get('shielded_by') is not None,
      'circle':deepcopy(m.get('circle')), 'angreal_id':m.get('angreal_id'),
      'available_bonuses':[{'held_id':e['id'],'skills':list(BONUSES[e['weave_id']])}
          for e in p['held'] if e['weave_id'] in BONUSES and not m['effects'].get(e['id'],{}).get('bonus_used',False)],
    }


def validate(state):
    p,w=state['pc'],state['world']; m=p['magic']
    _require(type(m) is dict and type(m.get('effects')) is dict, 'Invalid magic state.')
    pending=m.get('pending'); reserve=0 if pending is None else WEAVES[pending['weave_id']]['load']
    slots=0 if pending is None else 1
    if pending:
        _require(pending['weave_id'] in WEAVES and WEAVES[pending['weave_id']]['casting_seconds']>10, 'Invalid pending form.')
        _require(_integer(pending['elapsed_seconds'],0,pending['required_seconds']-1), 'Invalid pending time.')
        _require(pending['required_seconds']==WEAVES[pending['weave_id']]['casting_seconds'], 'Changed casting duration.')
        _require(pending['outcome'] in BANDS and p['embraced'], 'Invalid frozen cast outcome.')
    keys=[]; ids=[]
    for collection in ('held','tied'):
        for e in p[collection]:
            _require(set(e)=={'id','weave_id','load','target_id','binding_contribution','expires_at','area_metres'},'Invalid weave instance fields.')
            _require(e['weave_id'] in WEAVES and WEAVES[e['weave_id']]['held'], 'Invalid sustained form.')
            card=WEAVES[e['weave_id']]
            _require(e['load']==card['load'] and e['target_id'] in state, 'Invalid weave Load or target.')
            _require(collection!='tied' or card['tying'], 'This form cannot be tied.')
            _require(e['expires_at'] is None or _integer(e['expires_at']), 'Invalid expiry.')
            _require(_integer(e['binding_contribution']) and _integer(e['area_metres']), 'Invalid effect bounds.')
            keys.append((e['weave_id'],e['target_id'])); ids.append(e['id'])
    _require(len(set(keys))==len(keys) and len(set(ids))==len(ids), 'Duplicate weave instance.')
    _require(len(p['held'])+slots<=_slot_limit(state) and len(p['tied'])<=p['control'], 'Weave slots exceeded.')
    _require(sum(e['load'] for e in p['held']+p['tied'])+reserve<=_load_limit(state), 'Committed Load exceeded.')
    _require(sum(e['load'] for e in p['tied'])<=p['capacity'], 'Tied Load cannot depend on an item or circle.')
    _require(not p['held'] or p['embraced'], 'Held effect without Source.')
    _require(_integer(p['strain'],0,2*p['capacity']), 'Strain outside capacity.')
    for target in state.values():
        treatment=_meta(target).get('treatment')
        if treatment:
            _require(_integer(treatment['remaining_seconds'],1,86400), 'Invalid treatment recovery.')
    return True


def release_entry(state, entry):
    target=state[entry['target_id']]; p=state['pc']; wid=entry['weave_id']
    if wid=='W03':
        if 'resistance' in target and not target.get('defeated',False):
            target['resistance']=min(target['max_resistance'],target['resistance']+entry['binding_contribution'])
        target['restrained']=False
    if wid=='W38':
        _meta(target)['shielded_by']=None
        p['magic']['progress'].pop('W38:'+entry['target_id'],None)
    p['magic']['effects'].pop(entry['id'],None)
    if p.get('support_pending') and p['support_pending']['ally_id']==entry['id']: p['support_pending']=None
    if wid=='W22' and _meta(target).get('height_metres',0)>0:
        m=_meta(target); amount=m['drop_harm']; m['height_metres']=0
        if 'vitality' in target: _harm_other(state,entry['target_id'],amount,'fall')
        else: m['drop_damage']=m.get('drop_damage',0)+amount


def interrupt(state, reason):
    p=state['pc']; pending=p['magic']['pending']
    if pending:
        p['magic']['last_interruption']={'weave_id':pending['weave_id'],
            'elapsed_seconds':pending['elapsed_seconds'],'reason':reason}
        p['magic']['pending']=None
    refresh(state)


def drop(state, held_id=None):
    p=state['pc']
    for entry in list(p['held']):
        if entry in p['held'] and (held_id is None or entry['id']==held_id):
            p['held'].remove(entry); release_entry(state,entry)
    pending=p['magic']['pending']
    if pending and (held_id is None or pending['id']==held_id):
        interrupt(state,'Released or lost concentration.')
    refresh(state)


def before_action(state, intent):
    pending=state['pc']['magic']['pending']
    circle=state['pc']['magic'].get('circle')
    if circle and any(state[r].get('vitality',0)==0 or not state[r].get('embraced') or not state[r].get('willing',True) or _meta(state[r]).get('leave_requested') for r in circle['members']):
        _end_circle(state)
    if pending:
        keep=intent.get('verb') in ('continue_cast','release')
        if not keep or state['world']['active_conflict']:
            interrupt(state,'Another action or active conflict interrupted the cast.')


def _prevent_harm(state, target_id, amount, source):
    p=state['pc']
    if source in ('projectile','debris','flame') and any(e['weave_id']=='W05' and e['target_id']==target_id for e in p['held']+p['tied']):
        amount=max(0,amount-1)
    if source=='fall':
        catch=next((e for e in p['held'] if e['weave_id']=='W20' and e['target_id']==target_id),None)
        if catch:
            amount=max(0,amount-3); drop(state,catch['id'])
    return amount


def harm(state, amount, source, concentration='drop'):
    p=state['pc']; amount=_prevent_harm(state,'pc',amount,source)
    if not amount:
        return
    p['vitality']=max(0,p['vitality']-amount)
    if p['vitality']==0:
        p['wounds']=min(3,p['wounds']+1); drop(state); p['embraced']=False
        _end_circle(state)
        state['world']['active_conflict']=False; state['world']['defeat_pending']=True
    else:
        entries=p['held']+([p['magic']['pending']] if p['magic']['pending'] else [])
        if entries:
            if concentration=='preserve':
                _require(p['strain']<2*p['capacity'],'Cannot afford concentration in every result.')
                p['strain']+=1
            else:
                selected=entries[0]['id'] if concentration in ('drop',None) else concentration
                _require(any(e['id']==selected for e in entries),'Unknown concentration release choice.')
                drop(state,selected)
    refresh(state)


def _active_weave(state,target):
    m=_meta(target); owner=state.get(m.get('owner_id'),{})
    interval=state.get('conflict',{}).get('deferred_clock')
    now=interval['start'] if interval else state['world']['time_seconds']
    for held in ('held','tied'):
        entry=next((e for e in owner.get(held,[]) if e['id']==m.get('instance_id')),None)
        if entry and (entry['expires_at'] is None or entry['expires_at']>now):
            return owner,entry,held
    raise RuleError('The observed weave is no longer active.')


def _end_foreign(state,target):
    owner,entry,collection=_active_weave(state,target)
    if owner is state['pc']:
        if collection=='held': drop(state,entry['id'])
        else: release_entry(state,entry); owner['tied'].remove(entry)
    else:
        victim=state[entry['target_id']]
        if entry['weave_id']=='W03': victim['restrained']=False
        if entry['weave_id']=='W38': _meta(victim)['shielded_by']=None
        owner[collection].remove(entry)


def _validate_target(state,wid,target_id,mode,intent):
    card=WEAVES[wid]; t=_target(state,target_id,card['range']); m=_meta(t)
    attack=mode=='attack'
    _require(mode in ('utility','attack'),'Unsupported cast mode.')
    if attack:
        _require(wid in ATTACKS and state['world']['active_conflict'] and t.get('hostile') is True,'Attack needs a published opposing conflict.')
        _require(t.get('resistance',0)>0 and not t.get('defeated',False),'The target no longer opposes the action.')
        _require(_integer(t.get('guard'),1,22) and _integer(t.get('harm'),0,3),'Missing declared Guard or Harm.')
        _require(not m.get('cover',False),'The target has blocking cover.')
    else:
        _require(wid not in ('W33','W34'),'This form is an attack.')
    def need(condition,text): _require(condition,text)
    if wid=='W01' and not attack: need(t.get('dry_tinder') is True and not t.get('lit',False),'Spark needs exposed dry tinder.')
    if wid=='W02':
        obj=_target(state,intent.get('material_id'),10) if attack else t
        need(obj.get('kind')=='object' and _integer(obj.get('mass_grams'),0,5000),'Air Hand object exceeds5kg.')
    if wid=='W03': need(t.get('kind')=='person' and t.get('ordinary_target') is True and (attack or t.get('consenting') is True),'Binding needs an ordinary consenting or opposing person.')
    if wid=='W04': need(_integer(intent.get('area_metres',m.get('area_metres',10)),1,10),'Ward area exceeds10m.')
    if wid=='W05': need(target_id=='pc' or t.get('kind')=='person','Guard needs a person.')
    if wid in ('W06','W39'):
        need(target_id!='pc' and t.get('kind')=='person' and t.get('alive') is True,'This care needs another living person.')
        need(t.get('consenting') is True or (wid=='W06' and t.get('vitality')==0),'The patient has not consented.')
        if wid=='W06': need(not t.get('healing_used') and t['vitality']<t['max_vitality'],'Healing benefit unavailable until patient rests.')
        else:
            need(t['wounds']>0 and m.get('treatment') is None,'A Wound or free treatment slot is missing.')
            done=m.get('treatment_completed_at'); need(done is None or state['world']['time_seconds']>=done+604800,'Seven full days must pass after treatment benefit.')
    if wid=='W07': need(t.get('kind')=='object' or m.get('fixed_point'),'Lamp needs a fixed point or carried object.')
    if wid in ('W08','W09'):
        need(t.get('kind')!='person' and not m.get('worn') and not t.get('lit',False),'Temperature form requires unworn nonliving material.')
        need(_integer(m.get('water_ml'),1,10000) or _integer(t.get('mass_grams'),1,1000),'Temperature target exceeds its size limit.')
        need(type(m.get('temperature_c')) is int,'Target temperature is unknown.')
        need(m['temperature_c']<50 if wid=='W08' else m['temperature_c']>5,'The temperature limit is already reached.')
    if wid=='W10': need(m.get('material')=='fabric' and m.get('unattended') and _integer(t.get('mass_grams'),1,2000) and m.get('water_ml',0)>0,'Drying needs unattended wet fabric up to2kg.')
    if wid=='W11': need(m.get('open_source') and m.get('water_ml',0)>0 and m.get('container_ml',0)>m.get('received_ml',0) and _integer(m.get('rise_metres'),0,5),'Draw Water needs open water, container room and a rise within5m.')
    if wid=='W12': need(m.get('open_vessel') and _integer(m.get('water_ml'),1,20000) and m.get('visible_sediment') and not m.get('settled'),'Settling requires visible sediment in an open vessel.')
    if wid=='W13': need(_integer(m.get('area_metres'),1,3) and m.get('visible_particles'),'Air Sieve only diverts visible particles within3m.')
    if wid=='W14': need(m.get('small_sail') and _integer(m.get('occupants'),0,4) and m.get('still_water'),'Sail Breeze needs a small sail on still water.')
    if wid=='W15': need(target_id=='pc' or m.get('practice_fixture'),'Quiet Pocket is centred on its caster.')
    if wid=='W16': need(m.get('receiving_point'),'Carry Voice needs an open visible receiving point.')
    if wid=='W17': need(t.get('kind')!='person' and m.get('surface') and m.get('adequate_light'),'Close Lens requires a lit nonliving surface.')
    if wid=='W18': need(m.get('object_metres',0)>=1 and m.get('adequate_light') and not m.get('fog'),'Far Lens needs an unobstructed large object in good light.')
    if wid=='W19': need(t.get('kind')=='person' and t.get('consenting') and m.get('existing_air') and _integer(m.get('depth_metres'),0,2),'Air Pocket needs existing air and shallow water.')
    if wid=='W20': need((target_id=='pc' or t.get('kind')=='object' or t.get('consenting')) and _integer(t.get('mass_grams',m.get('mass_grams')),1,120000) and _integer(m.get('fall_metres'),0,5),'Catch must be prepared for an eligible fall within5m.')
    if wid=='W21': need(m.get('stable_supports') and _integer(m.get('gap_metres'),1,3),'Short Bridge requires stable supports and a gap within3m.')
    if wid=='W22': need(target_id!='pc' and _integer(t.get('mass_grams'),1,150000) and (t.get('kind')!='person' or t.get('consenting')) and _integer(m.get('drop_harm'),0,3),'Lifting needs consent, a declared drop hazard and load within150kg.')
    if wid=='W23': need(_integer(m.get('door_metres'),1,2),'Door Brace needs an existing closure within2m.')
    if wid=='W24': need(_integer(m.get('area_metres'),1,3) and not m.get('severe_weather'),'Weather Screen cannot stop severe weather.')
    if wid=='W25': need(m.get('material') in ('cord','rope','thread') and m.get('knot_visible') and m.get('weight_supported') and m.get('knotted'),'Unknotting needs a visible safely unloaded knot.')
    if wid=='W26': need(m.get('material')=='soil' and m.get('exposed') and m.get('supports_safe') and _integer(m.get('soil_litres'),1,250) and not m.get('loose'),'Loosen Earth needs supported exposed soil within250litres.')
    if wid=='W27': need(m.get('material')=='stone' and _integer(m.get('scan_depth_cm'),1,100) and type(m.get('voids')) is list,'Stone Probe needs a defined stone inspection.')
    if wid=='W28': need(m.get('material')=='stone' and _integer(t.get('mass_grams'),1,10000) and m.get('aligned') and m.get('clean_fracture') and not m.get('load_bearing') and not m.get('special') and not m.get('mended'),'Mend Stone needs aligned ordinary matching pieces.')
    if wid=='W29': need(m.get('material')=='metal' and _integer(t.get('mass_grams'),1,1000) and m.get('unattended') and not m.get('special'),'Forge Heat needs bare unattended ordinary metal.')
    if wid=='W30': need(_integer(m.get('area_metres'),1,5) and m.get('shallow') and m.get('moderate_current'),'Water Brake needs shallow moderate current.')
    if wid=='W31': need(m.get('water_ml',0)>=1000 and _integer(m.get('area_metres'),1,3),'Steam Veil needs an existing litre of water.')
    if wid=='W32' and not attack: need(t.get('kind')=='object' and _integer(t.get('mass_grams'),1,25000) and m.get('open_surface'),'Air Stroke object limit is25kg on an open surface.')
    if wid=='W34':
        pebble=_target(state,intent.get('material_id'),20)
        need(_meta(pebble).get('material')=='stone' and _integer(pebble.get('mass_grams'),1,100) and _meta(pebble).get('available'),'Stone Shot requires one available pebble.')
    if wid=='W35':
        if attack: need(m.get('lethal_intent_authorized') or m.get('safe_cutting_alternative'),'Human cutting attack needs a declared adjudicated intent.')
        else: need(m.get('material')=='rope' and m.get('unworn') and m.get('cut_safe') and _integer(m.get('diameter_mm'),1,20) and not m.get('cut'),'Air Blade utility needs exposed safe unworn rope.')
    if wid=='W36': need(m.get('ordinary_fire') and t.get('lit') and _integer(m.get('fire_metres'),1,2),'Dampen Flame needs an exposed ordinary fire within2m.')
    if wid in ('W37','W40'):
        owner,entry,collection=_active_weave(state,t)
        if wid=='W37': need(collection=='held' and entry['load']<=_caster(state)['control'],'Disruption needs a perceivable held weave within the leader’s Control Load.')
    if wid=='W38': need(target_id!='pc' and m.get('channeler') and _integer(t.get('control'),1,4) and _integer(t.get('capacity'),3,10),'Shield requires another defined channeler.')
    return t


def _oaths(state,wid,target,mode,action_id):
    p=state['pc']; m=p['magic']; tm=_meta(target)
    actor={'actor_id':'pc','oaths_active':p['oaths_active'],'oaths_source_event':p.get('oaths_source_event','genesis'),
           'beliefs':m['oath_beliefs'],'evidence':m['oath_evidence']}
    harmful=(mode=='attack' and wid!='W03' and not tm.get('inert_target',False)) or tm.get('use_harmful',False)
    context=tm.get('oath_context',{})
    if context.get('source_action') is not None and (
        context['source_action']!=(target.get('threat') or {}).get('source_action') or
        not state['world']['active_conflict']):
        context={}
    details={'effect':'weapon' if harmful else ('restraint' if wid in ('W03','W38') else 'utility'),
        'injures':harmful,'exposes_immediate_harm':tm.get('exposes_immediate_harm',False),
        'shadowspawn_proposition_id':context.get('shadowspawn_proposition_id'),
        'danger':context.get('danger'),'construct':None}
    if wid=='W29':
        details['construct']={'item_kind':'construct','intended_human_killing':tm.get('intended_human_killing',False)}
    proposal={'proposal_id':action_id,'kind':'power','statement_or_action':'Use '+WEAVES[wid]['name']+'.',
              'intent':'Apply the recorded '+mode+' effect.','details':details}
    ruling=adjudicate(actor,proposal)
    _require(ruling['result']=='ALLOW',ruling['public_reason'],'OATH_'+ruling['result'])
    m['oath_result']=public_view(ruling)
    if m.get('circle'):
        for rid in m['circle']['members']:
            if rid=='pc': continue
            member=state[rid]; mm=_meta(member); active=member.get('oaths_active')
            source=member.get('oaths_source_event') or ('genesis' if active is False else None)
            packet={'actor_id':rid,'oaths_active':active,'oaths_source_event':source,
                    'beliefs':member.get('beliefs',mm.get('oath_beliefs',[])),
                    'evidence':member.get('evidence',mm.get('oath_evidence',[]))}
            joint={'proposal_id':action_id,'kind':'circle','statement_or_action':proposal['statement_or_action'],
                   'intent':'Participate in the declared joint action.','details':{'joint_action':proposal}}
            participant=adjudicate(packet,joint)
            _require(participant['result']=='ALLOW',participant['public_reason'],'OATH_'+participant['result'])
            if 'private_oath_ruling' in member: member['private_oath_ruling']=participant


def _damage(state,target,amount):
    target['resistance']=max(0,target['resistance']-amount)
    if target['resistance']==0:
        bindings=[e for e in state['pc']['held'] if e['weave_id']=='W03' and state[e['target_id']] is target and e['binding_contribution']]
        if bindings: target['restrained']=True
        else: target['defeated']=True


def _effect(state,intent,action_id,band):
    p,w=state['pc'],state['world']; wid=intent['weave_id']; t=state[intent['target_id']]; m=_meta(t); card=WEAVES[wid]
    mode=intent.get('mode','utility'); now=w['time_seconds']
    if wid in ('W37','W38'):
        key=wid+':'+intent['target_id']; progress=p['magic']['progress'].get(key,0)
        progress=min(4,progress+(2 if band=='clean' else 1 if band=='costly' else 0)); p['magic']['progress'][key]=progress
        if wid=='W38':
            entry=next((e for e in p['held'] if e['weave_id']==wid and e['target_id']==intent['target_id']),None)
            if entry is None:
                entry=_instance(action_id,card,intent['target_id'],now); p['held'].append(entry)
                p['magic']['effects'][action_id]={'bonus_used':False,'transferred_ml':0,'started_at':now}
            if progress==4:
                m['shielded_by']=entry['id']; t['embraced']=False
                for victim in list(t.get('held',[])):
                    if victim['weave_id']=='W03': state[victim['target_id']]['restrained']=False
                t['held']=[]
        elif progress==4:
            _end_foreign(state,t); p['magic']['progress'].pop(key,None)
        return
    if band=='setback': return
    held_target=intent['material_id'] if wid=='W02' and mode=='attack' else intent['target_id']
    if card['held'] and not any(e['weave_id']==wid and e['target_id']==held_target for e in p['held']):
        area=intent.get('area_metres',m.get('area_metres',10)) if wid=='W04' else intent.get('area_metres',0)
        entry=_instance(action_id,card,held_target,now,area)
        p['held'].append(entry); p['magic']['effects'][action_id]={'bonus_used':False,'transferred_ml':0,'started_at':now,'barrier':4 if wid=='W23' else 0}
        if wid=='W14': p['magic']['effects'][action_id]['starting_distance_cm']=m['distance_moved_cm']
        if wid=='W04': p['magic']['effects'][action_id]['placed_location']=w['location']
    if mode=='attack':
        if wid=='W03':
            e=next(e for e in p['held'] if e['weave_id']==wid and e['target_id']==intent['target_id'])
            removed=min(2,t['resistance']); t['resistance']-=removed; e['binding_contribution']+=removed; t['restrained']=t['resistance']==0
        else: _damage(state,t,card['limits']['resistance'])
        return
    if wid=='W01': t['lit']=True
    elif wid=='W03': t['restrained']=True
    elif wid=='W06': t['vitality']=min(t['max_vitality'],t['vitality']+4); t['healing_used']=True
    elif wid=='W19': m['existing_air']=False
    elif wid=='W08': m['temperature_c']=min(50,m['temperature_c']+20)
    elif wid=='W09': m['temperature_c']=max(5,m['temperature_c']-20)
    elif wid=='W10': m['water_ml']=max(0,m['water_ml']-1000)
    elif wid=='W12': m['settled']=True
    elif wid=='W25': m['knotted']=False
    elif wid=='W26': m['loose']=True
    elif wid=='W27':
        found=[{'depth_cm':((v['depth_cm']+12)//25)*25} for v in m['voids'] if v['width_cm']>=10 and v['depth_cm']<=m['scan_depth_cm']]
        p['magic']['observation']={'weave_id':wid,'target_id':intent['target_id'],'voids':found,'scope':'Open cracks or voids only; no safety or contents claim.'}
    elif wid=='W28': m['mended']=True
    elif wid=='W29': m['hot']=True
    elif wid=='W32': m['pushed_metres']=m.get('pushed_metres',0)+1
    elif wid=='W35': m['cut']=True
    elif wid=='W36': t['lit']=False
    elif wid=='W39': m['treatment']={'remaining_seconds':86400,'started_at':now,'cast_id':action_id}
    elif wid=='W40':
        owner,e,collection=_active_weave(state,t)
        p['magic']['observation']={'load':e['load'],'holding':collection,
            'catalogue_id':e['weave_id'] if e['weave_id'] in p['known_weaves'] else None,
            'pattern':'known' if e['weave_id'] in p['known_weaves'] else 'unfamiliar',
            'remaining_minutes':max(0,(e['expires_at']-now+30)//60) if collection=='tied' else None}


def _cost(state,intent,band,uncertain,opponent,concentration,harm_fn):
    if not uncertain or band=='clean': return
    if opponent:
        foe=state[opponent]; harm_fn(state,foe['harm'],foe.get('harm_source','melee'),concentration)
    elif intent.get('cost','strain')=='strain': state[intent.get('cost_actor_id','pc')]['strain']+=1
    else: state['pc']['pending_work_seconds']+=600


def advance_effects(state,start,end):
    """Called after the clock advances. Resolve only previously declared effects."""
    p=state['pc']; m=p['magic']
    for entry in list(p['held']+p['tied']):
        if entry not in p['held']+p['tied']: continue
        if entry in p['held']:
            if entry['weave_id']=='W04' and m['effects'].get(entry['id'],{}).get('placed_location',state['world']['location'])!=state['world']['location']:
                p['held'].remove(entry); release_entry(state,entry); continue
            try: _target(state,entry['target_id'],WEAVES[entry['weave_id']]['range'])
            except RuleError:
                p['held'].remove(entry); release_entry(state,entry); continue
        card=WEAVES[entry['weave_id']]; data=m['effects'].setdefault(entry['id'],{'started_at':start,'transferred_ml':0,'bonus_used':False})
        upto=min(end,entry['expires_at']) if entry['expires_at'] is not None else end
        if entry['weave_id']=='W11':
            target=state[entry['target_id']]['magic']; elapsed=max(0,upto-data['started_at'])
            total=min(20000,elapsed*2000//60); amount=min(total-data.get('transferred_ml',0),target['water_ml'],target['container_ml']-target['received_ml'])
            amount=max(0,amount); target['water_ml']-=amount; target['received_ml']+=amount; data['transferred_ml']+=amount
        if entry['weave_id']=='W14':
            target=state[entry['target_id']]['magic']; elapsed=max(0,upto-data['started_at'])
            target['distance_moved_cm']=data.get('starting_distance_cm',0)+min(5000,elapsed*5000//600)
        if entry['expires_at'] is not None and entry['expires_at']<=end:
            (p['held'] if entry in p['held'] else p['tied']).remove(entry)
            release_entry(state,entry)
    pending=m['pending']
    if pending:
        pending['elapsed_seconds']+=end-start
        try:
            _validate_target(state,pending['weave_id'],pending['intent']['target_id'],pending['intent'].get('mode','utility'),pending['intent'])
        except RuleError:
            interrupt(state,'Required contact or range was lost.'); pending=None
    if pending:
        if state['world']['active_conflict'] or not p['embraced'] or p['vitality']==0:
            interrupt(state,'Conflict or incapacity interrupted casting.')
        else:
            if pending['elapsed_seconds']>=pending['required_seconds']:
                _require(pending['elapsed_seconds']==pending['required_seconds'],'Time crossed a pending cast decision.')
                frozen=deepcopy(pending); m['pending']=None
                _effect(state,frozen['intent'],frozen['id'],frozen['outcome'])
    # Foreign effects are authored records; expiry cannot generate an attack.
    for rid,actor in state.items():
        if rid!='pc' and 'held' in actor:
            actor['held']=[e for e in actor['held'] if e['expires_at'] is None or e['expires_at']>end]
            actor['tied']=[e for e in actor.get('tied',[]) if e['expires_at'] is None or e['expires_at']>end]
    for key in list(m['progress']):
        if key.startswith('W37:'):
            try: _active_weave(state,state[key[4:]])
            except RuleError:
                m['progress'].pop(key,None); m['progress_source'].pop(key,None)
    refresh(state)


def _cast(state,intent,action_id,advance,check,harm_fn):
    _closed(intent,('weave_id','target_id'),('mode','cost','area_metres','concentration','material_id','difficulty','allocation','cost_actor_id'))
    p,w=state['pc'],state['world']; wid=intent['weave_id']; caster=_caster(state); card=prerequisites(caster,wid)
    _require(p['embraced'] and not p['magic'].get('shielded_by'),'Embrace the Source without an active Shield first.')
    _require(p['pending_work_seconds']==0 and p['magic']['pending'] is None,'Finish outstanding casting or follow-up work first.')
    _require(intent.get('cost','strain') in ('strain','time'),'Choose strain or time as the utility cost.')
    mode=intent.get('mode','utility'); target=_validate_target(state,wid,intent['target_id'],mode,intent)
    _oaths(state,wid,target,mode,action_id)
    long=card['casting_seconds']>10
    _require(not long or (w['safe'] and not w['active_conflict']),'Establish a safe interval for a long cast.')
    held_target=intent['material_id'] if wid=='W02' and mode=='attack' else intent['target_id']
    same=next((e for e in p['held']+p['tied'] if e['weave_id']==wid and e['target_id']==held_target),None)
    reinforce=same is not None and (wid in ('W03','W38') or (wid=='W02' and mode=='attack'))
    _require(not same or reinforce,'The same weave cannot stack on one target.')
    _require(sum(e['load'] for e in p['held']+p['tied'])+(0 if reinforce else card['load'])<=_load_limit(state),'Insufficient free Load, including instant casts.')
    _require(not (card['held'] or long) or reinforce or len(p['held'])<_slot_limit(state),'No held slot available.')
    opponent=None
    if w['active_conflict']:
        opponent=intent['target_id'] if target.get('hostile') else w['magic'].get('opponent_id')
        _require(opponent in state and _integer(state[opponent].get('harm'),0,3),'Conflict cast needs a declared opponent Harm.')
    if mode=='attack': difficulty=target['guard']
    elif wid in ('W37','W38'):
        holder=_active_weave(state,target)[0] if wid=='W37' else target
        difficulty=14 if holder['control']<=2 else 16 if holder['control']==3 else 18
        if wid=='W38' and (holder['capacity']>caster['capacity'] or holder['embraced']): difficulty+=2
    else: difficulty=_meta(target).get('difficulty')
    _require(difficulty is None or _integer(difficulty,14,22),'Invalid authored casting difficulty.')
    if 'difficulty' in intent: _require(intent['difficulty']==difficulty and type(intent['difficulty']) is type(difficulty),'Difficulty comes from the authored scene.')
    if opponent and difficulty is None: difficulty=14
    if wid=='W37':
        progress_key=wid+':'+intent['target_id']; source=_active_weave(state,target)[1]['id']
        if p['magic']['progress_source'].get(progress_key)!=source:
            p['magic']['progress'].pop(progress_key,None); p['magic']['progress_source'][progress_key]=source
    track=p['magic']['progress'].get(wid+':'+intent['target_id'],0)
    attempt=digest({'weave':wid,'target':intent['target_id'],'mode':mode,'scene':w['scene_id'],
                    'method':p['magic']['methods'].get(wid+':'+intent['target_id'],0),'progress':track,
                    'target_state':{k:v for k,v in target.items() if k not in ('magic','location')}})
    _require(attempt not in p['magic']['attempts'],'A failed unchanged method needs preparation or changed circumstances.')
    extra=1 if difficulty is not None and not opponent and intent.get('cost','strain')=='strain' else 0
    allocation=_allocation(state,intent,card['load'])
    cost_actor=intent.get('cost_actor_id','pc')
    _require(cost_actor in allocation, 'Counter-cost payer must be a participating member.')
    for rid,amount in allocation.items():
        actor=state[rid]; _require(actor['strain']+amount+(extra if rid==cost_actor else 0)<=2*actor['capacity'], 'Cannot afford every declared Strain outcome.')
    for rid,amount in allocation.items(): state[rid]['strain']+=amount
    if wid=='W31': _meta(target)['water_ml']-=1000
    if wid=='W34':
        material=state[intent['material_id']]['magic']; material['available']=False; material['impact_target']=intent['target_id']
    fatigue=any(amount>0 and state[rid]['strain']>state[rid]['capacity'] for rid,amount in allocation.items())
    roller=state[p['magic']['circle']['leader_id']] if p['magic'].get('circle') else p
    spec=None if difficulty is None else check(roller,'will','channeling',difficulty+(2 if fatigue else 0))
    # Opening action belongs to the long duration, never adds a second cast cost.
    advance(state,10)
    branches={}
    for band in BANDS:
        result=deepcopy(state); q=result['pc']; effective='clean' if spec is None else band
        if effective=='setback': q['magic']['attempts'].append(attempt)
        if long:
            q['magic']['pending']={'id':action_id,'weave_id':wid,'intent':deepcopy(intent),
                'started_at':w['time_seconds']-10,'required_seconds':card['casting_seconds'],
                'elapsed_seconds':10,'outcome':effective}
        else: _effect(result,intent,action_id,effective)
        _cost(result,intent,effective,spec is not None,opponent,intent.get('concentration','drop'),harm_fn)
        refresh(result); branches[band]=result
    summaries=None
    if long:
        summaries={band:'Begin the cast, reserve its Load and slot, and freeze this technique result. The effect waits for uninterrupted completion; listed costs are already spent.' for band in BANDS}
    return spec,branches,'Use '+card['name']+'.','Apply the published form to '+intent['target_id']+'.',summaries


def _continuation_seconds(state,requested,maximum):
    _require(_integer(requested,1,maximum),'Invalid continuation duration.')
    deadline=state['world'].get('next_event_second'); now=state['world']['time_seconds']
    bounds=[requested,maximum]
    if deadline is not None: bounds.append(deadline-now)
    pending=state['pc']['magic'].get('pending')
    if pending and pending['weave_id']=='W40':
        try:
            entry=_active_weave(state,state[pending['intent']['target_id']])[1]
            if entry['expires_at'] is not None: bounds.append(entry['expires_at']-now)
        except RuleError: return 0
    return min(bounds)


def resolve(state,intent,action_id,*,advance,check,harm):
    """Return (check, branches, goal, method, summaries), mutating only this clone."""
    verb=intent['verb']; p,w=state['pc'],state['world']; goal='Use the declared magic operation.'
    if verb=='cast': return _cast(state,intent,action_id,advance,check,harm)
    if verb=='oath_defence': return _oath_defence(state,intent,action_id)
    if verb in ('circle_train','companion_embrace','circle_form','circle_end','attune_angreal','remove_angreal'):
        return _advanced_operation(state,intent,action_id,advance)
    if verb=='embrace':
        _closed(intent); _require(not p['embraced'] and not p['magic'].get('shielded_by'),'The Source is already held or blocked.')
        _require(p['vitality']>0,'An incapacitated character cannot embrace.')
        p['embraced']=True
        if w['active_conflict']:
            opponent=w['magic'].get('opponent_id'); _require(opponent in state,'Embracing under attack needs a published opponent.')
            foe=state[opponent]; _require(_integer(foe.get('guard'),1,22) and _integer(foe.get('harm'),0,3),'Missing declared defence stakes.')
            spec=check(p,'grace','athletics',foe['guard']); advance(state,10); branches={}
            for band in BANDS:
                result=deepcopy(state); amount=0 if band=='clean' else foe['harm']//2 if band=='costly' else foe['harm']
                harm(result,amount,foe.get('harm_source','melee'),'drop'); refresh(result); branches[band]=result
            return spec,branches,'Embrace the Source while defending.','Use Grace and Athletics against the published Guard; take zero, half rounded down, or full Harm.',None
        advance(state,10); goal='Embrace the Source.'
    elif verb=='release':
        _closed(intent,optional=('held_id',)); key=intent.get('held_id')
        _require(key is None or any(e['id']==key for e in p['held']) or (p['magic']['pending'] and p['magic']['pending']['id']==key),'Unknown held or pending weave.')
        drop(state,key)
        if key is None:
            p['embraced']=False; _end_circle(state)
        goal='Release the declared held effects.'
    elif verb in ('tie','untie'):
        _closed(intent,('held_id',) if verb=='tie' else ('tied_id',))
        _require(w['safe'] and not w['active_conflict'],'Tying needs a safe interval.')
        collection=p['held'] if verb=='tie' else p['tied']; key=intent.get('held_id',intent.get('tied_id'))
        e=next((e for e in collection if e['id']==key),None); _require(e is not None,'Unknown weave instance.')
        if verb=='tie':
            _require(p['magic'].get('circle') is None, 'Circle weaves cannot be tied.')
            _require(sum(x['load'] for x in p['tied'])+e['load']<=p['capacity'], 'Tied Load cannot depend on an angreal.')
            _require(p['control']>=3 and WEAVES[e['weave_id']]['tying'],'This weave cannot be tied.')
            _require(len(p['tied'])<p['control'] and p['strain']<2*p['capacity'],'Cannot afford tying.')
            p['strain']+=1; collection.remove(e); e['expires_at']=w['time_seconds']+3610; p['tied'].append(e)
        else:
            _target(state,e['target_id'],WEAVES[e['weave_id']]['range']); release_entry(state,e); collection.remove(e)
        advance(state,10)
    elif verb=='continue_cast':
        _closed(intent,optional=('seconds',)); pending=p['magic']['pending']; _require(pending is not None,'No pending cast remains.')
        remaining=pending['required_seconds']-pending['elapsed_seconds']
        seconds=_continuation_seconds(state,intent.get('seconds',remaining),remaining)
        _require(seconds>0,'Resolve the due world event first.'); advance(state,seconds,allow_boundary=True)
        goal='Continue the same frozen cast without another roll.'
    elif verb=='magic_prepare':
        _closed(intent,('weave_id','target_id')); prerequisites(p,intent['weave_id'])
        _require(w['safe'] and not w['active_conflict'],'Preparation requires a safe interval.')
        _require(intent['target_id'] in state,'Unknown practice target.')
        key=intent['weave_id']+':'+intent['target_id']; advance(state,600)
        if intent['target_id']=='magic-practice': _configure_practice(state,intent['weave_id'])
        p['magic']['methods'][key]=p['magic']['methods'].get(key,0)+1
        goal='Prepare a changed method with a source or ordinary care plan.'
    elif verb in ('move','magic_use'):
        return _use(state,intent,action_id,advance,check,harm)
    elif verb=='treatment_recovery':
        _closed(intent,('target_id','seconds')); t=state[intent['target_id']]; m=_meta(t); treatment=m.get('treatment')
        _require(treatment is not None and w['safe'] and not w['active_conflict'],'Recovery needs pending treatment and a safe interval.')
        _require(t.get('location')==w['location'],'The patient is elsewhere.')
        seconds=_continuation_seconds(state,intent['seconds'],min(28800,treatment['remaining_seconds']))
        _require(seconds>0,'Resolve the due event first.'); advance(state,seconds,allow_boundary=True)
        treatment['remaining_seconds']-=seconds
        if treatment['remaining_seconds']==0:
            t['wounds']=max(0,t['wounds']-1); m['treatment']=None; m['treatment_completed_at']=w['time_seconds']
            # The healed Wound cannot donate prior ordinary-care credit to a
            # later injury with the same numerical Wound count.
            p.get('life',{}).get('recovery',{}).pop(intent['target_id'],None)
        goal='Advance only this patient recovery obligation.'
    elif verb=='shield_struggle':
        return _struggle(state,intent,action_id,advance,check,harm)
    else: raise RuleError('Unsupported magic verb.')
    refresh(state)
    return None,None,goal,'Apply only the recorded numerical costs and effects.',None


def _use(state,intent,action_id,advance,check,harm_fn):
    """House interpretation: timed manipulation under attack includes defence.

    A successful defence retains the manipulation. A setback changes no
    discrete target; already running effects still consume elapsed time.
    Passive falls and closure impacts remain authored consequences in all bands.
    """
    if not state['world']['active_conflict'] or intent.get('operation')=='bonus':
        return _use_routine(state,intent,action_id,advance,check,harm_fn)
    opponent=state['world']['magic'].get('opponent_id')
    _require(opponent in state, 'Manipulation under attack needs a published opponent.')
    foe=state[opponent]
    _require(_integer(foe.get('guard'),1,22) and _integer(foe.get('harm'),0,3), 'Missing declared defence stakes.')
    _require(intent.get('operation')!='fall', 'A fall during conflict must come from an authored harm event; prepared Catch applies there.')
    if intent.get('operation')=='continue':
        _require(intent.get('seconds',10)==10 and type(intent.get('seconds',10)) is int, 'Maintain an effect for one ten-second exchange.')
        intent={**intent,'seconds':10}
    spec=check(state['pc'],'grace','athletics',foe['guard'])
    successful=deepcopy(state)
    _use_routine(successful,intent,action_id,advance,check,harm_fn)
    _require(successful['world']['time_seconds']-state['world']['time_seconds']==10, 'A timed use under attack must consume one exchange.')
    advance(state,10)
    branches={}
    passive=intent.get('operation') in ('continue','fall','absorb')
    for band in BANDS:
        result=deepcopy(successful if band!='setback' or passive else state)
        amount=0 if band=='clean' else foe['harm']//2 if band=='costly' else foe['harm']
        harm_fn(result,amount,foe.get('harm_source','melee'),'drop')
        refresh(result); branches[band]=result
    summaries={band:('Retain the existing manipulation.' if band!='setback' or passive else 'The discrete manipulation fails; existing effects continue.')+
               (' Avoid the enemy harm.' if band=='clean' else ' Apply half enemy Harm, rounded down.' if band=='costly' else ' Apply full enemy Harm.') for band in BANDS}
    return spec,branches,'Manipulate an existing effect while defending.','One Grace plus Athletics defence; no new casting cost. Passive effects continue during the exchange.',summaries


def _use_routine(state,intent,action_id,advance,check,harm_fn):
    _closed(intent,('held_id','operation'),('distance_metres','direction','seconds','message','skill_id','amount','mass_grams'))
    p=state['pc']; entry=next((e for e in p['held']+p['tied'] if e['id']==intent['held_id']),None)
    _require(entry is not None,'Unknown active weave.'); wid=entry['weave_id']; t=_target(state,entry['target_id'],WEAVES[wid]['range']); m=_meta(t)
    data=p['magic']['effects'].setdefault(entry['id'],{'bonus_used':False,'started_at':state['world']['time_seconds'],'transferred_ml':0})
    op=intent['operation']
    if wid=='W02':
        if op=='retrieve':
            distance=intent.get('distance_metres',2); _require(_integer(distance,1,2),'Air Hand moves at most2m per action.')
            t['distance_m']=max(0,t['distance_m']-distance)
        elif op in ('open','close'):
            _require(t.get('simple_latch') is True,'A simple exposed latch is required.'); t['open']=op=='open'
        else: raise RuleError('Unsupported Air Hand operation.')
        advance(state,10)
    elif wid in ('W11','W14') and op=='continue':
        remaining=entry['expires_at']-state['world']['time_seconds']
        seconds=_continuation_seconds(state,intent.get('seconds',remaining),remaining)
        _require(seconds>0,'The effect has ended.')
        _require(not state['world']['active_conflict'] or seconds<=10,'Continue an effect for at most one exchange during conflict.')
        advance(state,seconds,allow_boundary=True)
    elif wid in BONUSES and op=='bonus':
        _require(not data['bonus_used'] and intent.get('skill_id') in BONUSES[wid],'This one-use bonus is unavailable.')
        _require(p.get('support_pending') is None,'Use or cancel existing support first.')
        data['bonus_used']=True; p['support_pending']={'ally_id':entry['id'],'skill_id':intent['skill_id']}
    elif wid=='W16' and op=='speak':
        text=intent.get('message'); _require(type(text) is str and 0<len(text)<=1000,'A spoken message is required.')
        _require(not p['oaths_active'],'Oath-bound free text needs an authored meaning before speech.','OATH_CLARIFY')
        m['messages'].append(text); advance(state,10)
    elif wid=='W20' and op=='fall':
        amount=m.get('fall_harm'); _require(_integer(amount,0,6),'The fall Harm must be authored before this action.')
        reduced=max(0,amount-3); drop(state,entry['id']); advance(state,10)
        if entry['target_id']=='pc': harm_fn(state,reduced,'fall','drop')
        elif 'vitality' in t: _harm_other(state,entry['target_id'],reduced,'fall')
    elif wid=='W21' and op=='cross':
        _require(_integer(intent.get('mass_grams',70000),1,120000),'Crossing load exceeds120kg.')
        _require(entry['expires_at'] is None or entry['expires_at']>=state['world']['time_seconds']+10, 'The bridge would expire during this crossing.')
        advance(state,10); m['crossings']+=1
    elif wid=='W22' and op in ('raise','lower'):
        height=m['height_metres']+(1 if op=='raise' else -1); _require(0<=height<=3,'Platform height must stay within0–3m.')
        m['height_metres']=height; advance(state,10)
    elif wid=='W23' and op=='absorb':
        amount=m.get('declared_harm'); _require(_integer(amount,1,6),'Barrier harm must be authored for this exchange.')
        absorbed=min(data['barrier'],amount); data['barrier']-=absorbed; m['closure_harm']+=amount-absorbed
        if data['barrier']==0: drop(state,entry['id'])
        advance(state,10)
    elif wid=='W04' and op=='crossing':
        raise RuleError('A boundary crossing must come from an authored world event.','WORLD_EVENT_REQUIRED')
    else: raise RuleError('Unsupported operation for this weave.')
    refresh(state)
    return None,None,'Use '+WEAVES[wid]['name']+'.','Apply the stated existing effect without a second cast cost.',None


def boundary_crossing(state, target_id='world', *, location=None):
    """World-event hook. A crossing gives no identity, motive, or free reaction."""
    location=state['world']['location'] if location is None else location
    wards=[e for e in state['pc']['held']+state['pc']['tied'] if e['weave_id']=='W04' and e['target_id']==target_id
           and state['pc']['magic']['effects'].get(e['id'],{}).get('placed_location',state['world']['location'])==location]
    if wards:
        state['pc']['warning_ready']=True
        state['pc']['magic']['observation']={'warning':'A physical creature crossed the ward boundary.'}
    refresh(state)


def _configure_practice(state,wid):
    _require(wid not in ('W03','W05','W06','W19','W20','W38','W39'), 'This form needs a real consenting person or ordinary patient; use their record.')
    _require(state['world']['supplied'] and state['world']['library_available'] and state['magic-practice']['location']==state['world']['location'], 'Replenishing a practice object requires its supplied institutional workroom.')
    records=_fixture_records(state['world']['location']); template=records['magic-'+wid]
    target=state['magic-practice']; original_keys=set(target); base={}
    for item in records.values():
        for key,value in item.items(): base.setdefault(key,deepcopy(value))
    base.update(deepcopy(template)); base['magic']['configured_weave']=wid
    if wid in ('W33','W34'):
        base['kind']='object'; base['magic']['inert_target']=True
    if wid in ('W37','W40'):
        mentor=state.get('npc-mentor'); _require(mentor is not None and mentor.get('willing') and mentor.get('location')==state['world']['location'], 'A willing present tutor must demonstrate this pattern.')
        cost=2 if wid=='W37' else 3
        _require(mentor['strain']+cost<=2*mentor['capacity'], 'The tutor needs ordinary rest before another demonstration.')
        _require(not mentor['held'] and not mentor['tied'], 'The tutor already maintains a demonstration.')
        mentor['strain']+=cost; mentor['embraced']=True
        form='W05' if wid=='W37' else 'W04'; collection='held' if wid=='W37' else 'tied'
        entry=_instance('practice-demonstration',WEAVES[form],'npc-mentor',state['world']['time_seconds'])
        if collection=='tied': entry['expires_at']=state['world']['time_seconds']+3600
        mentor[collection].append(entry)
        base['magic']={'owner_id':'npc-mentor','instance_id':entry['id'],'configured_weave':wid,'difficulty':None}
    target.clear(); target.update(base)
    _require(set(target)==original_keys, 'Practice fields changed.')


def _circle_members(state):
    circle=state['pc']['magic'].get('circle')
    return circle['members'] if circle else ['pc']


def _oath_defence(state,intent,action_id):
    """House interpretation: player declares belief about an observed threat.

    Typed compiled threat facts grant no automatic belief or shared NPC belief.
    The declaration spends no time and supplies no new action authority.
    """
    _closed(intent,('target_id','believes_extreme_peril'))
    choice=intent['believes_extreme_peril']
    _require(type(choice) is bool, 'Declare a Boolean belief about extreme peril.')
    rid=intent['target_id']; w=state['world']; p=state['pc']; m=p['magic']
    _require(w['active_conflict'] and state.get('conflict',{}).get('target_id')==rid, 'This declaration concerns the current published opponent.')
    target=_target(state,rid,20); threat=target.get('threat')
    _require(type(threat) is dict and set(threat)=={'source_action','observer_id','immediate_lethal_threat','description'} and
             threat['observer_id']=='pc' and threat['immediate_lethal_threat'] is True,
             'The scene supplies no directly observed immediate threat to your life.')
    _require(type(threat['source_action']) is str and type(threat['description']) is str, 'The authored observation needs its source event.')
    proposition='self-peril-'+rid
    prior=[b for b in m['oath_beliefs'] if b['proposition_id']==proposition]
    old_ids={e for b in prior for e in b['evidence_ids']}
    m['oath_beliefs']=[b for b in m['oath_beliefs'] if b['proposition_id']!=proposition]
    retained={e for b in m['oath_beliefs'] for e in b['evidence_ids']}
    m['oath_evidence']=[e for e in m['oath_evidence'] if e['evidence_id'] not in old_ids or e['evidence_id'] in retained]
    suffix=digest({'target':rid,'source':threat['source_action']})[:24]
    evidence_id='threat-'+suffix
    m['oath_evidence'].append({'evidence_id':evidence_id,'basis':'observation',
        'statement':threat['description'],'source_event':threat['source_action'],'audience_ids':['pc']})
    m['oath_beliefs'].append({'belief_id':'belief-'+suffix,'proposition_id':proposition,
        'value':choice,'evidence_ids':[evidence_id]})
    _meta(target)['oath_context']={'source_action':threat['source_action'],
        'danger':{'threat_proposition_id':proposition,'protected_person':'self',
                  'relationship_proposition_id':None,'extreme':choice}}
    m['oath_result']=None
    refresh(state)
    return None,None,'Record your belief about the observed threat.', 'This explicit personal belief consumes no time; it does not decide any other actor’s belief.',None


def _load_limit(state):
    p=state['pc']; circle=p['magic'].get('circle')
    if circle: return min(12,max(state[r]['capacity'] for r in circle['members'])+2*(len(circle['members'])-1))
    return p['capacity']+(2 if p['magic'].get('angreal_id') else 0)


def _slot_limit(state):
    circle=state['pc']['magic'].get('circle')
    return state[circle['leader_id']]['control'] if circle else state['pc']['control']


def _caster(state):
    circle=state['pc']['magic'].get('circle')
    if circle:
        actor=deepcopy(state[circle['leader_id']])
        actor['flows']={f:max(state[r]['flows'][f] for r in circle['members']) for f in actor['flows']}
        return actor
    return state['pc']


def _allocation(state,intent,load):
    members=_circle_members(state)
    allocation=intent.get('allocation',{'pc':load})
    _require(type(allocation) is dict and set(allocation)<=set(members) and all(_integer(v,0,load) for v in allocation.values()) and sum(allocation.values())==load,'Declare whole-point Strain allocation among circle members.')
    return {rid:allocation.get(rid,0) for rid in members}


def _end_circle(state):
    circle=state['pc']['magic'].get('circle')
    if circle:
        drop(state)
        for rid in circle['members']:
            if rid!='pc': _meta(state[rid])['circle_id']=None
        state['pc']['magic']['circle']=None
    refresh(state)


def circle_member_harm(state,member_id,amount,source,concentration='drop'):
    """Authored harm hook. Members retain individual Vitality and Strain limits."""
    _require(member_id in _circle_members(state),'The injured actor is not in this circle.')
    if member_id=='pc':
        harm(state,amount,source,concentration)
        if state['pc']['vitality']==0: _end_circle(state)
        return
    amount=_prevent_harm(state,member_id,amount,source)
    if amount==0: return
    actor=state[member_id]; actor['vitality']=max(0,actor['vitality']-amount)
    if actor['vitality']==0:
        actor['wounds']=min(3,actor['wounds']+1); actor['embraced']=False; _end_circle(state)
    elif amount and (state['pc']['held'] or state['pc']['magic']['pending']):
        if concentration=='preserve':
            _require(actor['strain']<2*actor['capacity'],'The injured member cannot afford concentration.')
            actor['strain']+=1
        else:
            entries=state['pc']['held']+([state['pc']['magic']['pending']] if state['pc']['magic']['pending'] else [])
            key=entries[0]['id'] if concentration=='drop' else concentration
            _require(any(e['id']==key for e in entries),'Unknown circle concentration choice.')
            drop(state,key)
    refresh(state)


def _harm_other(state,target_id,amount,source):
    """Settle authored non-player harm, including the same fall protection."""
    if target_id in _circle_members(state):
        circle_member_harm(state,target_id,amount,source)
        return
    actor=state[target_id]; amount=_prevent_harm(state,target_id,amount,source)
    if amount==0 or actor['vitality']==0: return
    actor['vitality']=max(0,actor['vitality']-amount)
    incapacitated=actor['vitality']==0
    if incapacitated:
        actor['wounds']=min(3,actor.get('wounds',0)+1)
        if 'embraced' in actor: actor['embraced']=False
    # The default concentration response drops one owned effect; falling ends all.
    released=list(actor.get('held',[])) if incapacitated else list(actor.get('held',[]))[:1]
    for entry in released:
        victim=state[entry['target_id']]
        if entry['weave_id']=='W03':
            victim['restrained']=False
            if 'resistance' in victim and not victim.get('defeated',False):
                victim['resistance']=min(victim['max_resistance'],victim['resistance']+entry['binding_contribution'])
        if entry['weave_id']=='W38': _meta(victim)['shielded_by']=None
        actor['held'].remove(entry)


def _advanced_operation(state,intent,action_id,advance):
    p,w=state['pc'],state['world']; m=p['magic']; verb=intent['verb']
    if verb=='circle_train':
        _closed(intent,optional=('companions',))
        _require(w['safe'] and not w['active_conflict'] and w['library_available'],'Circle instruction needs a safe ordinary teaching source.')
        _require(not m['circle'] and not p['held'] and not p['tied'],'Release commitments before a full instruction day.')
        companions=intent.get('companions',[])
        _require(type(companions) is list and len(set(companions))==len(companions) and len(companions)<=2,'Choose at most two distinct companions.')
        for rid in companions:
            actor=_target(state,rid,5)
            _require(rid!='pc' and actor.get('willing') and actor.get('consenting') and 'flows' in actor,'Instruction needs willing channelers.')
        training=m.get('circle_training') or {'companions':list(companions),'seconds':0}
        _require(training['companions']==companions,'Resume instruction with the same participating students.')
        remaining=28800-training['seconds']
        if 'region' in w:
            from .regional import advance_activity
            result=advance_activity(state,remaining,'study',advance_clock=advance)
            elapsed=result['credited_seconds']
        else:
            day=str(w['time_seconds']//86400)
            _require(day not in w['main_activity'],'This day already has a main activity.')
            w['main_activity'][day]={'kind':'study','seconds':remaining}
            advance(state,remaining); elapsed=remaining
        training['seconds']+=elapsed; m['circle_training']=training
        if training['seconds']==28800:
            m['circle_trained']=True
            for rid in companions: _meta(state[rid])['circle_trained']=True
    elif verb=='companion_embrace':
        _closed(intent,('target_id',))
        _require(w['safe'] and not w['active_conflict'], 'Ask the companion during a safe interval.')
        rid=intent['target_id']; actor=_target(state,rid,5); am=_meta(actor)
        _require(rid!='pc' and actor.get('willing') and actor.get('consenting'), 'The companion must willingly consent.')
        _require(am.get('power_side')=='saidar' and am.get('circle_trained'), 'The companion needs the supported circle training.')
        _require(actor.get('vitality',0)>0 and not actor.get('embraced') and not am.get('shielded_by') and not am.get('circle_id'), 'The companion cannot embrace in this condition.')
        advance(state,10); actor['embraced']=True
    elif verb=='circle_form':
        _closed(intent,('member_ids',),('leader_id',))
        _require(w['safe'] and not w['active_conflict'], 'Form the supported circle during a safe interval.')
        members=intent['member_ids']
        _require(type(members) is list and 2<=len(members)<=3 and len(set(members))==len(members) and 'pc' in members,'A supported circle has two or three distinct willing members including you.')
        leader=intent.get('leader_id','pc'); _require(leader in members,'The leader must be a member.')
        _require(m['circle'] is None and m['pending'] is None,'An existing circle or pending cast must end first.')
        for rid in members:
            actor=_target(state,rid,5); am=_meta(actor)
            _require(am.get('power_side')=='saidar' and am.get('circle_trained') and actor.get('embraced'),'Each member must be trained and embrace saidar.')
            _require(rid=='pc' or (actor.get('willing') and actor.get('consenting')),'Circle consent is required.')
            _require(not actor.get('held') and not actor.get('tied') and not am.get('angreal_id'),'Release individual Load and angreal before linking.')
            _require(_integer(actor.get('strain'),0,2*actor['capacity']) and actor['vitality']>0,'A member cannot join in this condition.')
        advance(state,10*len(members))
        m['circle']={'id':action_id,'members':list(members),'leader_id':leader}
        for rid in members:
            if rid!='pc': _meta(state[rid])['circle_id']=action_id
    elif verb=='circle_end':
        _closed(intent); _require(m['circle'] is not None,'No circle is active.'); _end_circle(state)
    elif verb=='attune_angreal':
        _closed(intent,('target_id',)); item=_target(state,intent['target_id'],0)
        _require(w['safe'] and not w['active_conflict'] and m['circle'] is None,'Attunement needs a safe hour outside a circle.')
        _require(not m['angreal_id'] and _meta(item).get('angreal_bonus')==2 and _meta(item).get('loan_permitted'),'One authorized supported angreal may be used.')
        _require(_meta(item).get('attuned_to') in (None,'pc'),'The item is attuned to someone else.')
        advance(state,3600); m['angreal_id']=intent['target_id']; _meta(item)['attuned_to']='pc'; _meta(item)['carried_by']='pc'
    else:
        _closed(intent,optional=('release_ids',)); _require(m['angreal_id'] is not None,'No angreal is active.')
        releases=intent.get('release_ids',[])
        _require(type(releases) is list and len(set(releases))==len(releases) and set(releases)<={e['id'] for e in p['held']},'Choose existing held effects to release.')
        for key in releases: drop(state,key)
        _require(sum(e['load'] for e in p['held']+p['tied'])<=p['capacity'],'Choose enough held effects to fit natural Capacity before removal.')
        _meta(state[m['angreal_id']])['attuned_to']=None; _meta(state[m['angreal_id']])['carried_by']=None; m['angreal_id']=None
    refresh(state)
    return None,None,'Complete '+verb.replace('_',' ')+'.','Use the supported house-rule operation with its exact time and natural resource limits.',None


def _struggle(state,intent,action_id,advance,check,harm_fn):
    _closed(intent,optional=('cost','concentration'))
    p,w=state['pc'],state['world']; shield=p['magic'].get('shielded_by')
    _require(shield is not None,'No Shield currently blocks the character.')
    owners=[(rid,a,e) for rid,a in state.items() for e in a.get('held',[])
            if e['id']==shield and e['weave_id']=='W38' and e['target_id']=='pc']
    _require(len(owners)==1,'The Shield needs exactly one recorded holder.')
    rid,owner,entry=owners[0]
    difficulty=(14 if owner['control']<=2 else 16 if owner['control']==3 else 18)+(2 if owner['capacity']>p['capacity'] else 0)
    _require(intent.get('cost','strain') in ('strain','time'),'Choose a declared struggle cost.')
    opponent=rid if w['active_conflict'] else None
    if opponent: _require(_integer(owner.get('harm'),0,3),'Conflict struggle needs declared opposing Harm.')
    elif intent.get('cost','strain')=='strain': _require(p['strain']<2*p['capacity'],'Cannot afford the declared struggle cost.')
    spec=check(p,'will','channeling',difficulty); advance(state,10); branches={}
    for band in BANDS:
        result=deepcopy(state); q=result['pc']; key='struggle:'+shield
        progress=min(4,q['magic']['progress'].get(key,0)+(2 if band=='clean' else 1 if band=='costly' else 0))
        q['magic']['progress'][key]=progress
        if progress==4:
            result[rid]['held']=[e for e in result[rid]['held'] if e['id']!=shield]
            q['magic']['shielded_by']=None; q['magic']['progress'].pop(key,None)
        _cost(result,intent,band,True,opponent,intent.get('concentration','drop'),harm_fn)
        refresh(result); branches[band]=result
    return spec,branches,'Struggle free of the held Shield.','Make progress without casting or a base Strain charge.',None
