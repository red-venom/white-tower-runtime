"""Explicit player-authored identity and legal creation choices.

Free text is biography, never an instruction or an NPC knowledge grant.
No character is chosen for the player by generating the blank template.
"""
from copy import deepcopy
from .contracts import require, normalize, canonical

ATTRIBUTES = ('body', 'grace', 'wits', 'will', 'presence')
SKILLS = ('athletics','melee','marksmanship','stealth','survival','notice',
          'scholarship','medicine','persuasion','insight','leadership','composure')
FLOWS = ('air','earth','fire','water','spirit')


def template():
    skills = dict.fromkeys(SKILLS, 0)
    skills.update(scholarship=2, composure=2, melee=1, notice=1, medicine=1, persuasion=1)
    return {'schema':'character-v1', 'name':None, 'age':None,
            'identity':'woman', 'power_side':'saidar', 'origin':None,
            'prior_skill':None, 'outside_relationship':None, 'obligation':None,
            'personal_aim':None,
            'attributes':dict(zip(ATTRIBUTES,(1,1,2,2,0))), 'skills':skills,
            'starting_flow':'air'}


def validate(profile):
    normalize(profile)
    require(type(profile) is dict and set(profile) == set(template()), 'Use the complete character-v1 template.')
    require(profile['schema'] == 'character-v1', 'Unknown character schema.')
    for key, maximum in (('name',120),('origin',240),('outside_relationship',480),
                         ('obligation',480),('personal_aim',480)):
        require(type(profile[key]) is str and 1 <= len(profile[key].strip()) <= maximum,
                'Choose '+key.replace('_',' ')+'.')
    require(type(profile['age']) is int and 18 <= profile['age'] <= 2**53-1,
            'Choose an adult age for the new novice (18 or older).')
    require(profile['identity'] == 'woman' and profile['power_side'] == 'saidar',
            'This campaign module follows an adult woman who channels saidar.')
    for key, names, values in (('attributes',ATTRIBUTES,[0,1,1,2,2]),
                                ('skills',SKILLS,[0]*6+[1]*4+[2]*2)):
        ratings = profile[key]
        require(type(ratings) is dict and set(ratings)==set(names) and
                all(type(x) is int for x in ratings.values()) and sorted(ratings.values())==values,
                'Assign the published starting '+key+' ratings.')
    require(profile['starting_flow'] in FLOWS, 'Choose one starting Flow at 2.')
    require(profile['prior_skill'] in SKILLS and profile['skills'][profile['prior_skill']] > 0,
            'Choose a rated Skill from life before the Tower; it uses the existing Skill allocation.')
    require(len(canonical(profile)) <= 3072,
            'Keep the complete character profile within 3 KiB so its saved public sheet remains portable.')
    return True


def configure(state, profile):
    """Return a configured genesis; never rewrite a running character."""
    validate(profile)
    require(state['world']['time_seconds'] == 0 and state['pc']['level'] == 1 and
            state['pc']['rank'] == 'novice' and state['progression']['chapter']['completed'] == 0,
            'Identity choices belong to new character creation.')
    result = deepcopy(state)
    p = result['pc']
    p['name'] = profile['name'].strip()
    p['attributes'] = deepcopy(profile['attributes'])
    p['skills'] = deepcopy(profile['skills'])
    p['flows'] = {key: 2 if key==profile['starting_flow'] else 1 for key in FLOWS}
    p['max_vitality'] = p['vitality'] = 6+2*p['attributes']['body']
    p['identity'] = {key: deepcopy(profile[key]) for key in
                     ('age','identity','power_side','origin','prior_skill','outside_relationship','obligation','personal_aim')}
    return result
