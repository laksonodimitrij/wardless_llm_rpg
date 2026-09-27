"""
engine/state.py

Owns everything about a session's on-disk save file:
data/saves/session_<id>.json. A save bundles the three things a running
game needs together -- the party's characters, the world state, and the
BBEG tracker -- into one file per session, matching the original folder
plan's "a player's live game state" description.

SessionSave is defined here rather than in data/schemas/ because it's not
a fundamental data shape like Character/WorldState/BBEGTracker -- it's just
those three things zipped together for convenience at the engine layer.
If you later want multiple save slots, autosave-on-mutate, or save
versioning, this is the file to extend -- data/schemas/ stays untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from data.schemas.character import Character
from data.schemas.world_state import WorldState
from data.schemas.bbeg_tracker import BBEGTracker

from .campaign_loader import LoadedCampaign


class SessionSave(BaseModel):
    session_id: str
    campaign_id: str
    characters: dict[str, Character] = Field(default_factory=dict)   # character_id -> Character
    world_state: WorldState
    bbeg_tracker: BBEGTracker


def new_session(loaded_campaign: LoadedCampaign, session_id: str, characters: list[Character]) -> SessionSave:
    """Builds a fresh SessionSave from a just-loaded campaign (see
    campaign_loader.load_campaign) plus the party's characters. Doesn't
    write anything to disk -- call save_session() for that."""
    world_state = loaded_campaign.world_state.model_copy(deep=True)
    world_state.session_id = session_id
    world_state.party.character_ids = [c.id for c in characters]
    return SessionSave(
        session_id=session_id,
        campaign_id=loaded_campaign.manifest["campaign_id"],
        characters={c.id: c for c in characters},
        world_state=world_state,
        bbeg_tracker=loaded_campaign.bbeg_tracker.model_copy(deep=True),
    )


def _session_path(saves_dir: Path | str, session_id: str) -> Path:
    return Path(saves_dir) / f"session_{session_id}.json"


def save_session(session: SessionSave, saves_dir: Path | str) -> Path:
    """Writes the save file, wrapped in a top-level "session" key -- same
    one-key-per-file convention as character/world_state/bbeg_tracker."""
    saves_dir = Path(saves_dir)
    saves_dir.mkdir(parents=True, exist_ok=True)
    path = _session_path(saves_dir, session.session_id)
    wrapped = {"session": json.loads(session.model_dump_json(by_alias=True))}
    path.write_text(json.dumps(wrapped, indent=2))
    return path


def load_session(saves_dir: Path | str, session_id: str) -> SessionSave:
    path = _session_path(saves_dir, session_id)
    if not path.exists():
        raise FileNotFoundError(f"No save found at {path}")
    data = json.loads(path.read_text())
    return SessionSave(**data["session"])


def session_exists(saves_dir: Path | str, session_id: str) -> bool:
    return _session_path(saves_dir, session_id).exists()


# ---------------------------------------------------------------------------
# Small mutation helpers -- convenience only. The actual math lives in
# rules_5e.py; these just save you from writing
# `session.characters[cid].combat.hp` at every call site.
# ---------------------------------------------------------------------------

def get_character(session: SessionSave, character_id: str) -> Character:
    if character_id not in session.characters:
        raise KeyError(f"No character {character_id!r} in this session")
    return session.characters[character_id]


def advance_turn(session: SessionSave) -> int:
    session.world_state.turn_count += 1
    return session.world_state.turn_count


if __name__ == "__main__":
    import tempfile
    from data.schemas.character import Identity, Stats, Combat, HP, HitDice
    from .campaign_loader import load_campaign

    campaign_dir = Path(__file__).parent.parent / "data" / "campaigns" / "campaign_01_the_hollow_saint"
    loaded = load_campaign(campaign_dir, session_id="smoke_test_session")

    thalindra = Character(
        id="pc_thalindra", name="Thalindra Nightwhisper",
        identity=Identity(race="Wood Elf", char_class="Ranger", level=3),
        stats=Stats(strength=12, dexterity=18, constitution=14, intelligence=10, wisdom=15, charisma=8),
        combat=Combat(armor_class=15, hp=HP(current=24, maximum=28), hit_dice=HitDice(type="d10", maximum=3, remaining=3)),
    )

    session = new_session(loaded, session_id="smoke_test_session", characters=[thalindra])
    advance_turn(session)
    advance_turn(session)

    with tempfile.TemporaryDirectory() as tmp:
        saved_path = save_session(session, tmp)
        print("Saved to:", saved_path)

        reloaded = load_session(tmp, "smoke_test_session")
        print("Reloaded OK. Turn count:", reloaded.world_state.turn_count)
        print("Reloaded character:", get_character(reloaded, "pc_thalindra").name,
              "HP:", get_character(reloaded, "pc_thalindra").combat.hp)
        print("Reloaded BBEG stage:", reloaded.bbeg_tracker.escalation.current_stage.name)
        print("Round-trip characters match:",
              reloaded.characters["pc_thalindra"] == session.characters["pc_thalindra"])