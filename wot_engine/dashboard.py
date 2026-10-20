"""Human-readable dashboard derived only from released public records."""
from .player import journal, choice_list


def safe(value):
    text=str(value).replace('\n',' ')
    for character in ('\\','`','*','_','[',']','<','>','|'):
        text=text.replace(character,'\\'+character)
    return text


def render(controller):
    packet=controller.public_packet()
    p,w=packet['player'],packet['world']
    day,second=divmod(w['time_seconds'],86400)
    hour,second=divmod(second,3600)
    minute=second//60
    lines=['# White Tower', '', f"**{safe(p['name'])}** · {safe(p['rank'].replace('_',' '))} · Level {p['level']}", '',
           f"Day {day+1} since arrival, {hour:02}:{minute:02} · {safe(w['location'])}", '',
           f"Save status: **{safe(packet['status']['status'])}**. Only released records appear here.", '',
           '## Current scene', '', safe(w['scene_description']), '', '## Choices', '']
    for item in choice_list(controller):
        lines.append(f"{item['number']}. {safe(item['label'])}")
    lines += ['', 'You may describe a different intention. Read the stakes before a consequential action.', '',
              '## Character', '', '| Resource | Current |', '|---|---:|',
              f"| Vitality | {p['vitality']} / {p['max_vitality']} |", f"| Wounds | {p['wounds']} / 3 |",
              f"| Strain | {p['strain']} / {2*p['capacity']} |", f"| Capacity | {p['capacity']} |",
              f"| Control | {p['control']} |", f"| Supply | {p['supply']} / 6 |", f"| Silver | {p['silver']} |", '',
              'Flows: '+', '.join(f"{key.title()} {value}" for key,value in p['flows'].items())+'.', '',
              'Known weaves: '+', '.join(safe(x) for x in p['known_weaves'])+'.', '']
    if p.get('identity'):
        lines += ['Personal aim: '+safe(p['identity']['personal_aim']), '',
                  'Outside relationship: '+safe(p['identity']['outside_relationship']), '',
                  'Obligation: '+safe(p['identity']['obligation']), '']
    if 'training' in w:
        training=w['training']
        lines += ['## Training', '', f"Chapter {training['chapter']['number']} · {safe(training['chapter']['stage'])}", '',
                  f"Banked General Points: {p['general_points']}. Channel Points: {p['channel_points']}. Learning opportunities: {p['learning_opportunities']}.", '',
                  '| Review | Remaining requirements |', '|---|---|']
        for kind,review in training['readiness'].items():
            lines.append('| '+safe(kind)+' | '+('Ready' if review['ready'] else safe(', '.join(review['missing'])))+' |')
        lines += ['', '| Current study | Progress |', '|---|---|']
        current=[(key,value) for key,value in training['courses'].items() if value['status'] not in ('not_started','mastered')]
        for key,value in current:
            lines.append(f"| {safe(key)} | {value['days']} days + {value['partial_seconds']} seconds / {value['required_days']} days; {safe(value['status'])} |")
        if not current: lines.append('| No unfinished course | Choose a course through the training view. |')
        lines.append('')
    lines += ['## People', '', '| Name | Role | Bond | Support remaining |', '|---|---|---:|---:|']
    for npc in packet['npcs'].values():
        lines.append(f"| {safe(npc['name'])} | {safe(npc['role'])} | {npc['bond']} | {npc['support_remaining']} |")
    lines += ['', '## Recent journal', '']
    for entry in journal(controller,5):
        lines += [f"**{entry['sequence']}. {safe(entry['goal'])}**", '', safe(entry['narration']), '',
                  f"Receipt: {safe(entry['receipt_id'])}", '']
    if not journal(controller,1): lines += ['No released actions yet.', '']
    lines += ['## Save reference', '', f"Campaign: {safe(packet['campaign_id'])}", '',
              f"Projected head: `{packet['head_hash']}`", '',
              f"Projected event sequence: {packet['sequence']}", '',
              'This dashboard is a projection. The committed event history remains authoritative.', '']
    return '\n'.join(lines)
