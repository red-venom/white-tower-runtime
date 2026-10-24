"""Closed dispatcher for public GM commands sharing the action transaction."""
from . import worldbuilding, npc_activity
OPS={'establish',*npc_activity.OPS}


def _module(command):
    if type(command) is not dict or type(command.get('op')) is not str:raise ValueError('Use a structured world command.')
    if command.get('op')=='establish':return worldbuilding
    if command.get('op') in npc_activity.OPS:return npc_activity
    raise ValueError('Unsupported world command. Player actions must use a saved available choice.')


def choice(state,command):return _module(command).choice(state,command)
def resolve(state,command):return _module(command).resolve(state,command)
