"""Additive, public campaign preparation, committed through the action journal.

These records are campaign inventions, not verified canon or mechanical grants.
No general JSON patch, character editing, hidden information, or retcon endpoint.
"""
from copy import deepcopy

from .world_schema import ID, TEXT, NAME, variant, _text, _id
from . import challenges

CHANGE = {'anyOf': [
    variant('place', {'id': ID, 'name': NAME, 'description': TEXT}),
    variant('route', {'from': ID, 'to': ID, 'seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}}),
    variant('object', {'id': ID, 'name': NAME, 'location': ID,
                      'weight_kg': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 5}}),
    variant('person', {'id': ID, 'name': NAME, 'location': ID, 'description': TEXT}),
    variant('fact', {'id': ID, 'text': TEXT}),
    challenges.DEFINITION,
]}
CHANGES = {'type': 'array', 'minItems': 1, 'maxItems': 12, 'items': CHANGE}


def resolve(state, command):
    from . import sandbox
    sandbox.validate(state)
    if type(command) is not dict or set(command) != {'op', 'changes'} or command['op'] != 'establish':
        raise ValueError('Use an establish command containing only changes.')
    changes = command['changes']
    if type(changes) is not list or not 1 <= len(changes) <= 12:
        raise ValueError('Establish between one and twelve public world records together.')
    out = deepcopy(state)
    box = out['world']['sandbox']
    places = box.setdefault('places', deepcopy(sandbox.PLACES))
    people = box.setdefault('people', {})
    facts = box.setdefault('facts', {})
    checks = box.setdefault('challenges', {})
    labels = []
    for change in changes:
        if type(change) is not dict:
            raise ValueError('Each world record must be a structured object.')
        kind = change.get('kind')
        schema = next((s for s in CHANGE['anyOf'] if s['properties']['kind']['const'] == kind), None)
        if schema is None or set(change) != set(schema['required']):
            raise ValueError('Use the exact schema for a place, route, object, person, fact or challenge.')
        for key in ('id', 'location', 'from', 'to'):
            if key in change: _id(change[key])
        for key in ('name', 'description', 'text'):
            if key in change: _text(change[key], 100 if key == 'name' else 1000)
        if kind == 'route':
            a, b, seconds = change['from'], change['to'], change['seconds']
            if a not in places or b not in places or a == b:
                raise ValueError('A route must join two different established places.')
            if type(seconds) is not int or not 1 <= seconds <= 3600:
                raise ValueError('Route time must be 1–3600 seconds.')
            if b in places[a]['exits'] or a in places[b]['exits']:
                raise ValueError('An established route cannot be overwritten.')
            places[a]['exits'][b] = seconds
            places[b]['exits'][a] = seconds
            labels.append('route '+a+' ↔ '+b)
            continue
        id = change['id']
        if id == 'inventory' or any(id in records for records in (places, box['objects'], people, facts, checks)):
            raise ValueError('That identifier is already established or reserved; do not overwrite it.')
        if 'location' in change and change['location'] not in places:
            raise ValueError('Place new objects and people in an established location, never directly in inventory.')
        if 'name' in change:
            names = [state['identity']['name'], *state['resources']['inventory']]
            names += [record['name'] for records in (places, box['objects'], people, checks) for record in records.values()]
            if change['name'].casefold() in {n.casefold() for n in names}:
                raise ValueError('Use a distinct name; existing character and object identities must be preserved.')
        provenance = {'provenance': 'campaign_invention'}
        if kind == 'place':
            places[id] = {'name': change['name'], 'description': change['description'], 'exits': {}, **provenance}
        elif kind == 'object':
            weight = change['weight_kg']
            if type(weight) not in (int, float) or not 0 < weight <= 5:
                raise ValueError('Ordinary props must weigh more than zero and no more than 5 kg.')
            box['objects'][id] = {'name': change['name'], 'location': change['location'], 'portable': True,
                'weight_kg': weight, 'elevated': False, 'lit': False, 'dry_fuel': False, **provenance}
        elif kind == 'person':
            people[id] = {k: change[k] for k in ('name', 'location', 'description')} | provenance
        elif kind == 'challenge':
            challenges.validate_definition(out, change)
            checks[id] = deepcopy(change) | provenance
        else:
            facts[id] = {'text': change['text'], **provenance}
        labels.append(kind+' '+id)
    if len(places) > 100 or len(box['objects']) > 200 or len(people) > 100 or len(facts) > 300 or len(checks) > 200:
        raise ValueError('This sandbox has reached its world-record capacity.')
    sandbox.validate(out)
    return {'state': out, 'narration': 'Established public campaign records: '+', '.join(labels)+'. No time or character resources changed.',
            'elapsed_seconds': 0, 'roll': None}


def choice(state, command):
    from .store import digest
    result = resolve(state, command)
    return {'id': 'establish:'+digest(command), 'label': 'Establish public world records',
            'description': result['narration'], 'stakes': 'Preparation only. No time, resources, abilities or player decisions change.',
            'requires_roll': False, 'command': deepcopy(command)}
