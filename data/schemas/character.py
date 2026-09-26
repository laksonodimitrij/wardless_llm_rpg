"""
data/schemas/character.py

Canonical pydantic model for a character sheet. This is a field-for-field
mirror of data/schemas/templates/character_template.json — the JSON template
IS the schema now; this file just adds validation, defaults, and computed
helpers (ability modifiers, proficiency bonus, skill bonuses) on top of it.

Load a save file with:
    CharacterFile.model_validate_json(open(path).read())
Write one back out (preserving the "class" key, not "char_class") with:
    file.model_dump_json(by_alias=True, indent=2)

Design notes:
- `identity.char_class` is aliased to JSON key "class" since `class` is a
  reserved word in Python. Always dump with by_alias=True or the field will
  round-trip as "char_class" instead of "class".
- Computed values (proficiency_bonus, ability modifiers, skill/save bonuses)
  are never stored fields — they're derived from `identity.level` and
  `stats` every time, so they can never drift out of sync with the source
  numbers the way a cached "prof_bonus: 3" field could.
- `equipment.equipped` and `equipment.inventory` are both lists of the same
  Item type; which list an item sits in *is* its equipped/unequipped state,
  rather than a separate boolean flag on the item.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, computed_field

from .common import AbilityName, Condition, Item, NamedFeature, SKILL_ABILITY_MAP


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class Identity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    race: str = ""
    subrace: str = ""
    char_class: str = Field("", alias="class")
    subclass: str = ""
    level: int = Field(1, ge=1, le=20)
    background: str = ""
    alignment: str = ""
    experience_points: int = 0


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class Stats(BaseModel):
    strength: int = Field(10, ge=1, le=30)
    dexterity: int = Field(10, ge=1, le=30)
    constitution: int = Field(10, ge=1, le=30)
    intelligence: int = Field(10, ge=1, le=30)
    wisdom: int = Field(10, ge=1, le=30)
    charisma: int = Field(10, ge=1, le=30)

    def modifier(self, ability: AbilityName) -> int:
        score = getattr(self, ability.value)
        return (score - 10) // 2


# ---------------------------------------------------------------------------
# proficiencies
# ---------------------------------------------------------------------------

class Proficiencies(BaseModel):
    saving_throws: list[AbilityName] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)   # skill names, e.g. "Stealth"
    languages: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    weapons: list[str] = Field(default_factory=list)
    armor: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# combat
# ---------------------------------------------------------------------------

class HP(BaseModel):
    current: int = 1
    maximum: int = 1
    temporary: int = 0

    @computed_field
    @property
    def is_unconscious(self) -> bool:
        return self.current <= 0


class HitDice(BaseModel):
    type: str = "d8"
    maximum: int = 1
    remaining: int = 1


class DeathSaves(BaseModel):
    successes: int = Field(0, ge=0, le=3)
    failures: int = Field(0, ge=0, le=3)


class Combat(BaseModel):
    armor_class: int = 10
    initiative_bonus: int = 0
    speed: int = 30
    hp: HP = Field(default_factory=HP)
    hit_dice: HitDice = Field(default_factory=HitDice)
    death_saves: DeathSaves = Field(default_factory=DeathSaves)


# ---------------------------------------------------------------------------
# attacks
# ---------------------------------------------------------------------------

class Attack(BaseModel):
    name: str = ""
    attack_type: str = "melee"     # "melee" | "ranged" | "spell"
    attack_bonus: int = 0
    damage: str = ""               # dice notation, e.g. "1d8+3"
    damage_type: str = ""          # "slashing", "fire", etc.
    range_ft: Optional[int] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# equipment
# ---------------------------------------------------------------------------

class Currency(BaseModel):
    cp: int = 0
    sp: int = 0
    ep: int = 0
    gp: int = 0
    pp: int = 0


class Equipment(BaseModel):
    equipped: list[Item] = Field(default_factory=list)
    inventory: list[Item] = Field(default_factory=list)
    currency: Currency = Field(default_factory=Currency)


# ---------------------------------------------------------------------------
# abilities
# ---------------------------------------------------------------------------

class Abilities(BaseModel):
    features: list[NamedFeature] = Field(default_factory=list)
    feats: list[NamedFeature] = Field(default_factory=list)
    racial_traits: list[NamedFeature] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# spellcasting
# ---------------------------------------------------------------------------

class SpellSlot(BaseModel):
    maximum: int = 0
    remaining: int = 0


class Spellcasting(BaseModel):
    enabled: bool = False
    ability: Optional[AbilityName] = None
    spell_save_dc: Optional[int] = None
    spell_attack_bonus: Optional[int] = None
    spell_slots: dict[str, SpellSlot] = Field(
        default_factory=lambda: {str(i): SpellSlot() for i in range(1, 10)}
    )
    cantrips: list[str] = Field(default_factory=list)
    spells_known: list[str] = Field(default_factory=list)
    spells_prepared: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# state / personality / backstory
# ---------------------------------------------------------------------------

class CharacterState(BaseModel):
    inspiration: bool = False
    concentration: Optional[str] = None   # name of spell being concentrated on
    exhaustion: int = Field(0, ge=0, le=6)
    unconscious: bool = False
    dead: bool = False


class Personality(BaseModel):
    traits: str = ""
    ideals: str = ""
    bonds: str = ""
    flaws: str = ""


class Backstory(BaseModel):
    description: str = ""
    allies: list[str] = Field(default_factory=list)
    enemies: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# top-level character + file wrapper
# ---------------------------------------------------------------------------

class Character(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    name: str = ""

    identity: Identity = Field(default_factory=Identity)
    stats: Stats = Field(default_factory=Stats)
    proficiencies: Proficiencies = Field(default_factory=Proficiencies)
    combat: Combat = Field(default_factory=Combat)
    attacks: list[Attack] = Field(default_factory=list)
    equipment: Equipment = Field(default_factory=Equipment)
    abilities: Abilities = Field(default_factory=Abilities)
    spellcasting: Spellcasting = Field(default_factory=Spellcasting)
    conditions: list[Condition] = Field(default_factory=list)
    state: CharacterState = Field(default_factory=CharacterState)
    personality: Personality = Field(default_factory=Personality)
    backstory: Backstory = Field(default_factory=Backstory)
    notes: str = ""

    # -- computed / derived, never authored directly ------------------------

    @computed_field
    @property
    def proficiency_bonus(self) -> int:
        return 2 + (self.identity.level - 1) // 4

    def ability_modifier(self, ability: AbilityName) -> int:
        return self.stats.modifier(ability)

    def saving_throw_bonus(self, ability: AbilityName) -> int:
        mod = self.ability_modifier(ability)
        if ability in self.proficiencies.saving_throws:
            mod += self.proficiency_bonus
        return mod

    def skill_bonus(self, skill_name: str, expertise: bool = False) -> Optional[int]:
        ability = SKILL_ABILITY_MAP.get(skill_name)
        if ability is None:
            return None
        mod = self.ability_modifier(ability)
        if skill_name in self.proficiencies.skills:
            mod += self.proficiency_bonus * (2 if expertise else 1)
        return mod


class CharacterFile(BaseModel):
    """Root object matching the on-disk template: {"character": {...}}."""
    character: Character = Field(default_factory=Character)


if __name__ == "__main__":
    import json
    from pathlib import Path

    template_path = Path(__file__).parent / "templates" / "character_template.json"
    original = json.loads(template_path.read_text())
    blank = CharacterFile.model_validate_json(template_path.read_text())
    dumped = json.loads(blank.model_dump_json(by_alias=True))
    # Computed fields (proficiency_bonus, hp.is_unconscious) are derived and
    # appear in the dump but not the stored template -- strip them for the
    # structural-equality check.
    dumped["character"].pop("proficiency_bonus", None)
    dumped["character"]["combat"]["hp"].pop("is_unconscious", None)
    print("Loaded blank template OK. Round-trip matches (minus computed fields):",
          dumped == original)

    filled = CharacterFile(
        character=Character(
            id="pc_thalindra",
            name="Thalindra Nightwhisper",
            identity=Identity(race="Wood Elf", char_class="Ranger", level=3,
                               background="Outlander", alignment="Chaotic Good"),
            stats=Stats(strength=12, dexterity=18, constitution=14,
                        intelligence=10, wisdom=15, charisma=8),
            proficiencies=Proficiencies(
                saving_throws=[AbilityName.STRENGTH, AbilityName.DEXTERITY],
                skills=["Stealth", "Survival"],
                languages=["Common", "Elvish"],
            ),
            combat=Combat(armor_class=15, hp=HP(current=24, maximum=28)),
            equipment=Equipment(
                equipped=[Item(id="longbow", name="Longbow", tags=["weapon"])],
                inventory=[Item(id="healing_potion", name="Potion of Healing", quantity=2)],
                currency=Currency(sp=12, gp=45),
            ),
            experience_points=0,
        )
    )
    print(filled.model_dump_json(by_alias=True, indent=2))
    print("DEX save bonus:", filled.character.saving_throw_bonus(AbilityName.DEXTERITY))
    print("Stealth bonus:", filled.character.skill_bonus("Stealth"))
    print("Proficiency bonus:", filled.character.proficiency_bonus)