"""
engine/bbeg_escalation.py

This module owns the ONE rule that matters for the whole "BBEG grows
stronger" system: the LLM narrates what happened in the story ("a ritual
candle was lit," "the party failed to stop the marsh ritual"), but only
this module decides how much that's worth in escalation_counter and
whether it crosses a stage threshold. BBEGTracker.log_event() (in
data/schemas/bbeg_tracker.py) is the low-level mutation; apply_event()
below is the sanctioned, high-level entry point everything else should
call instead of touching the tracker directly.

Why a separate StageDefinition wrapper instead of just using EscalationStage:
escalation_stages.json (authored campaign content) carries narrative-only
fields -- "world_effects", "core_question_focus", "act" -- that aren't part
of the strict EscalationStage schema (see data/schemas/bbeg_tracker.py).
Those fields get silently dropped if you construct EscalationStage(**raw)
directly. StageDefinition keeps both: `.mechanical` (what gets written into
the tracker) and `.raw` (the full authored dict, so the DM prompt can still
say "the party has just triggered <world_effects>" when a stage flips).
"""

from __future__ import annotations

from dataclasses import dataclass

from data.schemas.bbeg_tracker import BBEGTracker, EscalationStage


@dataclass
class StageDefinition:
    mechanical: EscalationStage   # the trimmed shape that lives in the tracker
    raw: dict                     # the full authored entry, narrative fields included


@dataclass
class EscalationOutcome:
    """What apply_event() hands back -- enough for the DM/engine layer to
    narrate the consequence without re-deriving it."""
    counter_before: int
    counter_after: int
    stage_changed: bool
    previous_stage_index: int
    new_stage_index: int
    new_stage_name: str
    world_effects: str | None       # only set when stage_changed is True
    core_question_focus: list[str] | None
    is_final_stage: bool


# The LLM never gets to pick escalation_counter's delta directly -- it
# reports a story event and tags how significant it seemed ("minor" ..
# "pivotal"); this table is the ONLY place that severity turns into an
# actual number. Keeping the mapping here (not in dm/) means every
# severity->delta decision is made by engine code, not model output.
EVENT_SEVERITY_DELTAS: dict[str, int] = {
    "minor": 3,       # a small kindness, a quiet miracle, background rumor
    "moderate": 8,     # a public miracle, a coerced (but small) sacrifice
    "major": 18,       # a mass sacrifice, an assassination, open conflict
    "pivotal": 30,     # ritual milestones, campaign-defining turning points
}


def delta_for_severity(severity: str) -> int:
    try:
        return EVENT_SEVERITY_DELTAS[severity]
    except KeyError:
        raise ValueError(
            f"Unknown severity {severity!r}; expected one of {list(EVENT_SEVERITY_DELTAS)}"
        )


def build_stage_ladder(raw_stages: list[dict]) -> list[StageDefinition]:
    """Turns escalation_stages.json's raw list into StageDefinitions,
    sorted ascending by threshold (authoring order should already match
    this, but we don't trust file order over the actual threshold values)."""
    ladder = [StageDefinition(mechanical=EscalationStage(**s), raw=s) for s in raw_stages]
    ladder.sort(key=lambda sd: sd.mechanical.threshold)
    return ladder


def _stage_for_counter(ladder: list[StageDefinition], counter: int) -> StageDefinition:
    """The current stage is the highest-threshold stage the counter has
    reached or passed. Falls back to the first stage if somehow the
    counter is below every threshold (shouldn't happen if stage 0 has
    threshold 0, but defensive rather than crashing mid-session)."""
    eligible = [sd for sd in ladder if sd.mechanical.threshold <= counter]
    if not eligible:
        return ladder[0]
    return max(eligible, key=lambda sd: sd.mechanical.threshold)


def apply_event(
    tracker: BBEGTracker,
    ladder: list[StageDefinition],
    turn_number: int,
    reason: str,
    counter_delta: int,
) -> EscalationOutcome:
    """THE sanctioned way the BBEG grows. Call this after deciding a story
    event is significant enough to matter -- never call tracker.log_event()
    directly from dm/ or cli/ code, or the stage ladder and the counter can
    drift out of sync."""
    counter_before = tracker.escalation.counter
    previous_stage_index = tracker.escalation.current_stage.stage_index

    tracker.log_event(turn_number=turn_number, reason=reason, counter_delta=counter_delta)

    new_stage_def = _stage_for_counter(ladder, tracker.escalation.counter)
    stage_changed = new_stage_def.mechanical.stage_index != previous_stage_index
    if stage_changed:
        tracker.escalation.current_stage = new_stage_def.mechanical

    return EscalationOutcome(
        counter_before=counter_before,
        counter_after=tracker.escalation.counter,
        stage_changed=stage_changed,
        previous_stage_index=previous_stage_index,
        new_stage_index=new_stage_def.mechanical.stage_index,
        new_stage_name=new_stage_def.mechanical.name,
        world_effects=new_stage_def.raw.get("world_effects") if stage_changed else None,
        core_question_focus=new_stage_def.raw.get("core_question_focus") if stage_changed else None,
        is_final_stage=(new_stage_def.mechanical.stage_index == ladder[-1].mechanical.stage_index),
    )


def stage_definition_for(ladder: list[StageDefinition], stage_index: int) -> StageDefinition:
    """Look up a stage's full (mechanical + raw) definition by index --
    e.g. for campaign_loader.py to fetch stage 0 when seeding a new session."""
    for sd in ladder:
        if sd.mechanical.stage_index == stage_index:
            return sd
    raise KeyError(f"No stage with stage_index={stage_index} in this ladder")