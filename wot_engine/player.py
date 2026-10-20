"""Read-only player commands, built from released records and public projections."""
from copy import deepcopy

from .contracts import parse_json, require, digest


def journal(controller, limit=20):
    require(type(limit) is int and 1 <= limit <= 100, "Invalid journal limit")
    with controller.store.locked() as db:
        rows = db.execute("SELECT envelope_json,receipt_id FROM actions WHERE phase='DELIVERED' ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in reversed(rows):
            envelope = parse_json(row[0])
            event, action = envelope["event"], envelope["accepted_action"]
            check = action["stakes"]["check"]
            dice = [r["value"] for r in event["dice"]]
            roll = None if check is None else {
                "dice": dice, "attribute": check["attribute"], "attribute_rating": check["attribute_rating"],
                "skill": check["skill_id"], "skill_rating": check["skill_rating"], "modifier": check["modifier"],
                "difficulty": check["difficulty"],
                "total": sum(dice) + check["attribute_rating"] + check["skill_rating"] + check["modifier"],
            }
            result.append({"action_id": event["action_id"], "sequence": event["sequence"],
                           "goal": action["stakes"]["goal"], "outcome": event["outcome"],
                           "narration": event["public_narration"], "roll": roll, "receipt_id": row[1]})
        return result


def query(controller, command):
    """Every query consumes zero fictional time and performs no remote mutation."""
    packet = controller.public_packet()
    player, world = packet["player"], packet["world"]
    base = {"campaign_id": packet["campaign_id"], "head_hash": packet["head_hash"],
            "time_seconds": world["time_seconds"], "save_status": packet["status"]}
    if command == "sheet":
        return {**base, "character": deepcopy(player)}
    if command == "recap":
        return {**base, "location": world["location"], "scene": world["scene_description"],
                "choices": deepcopy(world["choices"]), "recent": journal(controller, 3)}
    if command == "choices":
        return {**base, "choices": choice_list(controller),
                "guidance":"Choose a listed action or describe a different intention; review its stakes before resolution."}
    if command == "weaves":
        definitions = controller.rules_engine().WEAVES
        return {**base, "weaves": {key:deepcopy(definitions[key]) for key in player['known_weaves']}}
    if command == "known-facts":
        return {**base, "scene": deepcopy(world), "people": deepcopy(packet["npcs"])}
    if command == "training":
        if "training" in world:
            return {**base, "rank": player["rank"], "known_weaves": deepcopy(player["known_weaves"]),
                    "learning_opportunities": player["learning_opportunities"],
                    "general_points": player["general_points"], "channel_points": player["channel_points"],
                    **deepcopy(world["training"])}
        return {**base, **{k:deepcopy(player[k]) for k in ("rank", "known_weaves", "study_progress", "learning_opportunities")},
                "guidance": "Safe study records exact fictional time. Formal advancement is not active in this prototype."}
    if command == "journal":
        return {**base, "entries": journal(controller)}
    if command == "show-roll":
        entries = journal(controller, 100)
        rolled = [entry for entry in entries if entry["roll"] is not None]
        return {**base, "last_roll": rolled[-1] if rolled else None}
    if command == "pause":
        return {**base, "message": "Play is paused. Fictional time advances only through accepted actions. Pending saves still need verification."}
    raise ValueError("Unknown player command")


def choice_list(controller):
    result = []
    for index, choice in enumerate(controller.public_packet()['world']['choices'], 1):
        if type(choice) is not dict or type(choice.get('intent')) is not dict:
            continue
        result.append({"number":index, "id":choice.get('id', 'choice-'+digest(choice['intent'])[:16]),
                       "label":choice['label'], "intent":deepcopy(choice['intent'])})
    return result


def select_choice(controller, selection):
    choices = choice_list(controller)
    found = [item for item in choices if str(item['number'])==str(selection) or item['id']==selection]
    require(len(found)==1, 'Choose a current choice number or ID.')
    return deepcopy(found[0]['intent'])


def readable_stakes(stakes):
    """A short view alongside, never a replacement for, the exact frozen offer."""
    output = {key:deepcopy(stakes[key]) for key in ('goal','method','time_seconds','check','irreversible_risk')}
    resources = {'vitality','wounds','supply','silver','strain','capacity','control',
                 'general_points','channel_points','pending_work_seconds','support_remaining'}
    def costs(changes):
        return [{'who':x['record_id'],'resource':x['field_id'],'before':x['before'],'after':x['after']}
                for x in changes if x['field_id'] in resources]
    output['upfront_resources'] = costs(stakes['upfront_changes'])
    output['outcomes'] = {key:{'summary':value['summary'], 'resource_changes':costs(value['changes'])}
                          for key,value in stakes['bands'].items()}
    return output


def correction_request(controller, directory, action_id, text):
    """Preserve feedback separately; a request cannot rewrite dice or history."""
    from pathlib import Path
    from .storage import atomic_json, private_directory, read_json
    require(type(text) is str and 1<=len(text.strip())<=4000, 'Describe the requested correction in 1–4000 characters.')
    with controller.store.locked() as db:
        row=db.execute("SELECT envelope_json FROM actions WHERE action_id=? AND phase='DELIVERED'",(action_id,)).fetchone()
        require(row is not None,'A correction must reference a released action.')
        event=parse_json(row[0])['event']
    request={'schema':'correction-request-v1','campaign_id':event['campaign_id'],
             'action_id':action_id,'event_hash':event['event_hash'],'text':text.strip(),
             'status':'requested','resolved':False}
    request_id='correction-'+digest(request)[:24]
    folder=private_directory(Path(directory)/'corrections')
    path=folder/(request_id+'.json')
    if path.exists():
        require(read_json(path)==request, 'Correction request identity conflict.')
    else:
        atomic_json(path,request)
    return {'request_id':request_id,'status':'requested','resolved':False,'history_changed':False,
            'message':'The correction request is saved for review. The original action and dice remain intact.'}
