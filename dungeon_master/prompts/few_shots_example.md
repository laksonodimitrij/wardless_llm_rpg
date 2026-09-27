# Few-shot examples

These are worked examples of the expected turn output — narration followed by a `<state_changes>` block. Match this pattern: prose first, then exactly one state block, nothing after it.

---

## Example 1 — a small narrative choice, no combat, no escalation

**Player action:** "I ask Toby Reyes what happened to him — gently, not pushing."

**Expected output:**

Toby doesn't look up from the fence post he's mending. "Ten years," he says, like he's said it a hundred times already and the words have worn smooth. "Went to sleep twenty-two. Woke up thirty-two. No memory of any of it — not one day." He finally meets your eyes. "They call it a sacrifice. Ask them who *asked* to make it." He goes back to the fence. The conversation, clearly, is over for now — but he didn't tell you to leave.

```
<state_changes>
{
  "world": {
    "npc_disposition_deltas": { "toby_reyes": 5 },
    "npc_known_facts_added": {
      "toby_reyes": ["Spoke to the party about losing ten years to a sacrifice he never consented to."]
    }
  }
}
</state_changes>
```

*(Note the empty `characters` and no `escalation_event` — a quiet conversation doesn't need either. Don't force fields that don't apply.)*

---

## Example 2 — a resolved combat turn (mechanics already computed)

**Given mechanical facts for this turn:** "Thalindra's attack roll: hit, 7 damage dealt to the Communion Zealot (now 9/16 HP)."

**Player action:** "I loose another arrow at the zealot."

**Expected output:**

Your arrow catches the zealot mid-stride, punching through leather at the shoulder — he staggers, snarling something about mercy through gritted teeth, but he's still standing and still coming.

```
<state_changes>
{}
</state_changes>
```

*(The damage was already applied by game code before you narrated it — don't repeat it in `hp_delta`, and don't invent a different outcome than the one you were given. An empty `{}` is correct here; nothing structural changed beyond the HP the engine already tracked.)*

---

## Example 3 — a miracle's cost, plus an escalation event

**Player action:** "We watch as Elian performs the healing rite on the boy."

**Expected output:**

Elian kneels, murmurs words that don't sound quite like a prayer, and presses both palms to the boy's fevered chest. The fever breaks instantly — color floods back into the child's face, and Mira sobs with relief. But you catch it: the faintest flicker, like a held breath, cross Elian's own face. Something left him too, just for a moment. He recovers fast enough that no one else seems to notice.

Word of this will travel. A public healing, performed openly, in a village this small — by morning, everyone within a day's walk will have heard the Communion healed a dying child.

```
<state_changes>
{
  "world": {
    "npc_disposition_deltas": { "elian_thorn": 3, "mira_hallow": 10 },
    "npc_known_facts_added": {
      "mira_hallow": ["Witnessed her son's fever broken instantly by Elian Thorn's rite."]
    },
    "quest_flag_updates": {
      "investigate_windshear_miracle": {
        "status": "active",
        "description": "Find out what the healing in Windshear Hollow actually cost."
      }
    }
  },
  "escalation_event": {
    "reason": "A public healing miracle in Windshear Hollow spreads word of the Communion's power.",
    "severity": "minor"
  }
}
</state_changes>
```

*(This is a public, visible miracle — worth an `escalation_event`, but a small local one, not a mass sacrifice, so `minor` — not `major` or `pivotal`.)*