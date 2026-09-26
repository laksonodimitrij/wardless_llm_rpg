"""
data/schemas/common.py

Small shared pieces reused across character.py, world_state.py, and
bbeg_tracker.py, so we don't redefine the same enum three different ways.

- AbilityName uses full lowercase words ("strength", not "STR") because
  that's what the character template's `stats` block uses as field names —
  keeping the enum values identical to those field names lets us do
  getattr(stats, ability.value) instead of maintaining a translation table.
- SKILL_ABILITY_MAP is fixed 5e SRD data (which ability governs which
  skill). It's a module-level constant, not stored per-character, because
  it never changes — the template only needs to store which skills a
  character is proficient in, not which ability each skill uses.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AbilityName(str, Enum):
    STRENGTH = "strength"
    DEXTERITY = "dexterity"
    CONSTITUTION = "constitution"
    INTELLIGENCE = "intelligence"
    WISDOM = "wisdom"
    CHARISMA = "charisma"


SKILL_ABILITY_MAP: dict[str, AbilityName] = {
    "Acrobatics": AbilityName.DEXTERITY,
    "Animal Handling": AbilityName.WISDOM,
    "Arcana": AbilityName.INTELLIGENCE,
    "Athletics": AbilityName.STRENGTH,
    "Deception": AbilityName.CHARISMA,
    "History": AbilityName.INTELLIGENCE,
    "Insight": AbilityName.WISDOM,
    "Intimidation": AbilityName.CHARISMA,
    "Investigation": AbilityName.INTELLIGENCE,
    "Medicine": AbilityName.WISDOM,
    "Nature": AbilityName.INTELLIGENCE,
    "Perception": AbilityName.WISDOM,
    "Performance": AbilityName.CHARISMA,
    "Persuasion": AbilityName.CHARISMA,
    "Religion": AbilityName.INTELLIGENCE,
    "Sleight of Hand": AbilityName.DEXTERITY,
    "Stealth": AbilityName.DEXTERITY,
    "Survival": AbilityName.WISDOM,
}


class Condition(str, Enum):
    BLINDED = "blinded"
    CHARMED = "charmed"
    DEAFENED = "deafened"
    FRIGHTENED = "frightened"
    GRAPPLED = "grappled"
    INCAPACITATED = "incapacitated"
    INVISIBLE = "invisible"
    PARALYZED = "paralyzed"
    PETRIFIED = "petrified"
    POISONED = "poisoned"
    PRONE = "prone"
    RESTRAINED = "restrained"
    STUNNED = "stunned"
    UNCONSCIOUS = "unconscious"


class NamedFeature(BaseModel):
    """Generic (name, description) pair — used for feats, racial traits,
    class features, and BBEG actions alike, so we don't need four almost
    identical models."""
    name: str = ""
    description: str = ""


class Item(BaseModel):
    id: str = ""
    name: str = ""
    quantity: int = 1
    weight_lb: float = 0.0
    attuned: bool = False
    description: Optional[str] = None
    charges: Optional[int] = None
    tags: list[str] = Field(default_factory=list)