"""
engine/rules_5e.py

5e-specific rules built on top of dice.py's generic mechanics: critical-hit
damage doubling, HP/damage application (temp HP absorbs first), leveling,
and thin wrappers that pull the right modifier off a Character/Enemy/
BBEGTracker before rolling. dice.py stays system-agnostic; every actual
5e RULE (not just "roll a d20") is encoded here instead.

Design note on `apply_damage`/`apply_healing`: character.py, bbeg_tracker.py,
and enemy.py each define their own HP-shaped class (Character's HP has a
`temporary` field; bbeg/enemy HP doesn't). Rather than one apply_damage per
schema, these functions just need `.current`/`.maximum` (and optionally
`.temporary`) on whatever's passed in -- duck typing, not a shared base
class -- so the same function works for a Character, an Enemy, or a BBEG.
"""

from __future__ import annotations

from typing import Optional, Protocol

from data.schemas.character import Character, Attack
from data.schemas.enemy import Enemy
from data.schemas.bbeg_tracker import BBEGTracker
from data.schemas.common import AbilityName

from . import dice


# ---------------------------------------------------------------------------
# HP application (works on Character.combat.hp, Enemy stat_block.hp, or
# BBEGTracker stat_block.hp -- anything with .current/.maximum)
# ---------------------------------------------------------------------------

class _HPLike(Protocol):
    current: int
    maximum: int


def apply_damage(hp: _HPLike, amount: int) -> int:
    """Reduces temp HP first (if the object has a `temporary` field), then
    current HP, floored at 0. Returns the amount actually removed from
    current HP (i.e. amount minus whatever temp HP absorbed) -- useful for
    narrating "the blow chips through her wards and lands for 4."""
    if amount <= 0:
        return 0
    temp = getattr(hp, "temporary", 0)
    remaining = amount
    if temp > 0:
        absorbed = min(temp, remaining)
        hp.temporary = temp - absorbed
        remaining -= absorbed
    hp.current = max(0, hp.current - remaining)
    return remaining


def apply_healing(hp: _HPLike, amount: int) -> int:
    """Increases current HP, capped at maximum. Returns the amount actually
    healed (capped), so callers can narrate "most of that healing had
    nowhere to go -- she was already near full.\""""
    if amount <= 0:
        return 0
    before = hp.current
    hp.current = min(hp.maximum, hp.current + amount)
    return hp.current - before


def is_down(hp: _HPLike) -> bool:
    return hp.current <= 0


# ---------------------------------------------------------------------------
# Damage resolution (the crit-doubling rule lives here, not in dice.py,
# because "critical hits double the dice" is a 5e rule, not a dice-rolling
# primitive)
# ---------------------------------------------------------------------------

def resolve_damage(notation: str, critical: bool = False, rng=None) -> dice.RollResult:
    """Roll damage, doubling the NUMBER OF DICE (not the flat modifier) on
    a critical hit -- e.g. "1d8+3" crits as 2d8+3, not (1d8+3)*2."""
    count, sides, modifier = dice.parse_dice(notation)
    if critical:
        count *= 2
    import random as _random
    rng = rng or _random
    rolls = [rng.randint(1, sides) for _ in range(count)]
    chosen = sum(rolls)
    return dice.RollResult(notation=notation, rolls=rolls, chosen=chosen,
                            modifier=modifier, total=chosen + modifier)


class AttackOutcome:
    """Bundles the attack roll and (if it hit) the damage roll into one
    result, so calling code doesn't have to juggle two separate returns."""

    def __init__(self, attack: dice.AttackRollResult, damage: Optional[dice.RollResult]):
        self.attack = attack
        self.damage = damage

    @property
    def hit(self) -> bool:
        return self.attack.hit

    @property
    def critical_hit(self) -> bool:
        return self.attack.critical_hit

    @property
    def damage_dealt(self) -> int:
        return self.damage.total if self.damage else 0


def resolve_attack(
    attack_bonus: int,
    damage_notation: str,
    target_ac: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
    flat_damage_bonus: int = 0,
    rng=None,
) -> AttackOutcome:
    """The single entry point for 'roll to hit, then roll damage if it
    lands' -- used by character_attack(), enemy_attack(), and
    bbeg_attack() below so the actual 5e sequence only exists once.

    `flat_damage_bonus` exists for cases like the BBEG's escalation
    stat_modifiers, which can include narrative keys (e.g. "damage_bonus")
    that don't correspond to a real stat_block field -- see bbeg_attack().
    """
    attack = dice.attack_roll(attack_bonus, target_ac, advantage, disadvantage, rng)
    if not attack.hit:
        return AttackOutcome(attack=attack, damage=None)
    damage = resolve_damage(damage_notation, critical=attack.critical_hit, rng=rng)
    if flat_damage_bonus:
        damage.total += flat_damage_bonus
    return AttackOutcome(attack=attack, damage=damage)


# ---------------------------------------------------------------------------
# Character-specific wrappers -- pull the right modifier off the schema,
# then delegate to the generic functions above
# ---------------------------------------------------------------------------

def character_ability_check(
    character: Character, ability: AbilityName, dc: int,
    advantage: bool = False, disadvantage: bool = False, rng=None,
) -> dice.CheckResult:
    modifier = character.ability_modifier(ability)
    return dice.ability_check(modifier, dc, advantage, disadvantage, rng)


def character_saving_throw(
    character: Character, ability: AbilityName, dc: int,
    advantage: bool = False, disadvantage: bool = False, rng=None,
) -> dice.CheckResult:
    modifier = character.saving_throw_bonus(ability)
    return dice.saving_throw(modifier, dc, advantage, disadvantage, rng)


def character_skill_check(
    character: Character, skill_name: str, dc: int, *, expertise: bool = False,
    advantage: bool = False, disadvantage: bool = False, rng=None,
) -> dice.CheckResult:
    bonus = character.skill_bonus(skill_name, expertise=expertise)
    if bonus is None:
        raise ValueError(
            f"Unknown skill {skill_name!r} -- not in SKILL_ABILITY_MAP (data/schemas/common.py)"
        )
    return dice.ability_check(bonus, dc, advantage, disadvantage, rng)


def character_attack(
    character: Character, attack: Attack, target_ac: int,
    advantage: bool = False, disadvantage: bool = False, rng=None,
) -> AttackOutcome:
    return resolve_attack(attack.attack_bonus, attack.damage, target_ac,
                           advantage=advantage, disadvantage=disadvantage, rng=rng)


# ---------------------------------------------------------------------------
# Enemy / BBEG wrappers
# ---------------------------------------------------------------------------

def enemy_attack(
    enemy: Enemy, target_ac: int,
    advantage: bool = False, disadvantage: bool = False, rng=None,
) -> AttackOutcome:
    return resolve_attack(enemy.stat_block.attack_bonus, enemy.stat_block.damage, target_ac,
                           advantage=advantage, disadvantage=disadvantage, rng=rng)


def bbeg_attack(
    tracker: BBEGTracker, target_ac: int,
    advantage: bool = False, disadvantage: bool = False, rng=None,
) -> AttackOutcome:
    """Uses tracker.effective_stat() for attack_bonus (a real stat_block
    field the escalation ladder modifies), but escalation stat_modifiers
    can also carry keys with no matching stat_block field -- this
    campaign's stages use "damage_bonus" as a flat bonus to damage rolls,
    which effective_stat() correctly returns None for (it only resolves
    real stat_block attributes). We pull that one directly off
    current_stage.stat_modifiers instead."""
    attack_bonus = tracker.effective_stat("attack_bonus")
    if attack_bonus is None:
        attack_bonus = tracker.stat_block.attack_bonus
    flat_damage_bonus = tracker.escalation.current_stage.stat_modifiers.get("damage_bonus", 0)
    return resolve_attack(attack_bonus, tracker.stat_block.damage, target_ac,
                           advantage=advantage, disadvantage=disadvantage,
                           flat_damage_bonus=flat_damage_bonus, rng=rng)


# ---------------------------------------------------------------------------
# Leveling
# ---------------------------------------------------------------------------

def hit_points_gained_on_level_up(
    hit_die_sides: int, constitution_modifier: int,
    take_average: bool = True, rng=None,
) -> int:
    """5e RAW: on level-up you either take the fixed average of the hit
    die (rounded up) or roll it -- both plus your CON modifier."""
    if take_average:
        base = (hit_die_sides // 2) + 1
    else:
        base = dice.roll(f"1d{hit_die_sides}", rng).total
    return max(1, base + constitution_modifier)  # HP gain is always at least 1


def apply_level_up(
    character: Character, constitution_modifier: int,
    take_average: bool = True, rng=None,
) -> int:
    """Increments level, hit dice, and HP maximum/current. Proficiency
    bonus is NOT touched here -- it's a computed_field on Character derived
    from identity.level, so it updates itself the moment level changes.
    Returns the HP gained, for narration ("Thalindra feels sturdier -- +7 HP")."""
    character.identity.level += 1
    hit_die_sides = int(character.combat.hit_dice.type.lstrip("dD"))
    gained = hit_points_gained_on_level_up(hit_die_sides, constitution_modifier, take_average, rng)
    character.combat.hp.maximum += gained
    character.combat.hp.current += gained
    character.combat.hit_dice.maximum += 1
    character.combat.hit_dice.remaining += 1
    return gained