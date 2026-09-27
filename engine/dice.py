"""
engine/dice.py

Pure dice mechanics -- rolling, parsing dice notation, ability/save checks,
attack rolls. Deliberately system-agnostic: nothing in here knows what a
"critical hit doubles damage dice" rule is, or what a proficiency bonus is.
That 5e-specific interpretation lives in rules_5e.py, which calls into this
module. Splitting it this way means dice.py could be reused as-is if the
system ever changed, and rules_5e.py stays the single place 5e rules text
gets encoded.

Every function takes an optional `rng` (a `random.Random` instance) so
tests can pass a seeded RNG and get deterministic results instead of
depending on the global `random` module.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_DICE_PATTERN = re.compile(r"^(\d*)d(\d+)\s*([+-]\s*\d+)?$", re.IGNORECASE)


def parse_dice(notation: str) -> tuple[int, int, int]:
    """Parse "2d6+3", "1d20", "4d8-2" into (count, sides, modifier)."""
    cleaned = notation.strip().replace(" ", "")
    match = _DICE_PATTERN.match(cleaned)
    if not match:
        raise ValueError(f"Invalid dice notation: {notation!r}")
    count = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    return count, sides, modifier


@dataclass
class RollResult:
    notation: str
    rolls: list[int]          # every raw die shown (both dice for adv/disadv)
    chosen: int                # the kept value: single die for d20, sum for multi-dice
    modifier: int
    total: int

    @property
    def natural(self) -> int:
        """Alias for `chosen`, matching 5e terminology ('a natural 20')."""
        return self.chosen


def roll(notation: str, rng: random.Random | None = None) -> RollResult:
    """Roll arbitrary dice notation, e.g. roll("2d6+3")."""
    rng = rng or random
    count, sides, modifier = parse_dice(notation)
    rolls = [rng.randint(1, sides) for _ in range(count)]
    chosen = sum(rolls)
    return RollResult(notation=notation, rolls=rolls, chosen=chosen,
                       modifier=modifier, total=chosen + modifier)


def roll_d20(
    modifier: int = 0,
    advantage: bool = False,
    disadvantage: bool = False,
    rng: random.Random | None = None,
) -> RollResult:
    """Roll a single d20 (or 2d20 keep-highest/lowest for adv/disadv) + modifier."""
    rng = rng or random
    if advantage and disadvantage:
        # 5e RAW: advantage and disadvantage cancel out.
        advantage = disadvantage = False

    if advantage or disadvantage:
        rolls = [rng.randint(1, 20), rng.randint(1, 20)]
        chosen = max(rolls) if advantage else min(rolls)
    else:
        rolls = [rng.randint(1, 20)]
        chosen = rolls[0]

    return RollResult(notation="1d20", rolls=rolls, chosen=chosen,
                       modifier=modifier, total=chosen + modifier)


@dataclass
class CheckResult:
    roll: RollResult
    dc: int
    success: bool
    is_natural_20: bool
    is_natural_1: bool


def ability_check(
    modifier: int,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
    rng: random.Random | None = None,
) -> CheckResult:
    """Generic d20 + modifier vs DC. Used for ability checks AND saving
    throws -- 5e RAW doesn't auto-succeed/fail either on a natural 20/1
    (that rule is attack-roll-only), so success is purely total >= dc.
    is_natural_20/is_natural_1 are exposed anyway for roleplay flavor."""
    result = roll_d20(modifier, advantage, disadvantage, rng)
    return CheckResult(
        roll=result,
        dc=dc,
        success=result.total >= dc,
        is_natural_20=(result.chosen == 20),
        is_natural_1=(result.chosen == 1),
    )


# Saving throws use identical mechanics to ability checks in 5e -- this
# alias exists purely so calling code reads naturally at the call site.
saving_throw = ability_check


@dataclass
class AttackRollResult:
    roll: RollResult
    target_ac: int
    hit: bool
    critical_hit: bool     # natural 20 -- always hits, and rules_5e.py doubles damage dice
    critical_miss: bool    # natural 1 -- always misses, regardless of total


def attack_roll(
    attack_bonus: int,
    target_ac: int,
    advantage: bool = False,
    disadvantage: bool = False,
    rng: random.Random | None = None,
) -> AttackRollResult:
    """d20 + attack bonus vs. target AC. Natural 20 always hits, natural 1
    always misses -- this IS a real 5e attack-roll-specific rule (unlike
    ability checks/saves), which is why it's handled here rather than by
    reusing ability_check()."""
    result = roll_d20(attack_bonus, advantage, disadvantage, rng)
    crit = result.chosen == 20
    fumble = result.chosen == 1
    hit = crit or (not fumble and result.total >= target_ac)
    return AttackRollResult(roll=result, target_ac=target_ac, hit=hit,
                             critical_hit=crit, critical_miss=fumble)