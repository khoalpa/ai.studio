"""Closed enums used by the prompt compiler public API."""

from enum import StrEnum


class BlockKind(StrEnum):
    MODULE = "MODULE"
    OVERLAY = "OVERLAY"


class MarkerEdge(StrEnum):
    BEGIN = "BEGIN"
    END = "END"


class UnitKind(StrEnum):
    CANONICAL_RULE_BLOCK = "CANONICAL_RULE_BLOCK"
    NAMED_GATE_BLOCK = "NAMED_GATE_BLOCK"
    REGISTRY_DECLARATION_LINE = "REGISTRY_DECLARATION_LINE"
    OUTPUT_TEMPLATE_BLOCK = "OUTPUT_TEMPLATE_BLOCK"


class Stage(StrEnum):
    STAGE1 = "STAGE1"
    STAGE2 = "STAGE2"
    STAGE3 = "STAGE3"
    STAGE4 = "STAGE4"


class Profile(StrEnum):
    YOUTH_SAFE = "YOUTH_SAFE"
    ADULT_STANDARD = "ADULT_STANDARD"
    SERIAL_DETECTIVE = "SERIAL_DETECTIVE"


class Route(StrEnum):
    CREATE = "CREATE"
    REPAIR = "REPAIR"
    RESUME = "RESUME"


class FindingSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
