"""Explicit rules versions. Loading new content never migrates an old save."""
from .contracts import ContractError

LEGACY = ("rules-v1", "content-initial-six-v1", "engine-v1")
FULL = ("rules-v2", "fullcontent-v1", "engine-v1")


def get_rules(rules_version, content_version, engine_version):
    version = (rules_version, content_version, engine_version)
    if version == LEGACY:
        from . import rules
        return rules
    if version == FULL:
        from . import full_rules
        return full_rules
    raise ContractError("The required campaign source version is unavailable.")


def for_context(context):
    return get_rules(*(context.get(key, default) for key, default in zip(
        ("rules_version", "content_version", "engine_version"), LEGACY)))
