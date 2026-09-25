"""Ollama prompt builder and response parser for Liar's Dice.

The prompt is built from the seat's observation only, which holds its own hand
and never the opponent's, so an agent cannot be told what it may not know.
"""

from __future__ import annotations

import json
from typing import Any

from arena.agents.ollama._adapters import OllamaGameAdapter, register_ollama_adapter
from arena.games.liarsdice.actions import Bid, Call
from arena.games.liarsdice.definition import LIARSDICE_GAME_ID


class LiarsDicePromptBuilder:
    """Build Ollama chat messages and parse responses for Liar's Dice."""

    SYSTEM_PROMPT = (
        "You are an expert player of Liar's Dice, a two-player bluffing game.\n"
        "Each player has a hidden hand of dice. You see only your own.\n"
        "Players take turns. On your turn you either:\n"
        "- BID: claim that at least QUANTITY dice among BOTH hands show FACE. Your bid must "
        "raise the standing bid: more dice, or the same number of a higher face.\n"
        "- CALL: challenge the standing bid. Both hands are revealed. If the bid was true "
        "you lose a die; if it was false, the bidder loses one.\n"
        "Losing all your dice loses the game. The loser of each round bids first next round.\n\n"
        "Strategy:\n"
        "- Count how many of each face you hold; the opponent's dice are unknown, and each "
        "shows a given face with probability 1/faces.\n"
        "- Expected count of a face = your matching dice + opponent dice / faces.\n"
        "- Call when the standing bid is well above that expectation; otherwise raise, "
        "preferably on a face you hold.\n\n"
        "Respond with a JSON object."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        me = observation.seat
        counts = observation.dice_counts
        opponent_dice = counts[1 - me]
        mine = sorted(observation.my_dice)
        tally = {face: mine.count(face) for face in range(1, observation.faces + 1)}
        bids = observation.bids
        standing = bids[-1] if bids else None
        can_call = any(isinstance(a, Call) for a in observation.legal_actions)

        lines = [
            f"You are seat {me}. Round {observation.round_number}. Dice are 1-{observation.faces}.",
            f"Your dice: {mine} (count per face: {json.dumps(tally)}).",
            f"Opponent has {opponent_dice} hidden dice; {sum(counts)} dice are in play in total.",
        ]
        if standing is not None:
            history = ", ".join(f"{b.quantity} x {b.face}" for b in bids)
            lines.append(f"Bids this round, oldest first: {history}.")
            lines.append(
                f"Standing bid: at least {standing.quantity} dice showing {standing.face}. "
                f"You hold {tally.get(standing.face, 0)} of them."
            )
        else:
            lines.append("No bid yet this round: you must open with a bid.")
        showdown = observation.last_showdown
        if showdown is not None:
            lines.append(
                f"Last round: seat {showdown.caller} called {showdown.bid.quantity} x "
                f"{showdown.bid.face}; there were {showdown.count}; "
                f"seat {showdown.loser} lost a die."
            )
        # Legality is stated from the actual legal actions, never re-derived: a
        # prompt that invites an impossible bid makes a small model burn every
        # retry (e.g. at the maximum bid, where only a call remains).
        legal_bids = [a for a in observation.legal_actions if isinstance(a, Bid)]
        if not legal_bids and can_call:
            lines.append(
                f"No higher bid exists ({sum(counts)} dice in play, faces up to "
                f"{observation.faces}). Your ONLY legal move is to call."
            )
            lines.append('Respond with JSON: {"thought": "<one sentence>", "action": "call"}')
        else:
            smallest = ", ".join(f"{b.quantity} x {b.face}" for b in legal_bids[:3])
            cap = f"A bid can claim at most {sum(counts)} dice (all dice in play)."
            if standing is not None:
                lines.append(
                    f"A bid must beat {standing.quantity} x {standing.face}: more dice, or "
                    f"as many dice of a higher face. {cap} Smallest legal raises: {smallest}."
                )
            else:
                lines.append(f"{cap} Smallest legal bids: {smallest}.")
            options = '"bid"' + (' or "call"' if can_call else "")
            lines.append(
                f'Respond with JSON: {{"thought": "<one sentence>", "action": {options}, '
                '"quantity": <int, for a bid>, "face": <int, for a bid>}'
            )
        if retry_feedback:
            items = "\n".join(f" - {f}" for f in retry_feedback)
            lines.append(f"Previous attempts were rejected:\n{items}")
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

    def parse_response(self, content: str, observation: Any) -> Any | None:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        kind = data.get("action")
        if not isinstance(kind, str):
            return None
        kind = kind.strip().lower()
        if kind == "call":
            action: Any = Call()
        elif kind == "bid":
            quantity, face = data.get("quantity"), data.get("face")
            if type(quantity) is not int or type(face) is not int:
                return None
            try:
                action = Bid(quantity=quantity, face=face)
            except ValueError:
                return None
        else:
            return None
        return action if action in observation.legal_actions else None

    def format_spec(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "action": {"type": "string", "enum": ["bid", "call"]},
                "quantity": {"type": "integer", "minimum": 1},
                "face": {"type": "integer", "minimum": 1},
            },
            "required": ["thought", "action"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return (
            "Response was not a legal move: a bid must raise the standing bid (more dice, "
            "or as many of a higher face) without claiming more dice than are in play, "
            "and you can only call a standing bid. "
            f"Raw content: {raw_content[:200]}"
        )


register_ollama_adapter(
    OllamaGameAdapter(
        game_id=LIARSDICE_GAME_ID,
        prompt_builder_factory=LiarsDicePromptBuilder,
    )
)


__all__: tuple[str, ...] = ("LiarsDicePromptBuilder",)
