"""
data/schemas/world_state.py

Canonical pydantic model for campaign/world state. Field-for-field mirror of
data/schemas/templates/world_state_template.json.

Load with:
    WorldStateFile.model_validate_json(open(path).read())
Write back out with:
    file.model_dump_json(by_alias=True, indent=2)

Design notes:
- `locations`, `npcs`, and `quests.flags` are dicts keyed by a slug id
  ("shadowfen_village", "elder_maren", "find_sunken_shrine"). The template
  starts them as {} — the engine adds entries as the party discovers/meets/
  triggers things. Each entry's shape is defined by the Location/NPC/
  QuestFlag models below.
- `flags.global` is aliased from the JSON key "global" (Python reserved
  word) — same pattern as `identity.char_class` -> "class" in character.py.
  Always dump with by_alias=True.
- NPC `disposition` is a bounded int (-100..100), not free-text mood, so the
  engine can gate behavior on thresholds and the LLM only ever proposes
  small deltas via `adjust_disposition()` rather than restating a mood from
  scratch each turn (which drifts).
"""

from __future__ import annotations

from typing import Union
from pydantic import BaseModel, ConfigDict, Field

from .common import Condition  # re-exported for convenience if engine code wants it


# ---------------------------------------------------------------------------
# party / location pointer
# ---------------------------------------------------------------------------

class Party(BaseModel):
    character_ids: list[str] = Field(default_factory=list)


class LocationPointer(BaseModel):
    current_location_id: str = ""


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------

class Location(BaseModel):
    name: str = ""
    description: str = ""
    region: str = ""
    connections: list[str] = Field(default_factory=list)   # ids of reachable locations
    discovered: bool = False
    danger_level: int = Field(0, ge=0, le=10)
    notes: str = ""


# ---------------------------------------------------------------------------
# npcs
# ---------------------------------------------------------------------------

class NPCStatusLiteral:
    ALIVE = "alive"
    DEAD = "dead"
    MISSING = "missing"
    UNKNOWN = "unknown"


class NPC(BaseModel):
    name: str = ""
    role: str = ""
    faction: str = ""
    location_id: str = ""
    status: str = NPCStatusLiteral.ALIVE
    disposition: int = Field(0, ge=-100, le=100)   # -100 hostile .. 0 neutral .. 100 devoted
    known_facts: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# quests
# ---------------------------------------------------------------------------

class QuestFlagStatus:
    NOT_STARTED = "not_started"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class QuestFlag(BaseModel):
    description: str = ""
    status: str = QuestFlagStatus.NOT_STARTED
    notes: str = ""


class Quests(BaseModel):
    flags: dict[str, QuestFlag] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# flags
# ---------------------------------------------------------------------------

class Flags(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    global_: dict[str, Union[bool, str, int]] = Field(default_factory=dict, alias="global")


# ---------------------------------------------------------------------------
# top-level world state + file wrapper
# ---------------------------------------------------------------------------

class WorldState(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    campaign_id: str = ""
    session_id: str = ""
    turn_count: int = 0

    party: Party = Field(default_factory=Party)
    location: LocationPointer = Field(default_factory=LocationPointer)
    locations: dict[str, Location] = Field(default_factory=dict)
    npcs: dict[str, NPC] = Field(default_factory=dict)
    quests: Quests = Field(default_factory=Quests)
    flags: Flags = Field(default_factory=Flags)
    notes: str = ""

    # -- convenience helpers --------------------------------------------

    def get_npcs_at(self, location_id: str) -> list[NPC]:
        return [n for n in self.npcs.values() if n.location_id == location_id]

    def active_quests(self) -> list[QuestFlag]:
        return [q for q in self.quests.flags.values() if q.status == QuestFlagStatus.ACTIVE]

    def adjust_disposition(self, npc_id: str, delta: int) -> None:
        npc = self.npcs[npc_id]
        npc.disposition = max(-100, min(100, npc.disposition + delta))


class WorldStateFile(BaseModel):
    """Root object matching the on-disk template: {"world_state": {...}}."""
    world_state: WorldState = Field(default_factory=WorldState)


if __name__ == "__main__":
    import json
    from pathlib import Path

    template_path = Path(__file__).parent / "templates" / "world_state_template.json"
    original = json.loads(template_path.read_text())
    blank = WorldStateFile.model_validate_json(template_path.read_text())
    dumped = json.loads(blank.model_dump_json(by_alias=True))
    print("Loaded blank template OK. Round-trip matches:", dumped == original)

    filled = WorldStateFile(
        world_state=WorldState(
            campaign_id="campaign_01_shadowfen",
            session_id="session_0001",
            turn_count=14,
            party=Party(character_ids=["pc_thalindra"]),
            location=LocationPointer(current_location_id="shadowfen_village"),
            locations={
                "shadowfen_village": Location(
                    name="Shadowfen Village",
                    description="A waterlogged huddle of stilt-houses on the edge of the fen.",
                    region="The Shadowfen",
                    connections=["black_root_marsh"],
                    discovered=True,
                    danger_level=1,
                ),
            },
            npcs={
                "elder_maren": NPC(
                    name="Elder Maren",
                    role="Village Elder",
                    location_id="shadowfen_village",
                    disposition=35,
                    known_facts=["Warned the party about the Sunken Shrine."],
                )
            },
            quests=Quests(flags={
                "find_sunken_shrine": QuestFlag(
                    description="Locate the entrance to the Sunken Shrine.",
                    status=QuestFlagStatus.ACTIVE,
                )
            }),
            flags=Flags(global_={"bridge_to_marsh_collapsed": False, "village_festival_active": True}),
        )
    )
    print(filled.model_dump_json(by_alias=True, indent=2))
    filled.world_state.adjust_disposition("elder_maren", +10)
    print("Maren disposition after +10:", filled.world_state.npcs["elder_maren"].disposition)