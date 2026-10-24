"""Shared closed schemas and validation for public world records."""
import re

ID = {'type': 'string', 'pattern': '^[a-z][a-z0-9_]{0,31}$'}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 1000}
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 100}


def variant(kind, fields):
    properties = {'kind': {'const': kind}, **fields}
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def _text(value, maximum=1000):
    if (type(value) is not str or not 1 <= len(value) <= maximum or value != value.strip()
            or any(ord(c) < 32 and c not in '\n\t' for c in value)):
        raise ValueError('Use nonempty bounded text without control characters or surrounding spaces.')
    try: value.encode('utf-8')
    except UnicodeError: raise ValueError('Text must be valid Unicode.') from None


def _id(value):
    if type(value) is not str or not re.fullmatch('[a-z][a-z0-9_]{0,31}', value):
        raise ValueError('Use a stable lowercase identifier of at most 32 characters.')


