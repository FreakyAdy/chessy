"""
greedy_agent.py — Greedy Capture Agent
══════════════════════════════════════

Prioritises captures, especially capturing high-value pieces.
Falls back to random moves when no captures are available.
A step up from the random agent.
"""

from __future__ import annotations

import random

import chess

from chess_arena.arena.adapter import ChessAgent


# Piece values for greedy evaluation
_PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,  # can't actually capture king
}


class GreedyAgent(ChessAgent):
    """Captures the highest-value piece when possible, otherwise plays randomly."""

    def __init__(self, name: str = "GreedyBot", config: dict | None = None) -> None:
        super().__init__(name=name, config=config or {})
        seed = (config or {}).get("seed")
        self._rng = random.Random(seed)

    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        board = chess.Board(fen)

        captures = []
        non_captures = []

        for uci in legal_moves:
            move = chess.Move.from_uci(uci)
            if board.is_capture(move):
                # Score by value of captured piece
                captured = board.piece_at(move.to_square)
                value = _PIECE_VALUES.get(captured.piece_type, 0) if captured else 0
                # En passant: captured pawn isn't on the target square
                if captured is None and board.is_en_passant(move):
                    value = 1  # pawn
                # Bonus for promotion
                if move.promotion:
                    value += _PIECE_VALUES.get(move.promotion, 0)
                captures.append((uci, value))
            else:
                non_captures.append(uci)

        if captures:
            # Sort by value descending, pick the best (break ties randomly)
            captures.sort(key=lambda x: x[1], reverse=True)
            best_value = captures[0][1]
            best_captures = [c for c, v in captures if v == best_value]
            return self._rng.choice(best_captures)

        return self._rng.choice(non_captures)
