"""Authoritative full-content-v1 house-rule weave cards; not canonical recipes."""
from copy import deepcopy
from .rules import RuleError

# ID, name, Control, Flow minima, Load, metres, held, cast seconds, duration, tying, profile.
_ROWS = [
('W01','Spark',1,{'fire':1},1,10,False,10,None,False,'U/A'),
('W02','Air Hand',1,{'air':1},1,10,True,10,None,False,'U/A'),
('W03','Air Binding',2,{'air':2,'spirit':1},2,10,True,10,None,False,'U/A'),
('W04','Warning Ward',2,{'spirit':2,'air':1},2,10,True,10,None,True,'U'),
('W05','Elemental Guard',2,{'air':2,'earth':1,'fire':1,'water':1},2,5,True,10,None,True,'U'),
('W06','Healing',3,{'water':2,'spirit':2,'air':1},3,0,False,10,None,False,'U'),
('W07','Lamp',1,{'air':1,'fire':1},1,5,True,10,None,True,'U'),
('W08','Warming',1,{'fire':1},1,0,False,60,None,False,'U'),
('W09','Cooling',1,{'water':1,'fire':1},1,0,False,60,None,False,'U'),
('W10','Drying',1,{'air':1,'water':1},1,2,False,600,None,False,'U'),
('W11','Draw Water',1,{'air':1,'water':1},1,10,True,10,600,False,'U'),
('W12','Settling Water',1,{'earth':1,'water':1},1,0,False,600,None,False,'U'),
('W13','Air Sieve',2,{'air':2,'earth':1},2,5,True,10,600,False,'U'),
('W14','Sail Breeze',2,{'air':2},2,10,True,10,600,False,'U'),
('W15','Quiet Pocket',2,{'air':2,'spirit':1},2,0,True,10,600,False,'U'),
('W16','Carry Voice',1,{'air':1,'spirit':1},1,60,True,10,60,False,'U'),
('W17','Close Lens',2,{'air':1,'fire':1},1,1,True,10,600,False,'U'),
('W18','Far Lens',2,{'air':2,'fire':1},2,500,True,10,600,False,'U'),
('W19','Air Pocket',3,{'air':2,'water':2},3,0,True,10,60,False,'U'),
('W20','Catch',2,{'air':2,'water':1},2,5,True,10,60,False,'U'),
('W21','Short Bridge',2,{'air':2,'earth':1},2,5,True,10,600,False,'U'),
('W22','Lifting Platform',3,{'air':2,'earth':2},3,10,True,10,60,False,'U'),
('W23','Door Brace',2,{'air':2,'earth':1},2,5,True,10,600,False,'U'),
('W24','Weather Screen',2,{'air':2,'water':2},2,5,True,10,3600,False,'U'),
('W25','Gentle Unknotting',2,{'air':2,'spirit':1},1,0,False,60,None,False,'U'),
('W26','Loosen Earth',2,{'earth':2},2,0,False,600,None,False,'U'),
('W27','Stone Probe',2,{'earth':2,'spirit':1},2,0,False,60,None,False,'I'),
('W28','Mend Stone',3,{'earth':2,'fire':1},3,0,False,3600,None,False,'U'),
('W29','Forge Heat',3,{'earth':2,'fire':2},3,2,True,10,3600,False,'U'),
('W30','Water Brake',3,{'air':2,'water':2},3,10,True,10,60,False,'U'),
('W31','Steam Veil',2,{'air':1,'fire':1,'water':1},2,10,True,10,60,False,'U'),
('W32','Air Stroke',2,{'air':2},2,15,False,10,None,False,'U/A'),
('W33','Flame Dart',2,{'air':1,'fire':2},2,20,False,10,None,False,'A'),
('W34','Stone Shot',2,{'air':1,'earth':2},2,20,False,10,None,False,'A'),
('W35','Air Blade',3,{'air':2,'fire':1},3,5,False,10,None,False,'U/A'),
('W36','Dampen Flame',3,{'fire':2,'water':2},3,10,False,10,None,False,'U'),
('W37','Disrupt Weave',3,{'air':2,'spirit':2},3,10,False,10,None,False,'P'),
('W38','Shield',3,{'spirit':2},3,10,True,10,None,False,'P'),
('W39','Wound Treatment',4,dict.fromkeys(('air','earth','fire','water','spirit'),2),4,0,False,3600,None,False,'U'),
('W40','Read a Weave',3,{'spirit':2},2,5,False,60,None,False,'I'),
]
_LIMITS = {
'W01':{'resistance':1,'hand_sized_tinder':True},
'W02':{'mass_grams':5000,'metres_per_action':2,'resistance':1},
'W03':{'resistance':2,'ordinary_person':True},
'W04':{'area_metres':10,'bonus':2}, 'W05':{'harm_reduction':1},
'W06':{'vitality':4,'uses_per_patient_rest':1}, 'W07':{'light_radius_metres':5},
'W08':{'water_ml':10000,'object_mass_grams':1000,'temperature_change_c':20,'maximum_c':50},
'W09':{'water_ml':10000,'object_mass_grams':1000,'temperature_change_c':20,'minimum_c':5},
'W10':{'fabric_grams':2000,'water_ml':1000},
'W11':{'water_ml':20000,'ml_per_minute':2000,'rise_metres':5},
'W12':{'water_ml':20000}, 'W13':{'area_metres':3,'bonus':2},
'W14':{'occupants':4,'distance_metres':50}, 'W15':{'area_metres':2,'bonus':2},
'W16':{'audible_radius_metres':3}, 'W17':{'magnification':4,'bonus':2},
'W18':{'minimum_object_metres':1,'bonus':2}, 'W19':{'depth_metres':2,'air_seconds':60},
'W20':{'mass_grams':120000,'fall_metres':5,'harm_reduction':3},
'W21':{'gap_metres':3,'width_metres':1,'mass_grams':120000},
'W22':{'area_metres':2,'mass_grams':150000,'metres_per_action':1,'height_metres':3},
'W23':{'door_metres':2,'barrier':4}, 'W24':{'area_metres':3,'bonus':2},
'W25':{'visible_knot':True}, 'W26':{'soil_litres':250},
'W27':{'depth_cm':100,'minimum_void_cm':10,'resolution_cm':25},
'W28':{'mass_grams':10000}, 'W29':{'metal_grams':1000},
'W30':{'area_metres':5,'bonus':2}, 'W31':{'water_ml':1000,'area_metres':3,'bonus':2},
'W32':{'resistance':2,'mass_grams':25000,'push_metres':1},
'W33':{'resistance':2}, 'W34':{'resistance':2,'pebble_grams':100},
'W35':{'resistance':3,'rope_mm':20}, 'W36':{'fire_metres':2},
'W37':{'progress_required':4,'clean_progress':2,'costly_progress':1},
'W38':{'progress_required':4,'clean_progress':2,'costly_progress':1,'source_or_capacity_penalty':2},
'W39':{'wounds':1,'recovery_seconds':86400,'cooldown_seconds':604800},
'W40':{'duration_round_seconds':60},
}
WEAVES = {}
for row in _ROWS:
    key,name,control,flows,load,range_m,held,casting,duration,tying,profile = row
    WEAVES[key] = dict(weave_id=key,name=name,control=control,flows=flows,load=load,
        range=range_m,held=held,casting_seconds=casting,max_duration_seconds=duration,
        tying=tying,profile=profile,known_prerequisites=['W06'] if key=='W39' else [],
        limits=_LIMITS[key],version=1,source_class='campaign_invention',
        source='weave-catalogue.md#'+key.lower(),availability='950-NE-house-rule')


def prerequisites(pc, weave_id, require_known=True):
    if weave_id not in WEAVES:
        raise RuleError('Unknown weave.', 'UNSUPPORTED_WEAVE')
    card = WEAVES[weave_id]
    if require_known and weave_id not in pc['known_weaves']:
        raise RuleError('Learn this weave first.')
    if pc['control'] < card['control'] or any(pc['flows'][f] < v for f,v in card['flows'].items()):
        raise RuleError('The Control or Flow prerequisite is not met.')
    if any(w not in pc['known_weaves'] for w in card['known_prerequisites']):
        raise RuleError('A prerequisite weave has not been learned.')
    return deepcopy(card)
