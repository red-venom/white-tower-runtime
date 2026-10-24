"""A second authored chapter, continuing the same disposable character.

No model calls, new character creation, hidden social rolls or invented PC speech.
The original gallery episode remains in the save unchanged.
"""
from copy import deepcopy
import re

TITLE = 'A Seat in the Garden'
KEY = 'garden_chapter'
OBJECTIVE = 'Choose how to spend a free half-hour with your fellow novices. You may keep an invitation private, welcome company, or spend the interval alone.'


def active(state):
    return KEY in state['world']['episode']


def can_start(state):
    e, c = state['world']['episode'], state['channeling']
    return e['completed'] and not active(state) and not (c['embraced'] or c['held_weaves'] or c['pending_cast'])


def next_start(state):
    now = state['clock']['fictional_seconds']
    start = now // 86400 * 86400 + 15 * 3600
    return start if now < start else start + 86400


def _choice(id, label, description, stakes):
    return {'id': id, 'label': label, 'description': description, 'stakes': stakes, 'requires_roll': False}


def start_choice(state):
    target = next_start(state)
    day = target // 86400 + 1
    return _choice('next_chapter', 'Continue with the same character',
        'Begin A Seat in the Garden at your next free afternoon. The letter chapter stays finished; your character, learning and memories carry forward.',
        f'Move to Day {day}, 15:00. No roll, training, recovery, resource change or promise is implied. Release any held workings first.')


def validate(state):
    e = state['world']['episode']; g = e[KEY]
    if not e['completed'] or g['stage'] not in ('arrival', 'complete') or type(g['heard']) is not bool:
        raise ValueError('Invalid connected chapter.')
    if type(g['started_at']) is not int or type(g['ends_at']) is not int or g['ends_at'] != g['started_at'] + 1800:
        raise ValueError('Invalid free interval.')
    if not g['started_at'] <= state['clock']['fictional_seconds'] <= g['ends_at']:
        raise ValueError('The chapter clock is outside its interval.')
    if (g['stage'] == 'complete') != (g['result'] is not None):
        raise ValueError('Invalid chapter outcome.')


def start(state):
    if not can_start(state):
        raise ValueError('Finish the current chapter and release active channeling first.')
    result = deepcopy(state); now = next_start(state)
    if state['clock']['fictional_seconds'] // 86400 != now // 86400:
        result['clock']['day_activity_seconds'] = 0
    result['clock']['fictional_seconds'] = now
    result['world']['episode'][KEY] = {'stage':'arrival', 'heard':False, 'result':None,
        'started_at':now, 'ends_at':now+1800, 'summary':None}
    result['world'].update(location='White Tower garden terrace', scene=TITLE)
    if not any(n['id']=='nera' for n in result['world']['npcs']):
        result['world']['npcs'].append({'id':'nera','name':'Nera','role':'Novice',
            'known':'A new novice. She has come to the garden with a cup of tea and a sketchbook.', 'memories':[]})
    validate(result)
    return {'state':result, 'narration':story(result), 'roll':None,
            'elapsed_seconds':now-state['clock']['fictional_seconds']}


def choices(state):
    validate(state); g=state['world']['episode'][KEY]
    if g['stage']=='complete':
        if state['clock']['fictional_seconds'] < g['ends_at']:
            minutes=(g['ends_at']-state['clock']['fictional_seconds'])//60
            return [_choice('garden_finish','Enjoy the rest of your free interval',
                'Let the conversation end. No further errand or test follows.',f'{minutes} minutes; no roll, recovery, reward or new obligation. Ends this chapter.')]
        return []
    out=[]
    if not g['heard']:
        out.append(_choice('garden_listen','Hear them out',
            'Listen through the whole exchange, until there is something for you to decide.',
            '2 minutes; no roll. This does not choose your reply or commit you to either invitation.'))
    out.extend([
        _choice('garden_private','Keep the conversation with Lysa private',
            'Accept time with Lysa without asking her to share her letter or including another person.',
            '20 minutes; no roll or resource cost. Nera finds another seat. No promise about tomorrow is made.'),
        _choice('garden_welcome','Make room for both of them',
            'Invite Nera to join you and Lysa. Let them choose what they want to share.',
            '20 minutes; no roll or resource cost. A shared conversation replaces the private one; nobody has to disclose a letter.'),
        _choice('garden_nera','Spend the interval with Nera',
            'Take the spare seat near the newcomer and give her company while she sketches.',
            '20 minutes; no roll or resource cost. Lysa keeps her own quiet time; you take on no future duty.'),
        _choice('garden_alone','Choose some time alone',
            'Decline both invitations and take the quiet end of the terrace.',
            'Use the remaining free interval; no roll, penalty, recovery or reward. Ends this chapter.'),
    ])
    return out


def story(state):
    g=state['world']['episode'][KEY]
    if g['stage']=='complete':
        return g['summary']
    if g['heard']:
        return ('Lysa rests a hand on the folded letter. ‘Nothing terrible. I just wanted to sit with someone who already knows me.’ '
                'She glances towards Nera. ‘But I needn\'t read it aloud.’\n\n'
                '‘I can sit over there,’ Nera says, lifting her sketchbook. ‘I was only wondering whether anyone minds being drawn.’ '
                'She does not start without an answer. The two invitations are different; neither novice needs rescuing. They leave the choice to you.')
    returned=state['world']['episode']['result']=='letter_returned'
    lead=('Lysa recognises you before you reach the terrace and raises a hand. The letter you returned is tucked safely into her notebook.'
          if returned else 'Lysa raises a hand from a terrace bench. Her letter is tucked safely into her notebook; the porter dealt with the earlier search. She makes no complaint about your choice.')
    return (lead+'\n\n‘There is room here, if you want it.’ She moves her cup aside. This is a free half-hour, with no practice to demonstrate and no errand waiting.\n\n'
            'At the next table, Nera turns a sketchbook over when she notices you. ‘Would either of you like some company?’ '
            'Lysa pauses, her fingers still on the folded letter. You can keep your conversation private, make a place for Nera, or choose time of your own.')


def resolve(state, choice_id, dice=None):
    if dice not in (None, []):
        raise ValueError('No dice are required for this conversation.')
    if choice_id not in {c['id'] for c in choices(state)}:
        raise ValueError('This approach is not available in the current chapter.')
    out=deepcopy(state);g=out['world']['episode'][KEY];seconds=0
    def remember(who,fact):
        n=next(n for n in out['world']['npcs'] if n['id']==who)
        if fact not in n['memories']:n['memories'].append(fact)
    if choice_id=='garden_listen':
        g['heard']=True;seconds=120;narration=story(out)
    elif choice_id=='garden_finish':
        seconds=g['ends_at']-out['clock']['fictional_seconds']
        narration='The rest of the interval passes without another request. Cups are gathered and the terrace grows quiet. This chapter is finished; nothing else is required to earn its ending.'
        g['summary'] += '\n\nThe free interval has ended.'
    else:
        seconds=g['ends_at']-out['clock']['fictional_seconds'] if choice_id=='garden_alone' else 1200
        endings={
          'garden_private': ('Lysa moves to the quieter end of the bench with you. Nera settles at the next table and opens her sketchbook.\n\n'
            'Lysa talks about the ordinary things her mother writes: a repaired gate, a neighbour\'s wedding, a younger brother who has begun signing his whole name. She laughs at that last part, then folds the page away. You have given her company without taking possession of her private story.\n\n'
            'Twenty minutes later she gathers her cup. ‘Thank you for sitting with me.’ She sets the cup on the tray and watches a sparrow work its way along the terrace rail.', 'Shared a private conversation in the garden without reading her letter.'),
          'garden_welcome': ('Lysa puts her letter away before Nera joins you. ‘The tea is better before it goes cold,’ she says, making room for the third cup.\n\n'
            'Nera shows a drawing of the terrace rail. One upright is much too tall; Lysa insists it looks like a particularly severe tutor, and Nera laughs before she can stop herself. The talk moves through garden paths and the small surprises of living in the Tower.\n\n'
            'After twenty minutes, Nera closes the book. ‘I\'ll know where to sit next time.’ Lysa shifts her cup away from the pencils before Nera can knock it over.', 'Welcomed Nera into a shared garden conversation.'),
          'garden_nera': ('Lysa settles with her letter while you take a seat near Nera. Nera turns the book so you can see the terrace rather than drawing you without permission.\n\n'
            'She talks as she works: the difficulty of making a curved leaf look alive, the good light at this table, the way the garden is easier to learn than the corridors. She asks what brought you out today, leaving you free to answer in your own words or simply enjoy the company.\n\n'
            'Twenty minutes later she shows you the finished leaf. ‘Better than the first one.’ She packs the pencils away. The shared activity is finished, with no favour owed.', 'Spent a quiet garden interval with Nera while she sketched.'),
          'garden_alone': ('Lysa nods and returns to her letter. Nera finds a place to sketch. Neither follows you with another request.\n\n'
            'At the quiet end of the terrace, leaves move against the stone rail and the cups clink faintly behind you. The rest of your free half-hour passes undisturbed.\n\n'
            'The interval is finished. You have lost no standing, resources or progress by choosing it for yourself.', 'Respected your choice to spend the free interval alone.'),
        }
        narration,memory=endings[choice_id]
        g.update(stage='complete',result=choice_id,summary=narration)
        targets={'garden_private':['lysa'],'garden_welcome':['lysa','nera'],'garden_nera':['nera'],'garden_alone':['lysa','nera']}
        for who in targets[choice_id]:remember(who,memory)
    out['clock']['fictional_seconds']+=seconds
    validate(out)
    return {'state':out,'narration':narration,'roll':None,'elapsed_seconds':seconds}


def view(state):
    validate(state);g=state['world']['episode'][KEY]
    return {'title':TITLE,'story':story(state),'objective':OBJECTIVE,'choices':choices(state),
        'status':'complete' if g['stage']=='complete' else 'in_progress',
        'completed':g['stage']=='complete','result':g['result'],
        'chapter':{'number':2,'previous_title':'The Letter in the Gallery','previous_completed':True}}


def interpret(state, text):
    available={c['id']:c for c in choices(state)}
    if '?' in text or re.match(r'^(what|why|how|can|could|would|should|is|do|does)\b',text):
        if re.search(r'\b(weave|air|spark|channel|saidar)\b',text):
            return {'kind':'answer','message':'This is free time without a tutor supervising practice. Your known weaves are preserved, but no casting action is available here.','choice_id':None}
        return {'kind':'answer','message':story(state)+'\n\nAvailable now: '+('; '.join(c['label'] for c in available.values()) or 'This chapter is finished.') ,'choice_id':None}
    patterns={
        'garden_listen':r'(?:listen|hear them out|listen to them|remain quiet|watch quietly)',
        'garden_private':r'(?:sit|talk|spend time) (?:privately )?with lysa(?: privately)?|keep (?:the )?conversation private',
        'garden_welcome':r'invite nera(?: to join us)?|make room for (?:both|everyone)|welcome nera',
        'garden_nera':r'(?:sit|spend time) with nera',
        'garden_alone':r'(?:spend|choose|take) (?:some )?time alone|decline both invitations',
        'garden_finish':r'enjoy the rest of (?:the|my) (?:free )?interval|finish the interval',
    }
    command=re.sub(r'^(?:i |she |elin )','',text).rstrip('.! ')
    for id,pattern in patterns.items():
        if id in available and re.fullmatch(pattern,command):
            return {'kind':'proposal','message':available[id]['description'],'choice_id':id}
    return {'kind':'clarify','message':'No action taken. Choose one of the available approaches, or ask about the scene. This authored chapter does not supply arbitrary speech for your character.','choice_id':None}
