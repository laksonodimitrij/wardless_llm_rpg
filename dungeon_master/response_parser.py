"""
dm/response_parser.py

This is where "the LLM proposes, the engine decides" actually gets
enforced. Every turn, the model's raw text output gets split into (1)
prose narration the player reads and (2) a structured state-change block.
That block is validated against TurnStateChanges below -- if it doesn't
parse or doesn't validate, apply_turn_changes() never runs and nothing
touches the save file. A malformed model response is a retry/error, never
a silent corruption.

Output contract the system prompt teaches the model to follow: raw output
must end with

    <state_changes>
    { ... }
    </state_changes>

Everything before that tag is narration. A custom tag pair (not a ```json
fence) is used because locally-hosted Ollama models are less reliable
about consistently closing markdown fences than hosted frontier models --
a single distinct tag pair is trivially regex-extractable, and the
extraction below still strips a stray code fence defensively in case the
model wraps the JSON in one anyway.

Design boundary worth remembering: TurnStateChanges is deliberately NOT a
full WorldState/Character/BBEGTracker. The model never re-emits an entire
save file -- it proposes a small, bounded set of *deltas*. This keeps
token cost down and means a bug in the model's output can only ever
corrupt a handful of fields, never silently overwrite state it wasn't
asked to touch.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError, field_validator

from data.schemas.world_state import QuestFlag
from data.schemas.common import Item
from engine import bbeg_escalation
from engine.state import SessionSave
from engine.campaign_loader import LoadedCampaign


# ---------------------------------------------------------------------------
# The output contract
# ---------------------------------------------------------------------------

# A single event proposal can't swing an NPC's disposition by more than
# this in one turn -- guards against a model deciding "Elder Maren now
# hates you (-100)" over one bad joke. Bounding the DELTA (not just the
# final -100..100 range already enforced on NPC.disposition itself) is
# what actually limits how fast relationships can swing.
MAX_DISPOSITION_DELTA_PER_EVENT = 25

# A narrative-consequence HP change (a miracle's cost, a ritual's toll --
# NOT a resolved combat attack, which is computed by engine/rules_5e.py
# before the model ever sees the turn) is capped as a fraction of the
# character's max HP, so the model can propose "the ritual costs you dearly"
# without being able to propose "the ritual kills you outright" on a whim.
MAX_NARRATIVE_HP_DELTA_FRACTION = 0.5


class QuestFlagUpdate(BaseModel):
    status: Optional[Literal["not_started", "active", "completed", "failed"]] = None
    description: Optional[str] = None    # allows introducing a brand-new quest flag
    notes: Optional[str] = None


class WorldChanges(BaseModel):
    location_id: Optional[str] = None                                   # party moved
    discovered_locations: list[str] = Field(default_factory=list)
    npc_disposition_deltas: dict[str, int] = Field(default_factory=dict)
    npc_status_changes: dict[str, Literal["alive", "dead", "missing", "unknown"]] = Field(default_factory=dict)
    npc_known_facts_added: dict[str, list[str]] = Field(default_factory=dict)
    quest_flag_updates: dict[str, QuestFlagUpdate] = Field(default_factory=dict)
    global_flag_updates: dict[str, Union[bool, str, int]] = Field(default_factory=dict)

    @field_validator("npc_disposition_deltas")
    @classmethod
    def _bound_disposition_deltas(cls, v: dict[str, int]) -> dict[str, int]:
        for npc_id, delta in v.items():
            if abs(delta) > MAX_DISPOSITION_DELTA_PER_EVENT:
                raise ValueError(
                    f"npc_disposition_deltas[{npc_id!r}]={delta} exceeds the per-event cap "
                    f"of +/-{MAX_DISPOSITION_DELTA_PER_EVENT}"
                )
        return v


class CharacterChanges(BaseModel):
    hp_delta: int = 0                     # narrative-consequence only -- see module docstring
    conditions_added: list[str] = Field(default_factory=list)
    conditions_removed: list[str] = Field(default_factory=list)
    inventory_added: list[dict] = Field(default_factory=list)     # raw Item-shaped dicts
    inventory_removed_ids: list[str] = Field(default_factory=list)
    currency_delta: dict[str, int] = Field(default_factory=dict)  # {"gp": -10}
    notes_append: Optional[str] = None


class EscalationProposal(BaseModel):
    reason: str
    severity: Literal["minor", "moderate", "major", "pivotal"]


class TurnStateChanges(BaseModel):
    world: WorldChanges = Field(default_factory=WorldChanges)
    characters: dict[str, CharacterChanges] = Field(default_factory=dict)   # character_id -> changes
    escalation_event: Optional[EscalationProposal] = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class ResponseParseError(Exception):
    """Raised when the model's raw output can't be split into narration +
    a valid state_changes block. Callers (cli/play.py) should catch this
    and either re-prompt the model or surface an error -- never proceed to
    apply_turn_changes() with an unparsed response."""


_STATE_BLOCK_PATTERN = re.compile(r"<state_changes>(.*?)</state_changes>", re.DOTALL | re.IGNORECASE)
_STRAY_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class ParsedTurn:
    narration: str
    state_changes: TurnStateChanges
    raw_state_block: str


def parse_turn_response(raw_text: str) -> ParsedTurn:
    match = _STATE_BLOCK_PATTERN.search(raw_text)
    if not match:
        raise ResponseParseError(
            "No <state_changes>...</state_changes> block found in model output."
        )

    narration = raw_text[: match.start()].strip()
    if not narration:
        raise ResponseParseError("No narration text found before the <state_changes> block.")

    block_text = _STRAY_FENCE_PATTERN.sub("", match.group(1).strip()).strip()

    try:
        raw_json = json.loads(block_text)
    except json.JSONDecodeError as e:
        raise ResponseParseError(f"state_changes block was not valid JSON: {e}") from e

    try:
        state_changes = TurnStateChanges.model_validate(raw_json)
    except ValidationError as e:
        raise ResponseParseError(f"state_changes failed schema validation: {e}") from e

    return ParsedTurn(narration=narration, state_changes=state_changes, raw_state_block=block_text)


# ---------------------------------------------------------------------------
# Applying validated changes to a session
# ---------------------------------------------------------------------------

@dataclass
class ApplySummary:
    """What actually happened when a ParsedTurn was applied -- for logging
    and for cli/play.py to display alongside the narration (e.g. an
    escalation stage change deserves an on-screen callout)."""
    warnings: list[str]
    escalation_outcome: Optional[bbeg_escalation.EscalationOutcome]


def apply_turn_changes(
    session: SessionSave,
    loaded_campaign: LoadedCampaign,
    parsed: ParsedTurn,
    turn_number: int,
) -> ApplySummary:
    """The ONLY place a validated TurnStateChanges actually mutates a
    SessionSave. Schema validation (parse_turn_response) already guaranteed
    types/ranges are sane; this function additionally checks things that
    require *current state* to evaluate (e.g. "is this a real location to
    move to?") which the standalone pydantic schema can't know on its own.

    Invalid-but-plausible proposals (an unreachable location, an unknown
    NPC id) are dropped with a warning rather than raising -- a single bad
    field in an otherwise-good turn shouldn't roll back the whole turn.
    """
    changes = parsed.state_changes
    world = session.world_state
    warnings: list[str] = []

    # -- location change: must be a real connection from the current spot --
    if changes.world.location_id:
        current = world.locations.get(world.location.current_location_id)
        target_id = changes.world.location_id
        if target_id not in world.locations:
            warnings.append(f"Ignored move to unknown location_id {target_id!r}")
        elif current is not None and target_id not in current.connections and target_id != world.location.current_location_id:
            warnings.append(
                f"Ignored move to {target_id!r} -- not reachable from "
                f"{world.location.current_location_id!r} (not in its connections list)"
            )
        else:
            world.location.current_location_id = target_id
            world.locations[target_id].discovered = True

    for loc_id in changes.world.discovered_locations:
        if loc_id in world.locations:
            world.locations[loc_id].discovered = True
        else:
            warnings.append(f"Ignored discovered_locations entry for unknown location_id {loc_id!r}")

    for npc_id, delta in changes.world.npc_disposition_deltas.items():
        if npc_id in world.npcs:
            world.adjust_disposition(npc_id, delta)
        else:
            warnings.append(f"Ignored disposition delta for unknown npc_id {npc_id!r}")

    for npc_id, status in changes.world.npc_status_changes.items():
        if npc_id in world.npcs:
            world.npcs[npc_id].status = status
        else:
            warnings.append(f"Ignored status change for unknown npc_id {npc_id!r}")

    for npc_id, facts in changes.world.npc_known_facts_added.items():
        if npc_id in world.npcs:
            world.npcs[npc_id].known_facts.extend(facts)
        else:
            warnings.append(f"Ignored known_facts for unknown npc_id {npc_id!r}")

    for quest_id, update in changes.world.quest_flag_updates.items():
        if quest_id in world.quests.flags:
            existing = world.quests.flags[quest_id]
            if update.status is not None:
                existing.status = update.status
            if update.notes is not None:
                existing.notes = update.notes
            if update.description is not None:
                existing.description = update.description
        else:
            # A brand-new quest flag -- requires a description to be worth creating.
            if update.description:
                world.quests.flags[quest_id] = QuestFlag(
                    description=update.description,
                    status=update.status or "not_started",
                    notes=update.notes or "",
                )
            else:
                warnings.append(
                    f"Ignored new quest flag {quest_id!r} -- no description provided"
                )

    world.flags.global_.update(changes.world.global_flag_updates)

    # -- per-character changes --
    for char_id, char_changes in changes.characters.items():
        if char_id not in session.characters:
            warnings.append(f"Ignored changes for unknown character_id {char_id!r}")
            continue
        character = session.characters[char_id]

        if char_changes.hp_delta:
            cap = max(1, math.ceil(character.combat.hp.maximum * MAX_NARRATIVE_HP_DELTA_FRACTION))
            delta = char_changes.hp_delta
            if abs(delta) > cap:
                clamped = cap if delta > 0 else -cap
                warnings.append(
                    f"Clamped hp_delta for {char_id!r} from {delta} to {clamped} "
                    f"(narrative HP changes are capped at {int(MAX_NARRATIVE_HP_DELTA_FRACTION*100)}% of max HP per turn)"
                )
                delta = clamped
            if delta < 0:
                character.combat.hp.current = max(0, character.combat.hp.current + delta)
            else:
                character.combat.hp.current = min(character.combat.hp.maximum, character.combat.hp.current + delta)

        for cond in char_changes.conditions_added:
            if cond not in character.conditions:
                character.conditions.append(cond)
        for cond in char_changes.conditions_removed:
            if cond in character.conditions:
                character.conditions.remove(cond)

        for item_dict in char_changes.inventory_added:
            try:
                character.equipment.inventory.append(Item(**item_dict))
            except ValidationError as e:
                warnings.append(f"Ignored malformed inventory item for {char_id!r}: {e}")
        if char_changes.inventory_removed_ids:
            keep_ids = set(char_changes.inventory_removed_ids)
            character.equipment.inventory = [
                i for i in character.equipment.inventory if i.id not in keep_ids
            ]

        for currency_key, delta in char_changes.currency_delta.items():
            if hasattr(character.equipment.currency, currency_key):
                current_value = getattr(character.equipment.currency, currency_key)
                setattr(character.equipment.currency, currency_key, max(0, current_value + delta))
            else:
                warnings.append(f"Ignored unknown currency key {currency_key!r} for {char_id!r}")

        if char_changes.notes_append:
            character.notes = (character.notes + "\n" if character.notes else "") + char_changes.notes_append

    # -- escalation: severity -> delta translation happens here, not in the model's output --
    escalation_outcome = None
    if changes.escalation_event:
        delta = bbeg_escalation.delta_for_severity(changes.escalation_event.severity)
        escalation_outcome = bbeg_escalation.apply_event(
            session.bbeg_tracker,
            loaded_campaign.stage_ladder,
            turn_number=turn_number,
            reason=changes.escalation_event.reason,
            counter_delta=delta,
        )

    return ApplySummary(warnings=warnings, escalation_outcome=escalation_outcome)