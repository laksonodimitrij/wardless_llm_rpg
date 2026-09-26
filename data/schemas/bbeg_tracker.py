"""
data/schemas/bbeg_tracker.py

Canonical pydantic model for the BBEG escalation tracker. Field-for-field
mirror of data/schemas/templates/bbeg_tracker_template.json.

Load with:
    BBEGTrackerFile.model_validate_json(open(path).read())
Write back out with:
    file.model_dump_json(indent=2)

Design notes:
- `escalation.counter` is a single monotonic int. Anything that should make
  the BBEG scarier (turns passed, a ritual completed, an ally slain) calls
  `log_event()`, which is the ONLY way the counter changes and the only
  place a history entry gets written. The LLM reports what happened in the
  story ("a ritual candle was lit"); the engine (bbeg_escalation.py) is what
  decides how much that's worth and whether it crosses a stage threshold —
  never the LLM directly.
- `escalation.current_stage` is a snapshot copied in from the campaign's
  escalation_stages.json (data/campaigns/<id>/) whenever a threshold is
  crossed. This file only holds the *current* stage, not the full ladder of
  stages — that ladder is campaign content, not runtime save state.
- `stat_block` intentionally uses loose dicts for saving_throws (not a
  bounded enum-keyed model) since a homebrew BBEG's save proficiencies
  shouldn't be constrained by this schema.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .common import NamedFeature


# ---------------------------------------------------------------------------
# escalation
# ---------------------------------------------------------------------------

class EscalationStage(BaseModel):
    stage_index: int = 0
    name: str = ""
    threshold: int = 0
    description: str = ""
    stat_modifiers: dict[str, int] = Field(default_factory=dict)   # {"armor_class": 2}
    new_abilities: list[str] = Field(default_factory=list)


class Escalation(BaseModel):
    counter: int = 0
    current_stage: EscalationStage = Field(default_factory=EscalationStage)


# ---------------------------------------------------------------------------
# stat block
# ---------------------------------------------------------------------------

class HP(BaseModel):
    current: int = 1
    maximum: int = 1


class StatBlock(BaseModel):
    hp: HP = Field(default_factory=HP)
    armor_class: int = 10
    attack_bonus: int = 0
    damage: str = ""                       # dice notation, e.g. "2d10+5"
    saving_throws: dict[str, int] = Field(default_factory=dict)   # {"wisdom": 5}
    resistances: list[str] = Field(default_factory=list)
    immunities: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# abilities
# ---------------------------------------------------------------------------

class BBEGAbilities(BaseModel):
    actions: list[NamedFeature] = Field(default_factory=list)
    legendary_actions: list[NamedFeature] = Field(default_factory=list)
    lair_actions: list[NamedFeature] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

class EscalationEvent(BaseModel):
    turn_number: int = 0
    reason: str = ""
    counter_delta: int = 0


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

class BBEGState(BaseModel):
    is_defeated: bool = False
    is_aware_of_party: bool = False
    current_location_id: str = ""


# ---------------------------------------------------------------------------
# top-level tracker + file wrapper
# ---------------------------------------------------------------------------

class BBEGTracker(BaseModel):
    campaign_id: str = ""
    bbeg_id: str = ""
    name: str = ""

    escalation: Escalation = Field(default_factory=Escalation)
    stat_block: StatBlock = Field(default_factory=StatBlock)
    abilities: BBEGAbilities = Field(default_factory=BBEGAbilities)
    history: list[EscalationEvent] = Field(default_factory=list)
    state: BBEGState = Field(default_factory=BBEGState)
    notes: str = ""

    # -- helpers ------------------------------------------------------------

    def log_event(self, turn_number: int, reason: str, counter_delta: int) -> None:
        """The only sanctioned way escalation.counter changes. The engine
        calls this after deciding an event is significant; the LLM never
        writes to escalation.counter directly."""
        self.escalation.counter += counter_delta
        self.history.append(
            EscalationEvent(turn_number=turn_number, reason=reason, counter_delta=counter_delta)
        )

    def effective_stat(self, key: str) -> int | None:
        base = getattr(self.stat_block, key, None)
        if not isinstance(base, int):
            return None
        mod = self.escalation.current_stage.stat_modifiers.get(key, 0)
        return base + mod


class BBEGTrackerFile(BaseModel):
    """Root object matching the on-disk template: {"bbeg_tracker": {...}}."""
    bbeg_tracker: BBEGTracker = Field(default_factory=BBEGTracker)


if __name__ == "__main__":
    import json
    from pathlib import Path

    template_path = Path(__file__).parent / "templates" / "bbeg_tracker_template.json"
    original = json.loads(template_path.read_text())
    blank = BBEGTrackerFile.model_validate_json(template_path.read_text())
    dumped = json.loads(blank.model_dump_json())
    print("Loaded blank template OK. Round-trip matches:", dumped == original)

    filled = BBEGTrackerFile(
        bbeg_tracker=BBEGTracker(
            campaign_id="campaign_01_shadowfen",
            bbeg_id="the_drowned_choir",
            name="The Drowned Choir",
            escalation=Escalation(
                counter=12,
                current_stage=EscalationStage(
                    stage_index=1,
                    name="Whispering Shadow",
                    threshold=10,
                    description="The Choir's voice can now be heard in dreams across the whole Shadowfen.",
                    stat_modifiers={"armor_class": 1, "attack_bonus": 1},
                    new_abilities=["Dream Whisper (fear effect, once per long rest)"],
                ),
            ),
            stat_block=StatBlock(
                hp=HP(current=180, maximum=180),
                armor_class=16,
                attack_bonus=7,
                damage="2d10+5",
            ),
        )
    )
    filled.bbeg_tracker.log_event(turn_number=15, reason="Party failed to stop the marsh ritual", counter_delta=3)
    print(filled.model_dump_json(indent=2))
    print("Effective AC:", filled.bbeg_tracker.effective_stat("armor_class"))