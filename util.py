"""
Simple utilities.
"""

import dataclasses
import enum
import json

import pint

UNITS = pint.UnitRegistry()


def dataclass_to_dict(data):
    """
    Convert a dataclass object into a dictionary.  Converts any nested dataclasses or dicts into
    JSON blobs.
    """
    base_object = dataclasses.asdict(data)
    for name, value in base_object.items():
        if dataclasses.is_dataclass(value):
            base_object[name] = json.dumps(dataclass_to_dict(value))
        elif isinstance(value, dict):
            base_object[name] = json.dumps(value)
        elif isinstance(value, enum.Enum):
            base_object[name] = value.name
    return base_object
