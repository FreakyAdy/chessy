"""
template_agent.py — Starter Template for Community / Friend Chess Models
═════════════════════════════════════════════════════════════════════════

Share this template with your friends! To build an eligible competition bot:
  1. Subclass `ChessAgent`
  2. Implement `get_move(self, board_fen: str, legal_moves: list[str]) -> str`
  3. Ensure your return move is always one of the UCI strings in `legal_moves`
  4. Run `python verify_agent.py uploaded_agents/template_agent.py` to audit!
"""

from __future__ import annotations

import random
from typing import Optional

import chess
from chess_arena.arena.adapter import ChessAgent


class CommunityFriendAgent(ChessAgent):
    """Example custom agent ready for tournament qualification."""

    def __init__(self, name: str = "FriendBot", config: Optional[dict] = None) -> None:
        super().__init__(name=name, config=config)
        self.seed = self.config.get("seed", 42)
        self.rng = random.Random(self.seed)

    def get_move(self, board_fen: str, legal_moves: list[str]) -> str:
        """Select a move from the available legal moves.

        Parameters
        ----------
        board_fen : str
            Current position in Forsyth–Edwards Notation (FEN).
        legal_moves : list[str]
            Non-empty list of strictly legal UCI move strings (e.g. ['e2e4', 'd2d4']).

        Returns
        -------
        str
            A UCI string chosen from ``legal_moves``.
        """
        if not legal_moves:
            return ""

        board = chess.Board(board_fen)

        # 1. Prefer captures
        capture_moves = [
            m.uci() for m in board.legal_moves if board.is_capture(m)
        ]
        if capture_moves:
            return self.rng.choice(capture_moves)

        # 2. Prefer center control (e4, d4, e5, d5)
        center_squares = {chess.E4, chess.D4, chess.E5, chess.D5}
        center_moves = [
            m.uci() for m in board.legal_moves if m.to_square in center_squares
        ]
        if center_moves:
            return self.rng.choice(center_moves)

        # 3. Fallback to random legal move
        return self.rng.choice(legal_moves)
