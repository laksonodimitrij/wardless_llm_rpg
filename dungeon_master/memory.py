"""
dm/memory.py

Keeps the context fed to the model bounded as a campaign runs long. Recent
turns are kept verbatim (player action + narration) up to
`max_recent_turns`; anything older gets folded into a single rolling prose
summary instead of being dropped, so early-campaign facts (a promise made
to Elder Maren in turn 3) aren't just lost by turn 80.

Compressing old turns into the rolling summary requires an LLM call (using
prompts/summarizer_prompt.md), but this module doesn't import llm_client.py
directly -- compress_if_needed() takes a `chat_fn: Callable[[list[dict]],
str]` instead. That's dependency injection: cli/play.py wires in the real
LLMClient.chat, while tests can pass a fake function that returns a fixed
string, with no network involved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

ChatFn = Callable[[list[dict]], str]

_SUMMARIZER_PROMPT_PATH = Path(__file__).parent / "prompts" / "summarizer_prompt.md"


class TurnRecord(BaseModel):
    turn_number: int
    player_action: str
    narration: str


class Memory(BaseModel):
    rolling_summary: str = ""
    recent_turns: list[TurnRecord] = Field(default_factory=list)
    max_recent_turns: int = 8

    def add_turn(self, turn_number: int, player_action: str, narration: str) -> None:
        self.recent_turns.append(
            TurnRecord(turn_number=turn_number, player_action=player_action, narration=narration)
        )

    def needs_compression(self) -> bool:
        return len(self.recent_turns) > self.max_recent_turns

    def compress_if_needed(self, chat_fn: ChatFn) -> bool:
        """If we're over the recent-turns budget, folds the oldest turns
        into rolling_summary via chat_fn and drops them from recent_turns.
        Returns whether compression actually happened (so callers can log
        it / show a 'the DM takes a moment to recall...' beat)."""
        if not self.needs_compression():
            return False

        overflow_count = len(self.recent_turns) - self.max_recent_turns
        to_compress = self.recent_turns[:overflow_count]
        self.recent_turns = self.recent_turns[overflow_count:]

        summarizer_prompt = _SUMMARIZER_PROMPT_PATH.read_text()
        turns_text = "\n\n".join(
            f"Turn {t.turn_number} -- player action: {t.player_action}\nWhat happened: {t.narration}"
            for t in to_compress
        )
        messages = [
            {"role": "system", "content": summarizer_prompt},
            {
                "role": "user",
                "content": (
                    f"Existing summary so far:\n{self.rolling_summary or '(none yet -- this is the first compression)'}\n\n"
                    f"New turns to fold in:\n{turns_text}"
                ),
            },
        ]
        self.rolling_summary = chat_fn(messages).strip()
        return True

    def context_block(self) -> str:
        """Formats memory as plain text for inclusion in the next turn's
        prompt -- this is what actually gets handed to the model, not the
        Memory object itself."""
        parts = []
        if self.rolling_summary:
            parts.append(f"## Story so far\n{self.rolling_summary}")
        if self.recent_turns:
            recent_text = "\n\n".join(
                f"Turn {t.turn_number} -- player did: {t.player_action}\n{t.narration}"
                for t in self.recent_turns
            )
            parts.append(f"## Recent turns\n{recent_text}")
        return "\n\n".join(parts) if parts else "(campaign just started -- no history yet)"


if __name__ == "__main__":
    # Smoke test with a fake chat_fn -- no network, no real model needed.
    def fake_chat_fn(messages: list[dict]) -> str:
        return "Fake summary: the party met Elian Thorn and Mira Hallow in Windshear Hollow."

    memory = Memory(max_recent_turns=3)
    for i in range(1, 6):
        memory.add_turn(turn_number=i, player_action=f"Player action {i}", narration=f"Narration for turn {i}.")

    print("Before compression -- recent_turns count:", len(memory.recent_turns))
    compressed = memory.compress_if_needed(fake_chat_fn)
    print("Compression happened:", compressed)
    print("recent_turns count after:", len(memory.recent_turns))
    print("rolling_summary:", memory.rolling_summary)
    print()
    print("context_block():\n", memory.context_block())