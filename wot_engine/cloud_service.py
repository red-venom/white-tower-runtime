"""Cloud-facing game operations; transport authentication supplies principal.

This module does not authenticate HTTP or claim a deployed service. Its durable
root must be a persistent host volume. FileRemote here is an explicit disposable
cloud rehearsal store, not an independently hosted replica or Notion adapter.
"""
from copy import deepcopy
from pathlib import Path
import re
import secrets

from . import creation, full_rules
from .contracts import canonical, digest, require
from .controller import Controller
from .player import query, readable_stakes
from .storage import FileRemote, atomic_json, file_lock, private_directory, read_json

IDENTIFIER = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z')


def campaign_path(root, principal, campaign_id):
    require(type(principal) is str and 1 <= len(principal) <= 256, 'Authenticated identity required.')
    require(type(campaign_id) is str and IDENTIFIER.fullmatch(campaign_id), 'Invalid campaign ID.')
    return Path(root) / digest(principal) / campaign_id


def list_rehearsals(root, principal, after=None):
    """Discover only this authenticated player's saves without opening a writer.

    An initialization marker includes interrupted initialization, so a failed
    creation remains discoverable for recovery rather than silently disappearing.
    No private profile or seed is read. Read the selected campaign for its status.
    """
    require(type(principal) is str and 1 <= len(principal) <= 256, 'Authenticated identity required.')
    require(after is None or (type(after) is str and IDENTIFIER.fullmatch(after)), 'Invalid cursor.')
    directory = Path(root) / digest(principal)
    if not directory.exists():
        return {'campaigns':[], 'next_after':None}
    names = sorted(p.name for p in directory.iterdir() if p.is_dir() and not p.is_symlink()
                   and IDENTIFIER.fullmatch(p.name) and (p / 'initialization.json').is_file()
                   and (after is None or p.name > after))
    return {'campaigns':[{'campaign_id':name,'disposable':True} for name in names[:50]],
            'next_after':names[49] if len(names) > 50 else None}


def character_template():
    return {'template':creation.template(), 'guidance':
            'Ask the player for the blank biography fields and an adult age (18+). '
            'This module follows a woman who channels saidar. Attributes use 0,1,1,2,2; '
            'skills use six 0s, four 1s and two 2s. Prior skill must have a positive rating. '
            'Choose air, earth, fire, water or spirit as the starting Flow. '
            'Keep the complete profile within 3 KiB. Do not invent the player’s identity choices.'}


class CloudGame:
    def __init__(self, root, principal, campaign_id):
        path = campaign_path(root, principal, campaign_id)
        self.campaign_id = campaign_id
        # The principal comes from the authenticated gateway, never tool arguments.
        self.path = private_directory(path)
        self.offers = private_directory(self.path / 'offers')
        self.controller = Controller(self.path / 'controller', FileRemote(self.path / 'rehearsal-remote'))

    def start_rehearsal(self, character=None):
        with file_lock(self.path / 'service.lock'):
            request = {'character':character, 'disposable':True}
            path = self.path / 'initialization.json'
            if path.exists():
                saved = read_json(path)
                require(canonical(saved['request']) == canonical(request), 'Campaign already has different creation choices.')
            else:
                seed = secrets.token_bytes(32)
                options = {} if character is None else {'character':character}
                state = full_rules.initial_state(seed=seed, campaign_id=self.campaign_id, **options)
                saved = {'request':request,'seed_hex':seed.hex(),'state':state}
                atomic_json(path, saved)
            result = self.controller.initialize(self.campaign_id, saved['state'], bytes.fromhex(saved['seed_hex']),
                rules_version=full_rules.RULES_VERSION,content_version=full_rules.CONTENT_VERSION,
                engine_version=full_rules.ENGINE_VERSION)
            return {'save':result, 'packet':self.controller.public_packet(), 'disposable':True}

    def read(self, command='recap', course_id=None):
        require(command in ('recap','sheet','choices','training','journal','show-roll','known-facts','weaves','pause','course'),
                'Unknown player query.')
        if command == 'course':
            return self.controller.public_course(course_id)
        return query(self.controller, command)

    def preview(self, action_id, intent):
        require(type(action_id) is str and IDENTIFIER.fullmatch(action_id), 'Invalid action ID.')
        require(type(intent) is dict, 'An action intention is required.')
        with file_lock(self.path / 'service.lock'):
            path = self.offers / (action_id + '.json')
            if path.exists():
                offer = read_json(path)
                require(canonical(offer['intent']) == canonical(intent), 'Action ID already has another intention.')
            else:
                require(self.controller.public_status()['status'] == 'OK', 'Finish the pending save first.')
                packet = self.controller.public_packet()
                action = full_rules.build_action(self.controller.trusted_state(), packet['head_hash'],
                    self.campaign_id, action_id, intent, 'preview-only')
                offer = {'intent':deepcopy(intent), 'action':action}
                atomic_json(path, offer)
            action = offer['action']
            return {'action_id':action_id,'expected_head_hash':action['expected_head_hash'],
                    'stakes_hash':action['stakes_hash'],'stakes':readable_stakes(action['stakes']),
                    'accepted':False}

    def accept(self, action_id, stakes_hash):
        require(type(action_id) is str and IDENTIFIER.fullmatch(action_id), 'Invalid action ID.')
        with file_lock(self.path / 'service.lock'):
            path = self.offers / (action_id + '.json')
            require(path.is_file(), 'Preview this action before accepting it.')
            offer = read_json(path)
            require(stakes_hash == offer['action']['stakes_hash'], 'Acceptance does not match the shown stakes.')
            # Persist exact accepted input before execution. Retries never rebuild
            # against a later state and never generate another action identity.
            accepted_path = self.offers / (action_id + '.accepted.json')
            if accepted_path.exists():
                action = read_json(accepted_path)
            else:
                require(self.controller.public_packet()['head_hash'] == offer['action']['expected_head_hash'],
                        'Offer is stale; preview a new action ID.')
                action = deepcopy(offer['action'])
                action['acceptance_ref'] = 'cloud-choice-' + action_id
                atomic_json(accepted_path, action)
            narrations = {key:value['summary'] for key,value in action['stakes']['bands'].items()}
            narrations['routine'] = narrations['clean']
            result = self.controller.execute(action, narrations)
            return {'save':result, 'packet':self.controller.public_packet()}
