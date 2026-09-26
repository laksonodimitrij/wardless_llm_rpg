"""
data/schemas/enemy.py

Lightweight stat-block schema for regular combat enemies (mooks, elites,
monsters) -- distinct from bbeg_tracker.py in one key way: enemies here have
no escalation ladder and no persistent save state. They're templates,
authored once per campaign in data/campaigns/<id>/enemies.json, "spawned"
fresh into an encounter by the engine, and discarded once the fight ends.
If you need a spawned instance's current HP mid-fight, track that
transiently in the encounter/combat loop -- don't add a save file for it.

Reuses StatBlock-shaped fields and NamedFeature from common.py/bbeg_tracker
conventions so an enemy and the BBEG "feel" the same to engine code that
reads stat blocks, even though only the BBEG persists across sessions.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .common import NamedFeature


class EnemyHP(BaseModel):
    current: int = 1
    maximum: int = 1


class EnemyStatBlock(BaseModel):
    hp: EnemyHP = Field(default_factory=EnemyHP)
    armor_class: int = 10
    attack_bonus: int = 0
    damage: str = ""                      # dice notation, e.g. "1d6+2"
    saving_throws: dict[str, int] = Field(default_factory=dict)
    resistances: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)


class EnemyAbilities(BaseModel):
    actions: list[NamedFeature] = Field(default_factory=list)
    reactions: list[NamedFeature] = Field(default_factory=list)


class Enemy(BaseModel):
    id: str = ""
    name: str = ""
    category: str = "mook"          # "mook" | "elite" | "monster" | "undead" | "boss_minion"
    description: str = ""
    stat_block: EnemyStatBlock = Field(default_factory=EnemyStatBlock)
    abilities: EnemyAbilities = Field(default_factory=EnemyAbilities)
    challenge_rating: float = 0.0
    notes: str = ""


class EnemyRosterFile(BaseModel):
    """Root object matching the on-disk campaign file: {"enemies": {id: Enemy}}."""
    enemies: dict[str, Enemy] = Field(default_factory=dict)


if __name__ == "__main__":
    import json
    from pathlib import Path

    roster_path = (
        Path(__file__).parent.parent
        / "campaigns" / "campaign_01_the_hollow_saint" / "enemies.json"
    )
    if roster_path.exists():
        roster = EnemyRosterFile.model_validate_json(roster_path.read_text())
        print(f"Loaded {len(roster.enemies)} enemies OK:")
        for enemy_id, enemy in roster.enemies.items():
            print(f"  - {enemy_id}: {enemy.name} (CR {enemy.challenge_rating}, HP {enemy.stat_block.hp.maximum})")
    else:
        print("No enemies.json found yet at", roster_path)