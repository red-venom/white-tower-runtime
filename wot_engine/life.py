"""Ordinary recovery and paid work on the shared, bounded activity clock.

House default for mixed care: one completed cared day earns7/21 of one Wound;
an uncared day earns3/21. Partial8h cycles retain time and their selected care
regime. Surplus never advances the next Wound. No equipment prices are invented.
"""
from copy import deepcopy
from .rules import RuleError, _require, _integer
from .regional import advance_activity, next_boundary, WORK_DAY

VERBS={'recover_wound','paid_work'}


def initialize(state):
    state['pc']['life']={'recovery':{},'work_seconds':0,'earned_silver':0,'last_activity':None}
    state['world']['life']={'paid_work_available':True,'institutional_care_available':True}


def handles(intent):
    return type(intent) is dict and intent.get('verb') in VERBS


def _closed(intent,required=(),optional=()):
    _require(type(intent) is dict and set(intent)<={'verb',*required,*optional} and set(required)<=set(intent),'Unknown or missing life intent fields.')
    for key in ('target_id','care','carer_id'):
        if key in intent: _require(type(intent[key]) is str,'Invalid life option.')
    _require(_integer(intent.get('seconds',WORK_DAY),1,WORK_DAY),'Choose1–28,800 seconds of activity.')


def _safe(state):
    p,w=state['pc'],state['world']
    _require(w['safe'] and not w['active_conflict'],'Find a safe interval first.')
    _require(not p['held'] and not p['tied'] and not p.get('magic',{}).get('pending') and not p.get('magic',{}).get('circle'),'End committed magic before a main recovery or work activity.')
    _require(p['pending_work_seconds']==0,'Finish the declared follow-up work first.')


def _patient(state,target_id):
    _require(target_id in state,'Unknown patient.')
    patient=state[target_id]
    if target_id!='pc':
        _require(patient.get('kind')=='person' and patient.get('alive') is True,'Ordinary recovery needs a living person.')
        _require(patient.get('location')==state['world']['location'] and patient.get('visible'),'The patient is elsewhere.')
        _require(patient.get('consenting') or patient.get('vitality')==0,'The patient has not consented.')
    _require(_integer(patient.get('wounds'),1,3),'The patient has no Wound to recover.')
    _require(not patient.get('magic',{}).get('treatment'),'A W39 treatment already owns this recovery time.')
    return patient


def _care_source(state,intent):
    mode=intent.get('care','alone')
    _require(mode in ('institutional','companion','alone'),'Unknown ordinary care source.')
    if mode=='institutional':
        w=state['world']
        _require('carer_id' not in intent,'Institutional care does not require a particular ally.')
        _require(w['life']['institutional_care_available'] and w['supplied'] and w.get('region',{}).get('location_id')=='infirmary','Institutional care is available in the supplied infirmary.')
        return True,None
    if mode=='companion':
        rid=intent.get('carer_id'); _require(rid in state and rid!='pc','Choose a present consenting carer.')
        actor=state[rid]
        _require(actor.get('kind')=='person' and actor.get('willing') and actor.get('visible') and actor.get('location')==state['world']['location'],'The carer must be willing and present.')
        _require('medicine' in actor.get('competences',[]) and actor.get('vitality',0)>0,'The carer needs the stated competence and capacity.')
        _require(not actor.get('magic',{}).get('circle_id'),'A linked participant cannot also provide care.')
        return True,rid
    _require('carer_id' not in intent,'Alone recovery has no carer.')
    return False,None


def _new_recovery(wounds):
    return {'wounds_observed':wounds,'credit_units':0,'cycle_seconds':0,
            'cycle_cared':None,'paid_carers':[],'completed_cared_days':0,'completed_alone_days':0}


def resolve(state,intent,action_id,*,advance,check,harm):
    """Routine actions; the dispatcher freezes all resulting time and resources."""
    _safe(state); p,w=state['pc'],state['world']; life=p['life']
    if intent['verb']=='paid_work':
        _closed(intent,optional=('seconds',))
        _require(w['supplied'] and w['life']['paid_work_available'],'Safe institutional paid work is not available here.')
        _require(p['wounds']<3,'Three Wounds require recovery before paid work.')
        requested=intent.get('seconds',WORK_DAY)
        result=advance_activity(state,requested,'work',advance_clock=advance)
        total=life['work_seconds']+result['credited_seconds']; coins,remaining=divmod(total,WORK_DAY)
        life['work_seconds']=remaining; life['earned_silver']+=coins; p['silver']+=coins
        goal='Complete ordinary paid work.'
        method='Earn one silver per completed8h of credited work. Interrupted credit remains; no advancement is awarded.'
    elif intent['verb']=='recover_wound':
        _closed(intent,optional=('target_id','care','carer_id','seconds'))
        target_id=intent.get('target_id','pc'); patient=_patient(state,target_id); cared,carer=_care_source(state,intent)
        entry=life['recovery'].setdefault(target_id,_new_recovery(patient['wounds']))
        # Another completed treatment already healed the active Wound.
        if patient['wounds']<entry['wounds_observed']:
            entry=_new_recovery(patient['wounds']); life['recovery'][target_id]=entry
        entry['wounds_observed']=patient['wounds']
        _require(entry['cycle_cared'] is None or entry['cycle_cared']==cared,'Finish this interrupted8h cycle with its selected care regime.')
        if entry['cycle_cared'] is None: entry['cycle_cared']=cared
        if carer is not None and carer not in entry['paid_carers']:
            _require(_integer(state[carer].get('support_remaining'),1,2),'The carer needs a remaining support use.')
            state[carer]['support_remaining']-=1; entry['paid_carers'].append(carer)
        requested=min(intent.get('seconds',WORK_DAY),WORK_DAY-entry['cycle_seconds'])
        if carer is not None and 'private_state' in state[carer]:
            available=state[carer]['private_state']['resources']['work_seconds']
            _require(available>0, 'The carer needs a full safe rest before further work.')
            requested=min(requested,available)
        result=advance_activity(state,requested,'recovery',advance_clock=advance)
        if carer is not None and 'private_state' in state[carer]:
            state[carer]['private_state']['resources']['work_seconds']-=result['credited_seconds']
        entry['cycle_seconds']+=result['credited_seconds']
        if entry['cycle_seconds']==WORK_DAY:
            entry['credit_units']+=7 if cared else 3
            entry['completed_cared_days']+=int(cared); entry['completed_alone_days']+=int(not cared)
            entry.update(cycle_seconds=0,cycle_cared=None,paid_carers=[])
            if entry['credit_units']>=21:
                patient['wounds']-=1
                # The next Wound starts from zero even after mixed-care surplus.
                life['recovery'][target_id]=_new_recovery(patient['wounds'])
        goal='Recover one Wound through ordinary rest and care.'
        method='Use exclusive8h main-activity recovery days: three with care or seven alone. Retain interrupted credit; never double-count W39.'
    else: raise RuleError('Unsupported life operation.')
    life['last_activity']={'action_id':action_id,'kind':intent['verb'],
                           'seconds':result['elapsed_seconds'],'stop_reason':result['stop_reason']}
    validate(state)
    return None,None,goal,method,None


def validate(state):
    life=state['pc']['life']
    _require(set(life)=={'recovery','work_seconds','earned_silver','last_activity'},'Invalid life fields.')
    _require(_integer(life['work_seconds'],0,WORK_DAY-1) and _integer(life['earned_silver']),'Invalid work credit.')
    _require(type(life['recovery']) is dict and len(life['recovery'])<=len(state),'Invalid patient ledger.')
    for rid,entry in life['recovery'].items():
        _require(rid in state and set(entry)==set(_new_recovery(0)),'Invalid recovery entry.')
        _require(_integer(entry['wounds_observed'],0,3) and _integer(entry['credit_units'],0,20) and _integer(entry['cycle_seconds'],0,WORK_DAY-1),'Invalid recovery credit.')
        _require(entry['cycle_cared'] is None or type(entry['cycle_cared']) is bool,'Invalid care regime.')
        _require((entry['cycle_seconds']==0)==(entry['cycle_cared'] is None),'Incomplete recovery cycle state.')
        _require(len(entry['paid_carers'])==len(set(entry['paid_carers'])) and all(x in state for x in entry['paid_carers']),'Invalid care contributors.')
        _require(_integer(entry['completed_cared_days']) and _integer(entry['completed_alone_days']),'Invalid completed recovery days.')
    return True


def public_view(state):
    return deepcopy(state['pc']['life'])


def available_choices(state):
    p,w=state['pc'],state['world']; result=[]
    if p['vitality']==0 or not w['safe'] or w['active_conflict'] or p['held'] or p['tied'] or p['pending_work_seconds'] or p.get('magic',{}).get('pending') or p.get('magic',{}).get('circle'): return result
    boundary=next_boundary(state,WORK_DAY)
    ledger=w['main_activity']; current=ledger['day']==w['time_seconds']//86400
    used=ledger['used_seconds'] if current else 0
    recovery=ledger['by_kind']['recovery'] if current else 0
    seconds=min(boundary['elapsed_seconds'],WORK_DAY-used)
    if seconds<=0: return result
    if w['supplied'] and w['life']['paid_work_available'] and p['wounds']<3 and recovery==0:
        result.append({'id':'life-work','label':'Do safe paid work; one silver per8h.','intent':{'verb':'paid_work','seconds':seconds}})
    if p['wounds'] and not p.get('magic',{}).get('treatment') and used==recovery:
        entry=p['life']['recovery'].get('pc',{}); selected=entry.get('cycle_cared')
        if selected is not True:
            result.append({'id':'life-recover-alone','label':'Continue ordinary Wound recovery without a carer.','intent':{'verb':'recover_wound','care':'alone','seconds':seconds}})
        if selected is not False and w.get('region',{}).get('location_id')=='infirmary' and w['supplied'] and w['life']['institutional_care_available']:
            result.append({'id':'life-recover-care','label':'Use ordinary infirmary care for Wound recovery.','intent':{'verb':'recover_wound','care':'institutional','seconds':seconds}})
    return result
