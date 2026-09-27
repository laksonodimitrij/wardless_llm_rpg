"""
engine/campaign_loader.py

Reads a campaign folder's authored JSON (manifest, locations, npcs,
escalation_stages, enemies) and assembles the objects a brand-new session
starts from: a WorldState seeded with that campaign's map and NPC roster, a
BBEGTracker seeded at stage 0 with the BBEG's base stats, the full
escalation ladder (for bbeg_escalation.py to consult all session long), and
the enemy roster (for spawning combat encounters).

This module owns all the file I/O for campaign content. engine/state.py
owns file I/O for session SAVES. bbeg_escalation.py stays pure logic with
no file access at all -- it's handed the ladder this module already parsed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from data.schemas.world_state import (
    WorldState, Location, NPC, Party, LocationPointer, Quests, Flags,
)
from data.schemas.bbeg_tracker import BBEGTracker, Escalation, StatBlock, HP as BbegHP
from data.schemas.enemy import EnemyRosterFile, Enemy

from .bbeg_escalation import StageDefinition, build_stage_ladder, stage_definition_for


@dataclass
class LoadedCampaign:
    manifest: dict                        # raw manifest["manifest"] content -- flavor/theme/act data
    world_state: WorldState
    bbeg_tracker: BBEGTracker
    enemy_roster: EnemyRosterFile
    stage_ladder: list[StageDefinition]

    def spawn_enemy(self, enemy_id: str) -> Enemy:
        """Returns a deep copy of an enemy template, ready to drop into an
        encounter. Enemies are stateless content -- mutating the returned
        copy (taking damage, dying) never touches the campaign's roster,
        so the same template can be spawned again in a later encounter."""
        template = self.enemy_roster.enemies[enemy_id]
        return template.model_copy(deep=True)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing campaign file: {path}")
    return json.loads(path.read_text())


def load_campaign(campaign_dir: Path | str, session_id: str) -> LoadedCampaign:
    """Assembles a fresh, never-played session's starting state from a
    campaign folder. Does NOT touch data/saves/ -- pass the result to
    engine/state.py's new_session() to get something you can actually save."""
    campaign_dir = Path(campaign_dir)

    manifest = _read_json(campaign_dir / "manifest.json")["manifest"]
    locations_raw = _read_json(campaign_dir / "locations.json")["locations"]
    npcs_raw = _read_json(campaign_dir / "npcs.json")["npcs"]
    stages_raw = _read_json(campaign_dir / "escalation_stages.json")["escalation_stages"]
    enemy_roster = EnemyRosterFile.model_validate_json(
        (campaign_dir / "enemies.json").read_text()
    )

    locations = {loc_id: Location(**loc) for loc_id, loc in locations_raw.items()}
    npcs = {npc_id: NPC(**npc) for npc_id, npc in npcs_raw.items()}

    world_state = WorldState(
        campaign_id=manifest["campaign_id"],
        session_id=session_id,
        turn_count=0,
        party=Party(character_ids=[]),
        location=LocationPointer(current_location_id=manifest["starting_location_id"]),
        locations=locations,
        npcs=npcs,
        quests=Quests(),
        flags=Flags(),
    )
    # The starting location should already be marked discovered -- the
    # party is standing in it turn one, they haven't "found" it.
    if world_state.location.current_location_id in world_state.locations:
        world_state.locations[world_state.location.current_location_id].discovered = True

    stage_ladder = build_stage_ladder(stages_raw)
    stage_zero = stage_definition_for(stage_ladder, 0).mechanical

    bbeg_info = manifest["bbeg"]
    bbeg_tracker = BBEGTracker(
        campaign_id=manifest["campaign_id"],
        bbeg_id=bbeg_info["id"],
        name=bbeg_info["name"],
        escalation=Escalation(counter=0, current_stage=stage_zero),
        stat_block=StatBlock(
            hp=BbegHP(**bbeg_info["base_stat_block"]["hp"]),
            armor_class=bbeg_info["base_stat_block"]["armor_class"],
            attack_bonus=bbeg_info["base_stat_block"]["attack_bonus"],
            damage=bbeg_info["base_stat_block"]["damage"],
            saving_throws=bbeg_info["base_stat_block"].get("saving_throws", {}),
            resistances=bbeg_info["base_stat_block"].get("resistances", []),
            immunities=bbeg_info["base_stat_block"].get("immunities", []),
            vulnerabilities=bbeg_info["base_stat_block"].get("vulnerabilities", []),
        ),
    )

    return LoadedCampaign(
        manifest=manifest,
        world_state=world_state,
        bbeg_tracker=bbeg_tracker,
        enemy_roster=enemy_roster,
        stage_ladder=stage_ladder,
    )


if __name__ == "__main__":
    loaded = load_campaign(
        Path(__file__).parent.parent / "data" / "campaigns" / "campaign_01_the_hollow_saint",
        session_id="smoke_test_session",
    )
    print("Loaded campaign:", loaded.manifest["title"])
    print("Starting location:", loaded.world_state.location.current_location_id,
          "-- discovered:", loaded.world_state.locations[loaded.world_state.location.current_location_id].discovered)
    print("NPCs seeded:", list(loaded.world_state.npcs.keys()))
    print("BBEG:", loaded.bbeg_tracker.name, "stage:", loaded.bbeg_tracker.escalation.current_stage.name)
    print("Enemy roster:", list(loaded.enemy_roster.enemies.keys()))

    spawned = loaded.spawn_enemy("aldric_voss")
    spawned.stat_block.hp.current = 1   # mutate the spawned copy
    print("Spawned copy HP after mutation:", spawned.stat_block.hp.current)
    print("Original template HP unaffected:", loaded.enemy_roster.enemies["aldric_voss"].stat_block.hp.current)