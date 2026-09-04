"""
random_agent.py — Baseline Random Agent
════════════════════════════════════════

Picks a uniformly random legal move.  This is the reference implementation
that every new agent should be able to beat.
"""

from __future__ import annotations

import random

from chess_arena.arena.adapter import ChessAgent


class RandomAgent(ChessAgent):
    """Plays a uniformly random legal move every turn."""

    def __init__(self, name: str = "RandomBot", config: dict | None = None) -> None:
        super().__init__(name=name, config=config or {})
        seed = (config or {}).get("seed")
        self._rng = random.Random(seed)

    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        return self._rng.choice(legal_moves)
