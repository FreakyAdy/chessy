"""
center_control_agent.py — Center Control Agent
═══════════════════════════════════════════════

Prioritises moves that control the centre of the board (d4, d5, e4, e5)
and develops pieces early.  A simple positional heuristic.
"""

from __future__ import annotations

import random

import chess

from chess_arena.arena.adapter import ChessAgent


# Centre squares weighted by importance
_CENTER_SQUARES = {
    chess.D4: 3, chess.D5: 3, chess.E4: 3, chess.E5: 3,
    chess.C3: 1, chess.C4: 2, chess.C5: 2, chess.C6: 1,
    chess.D3: 2, chess.D6: 2,
    chess.E3: 2, chess.E6: 2,
    chess.F3: 1, chess.F4: 2, chess.F5: 2, chess.F6: 1,
}


class CenterControlAgent(ChessAgent):
    """Moves pieces towards the centre, develops knights/bishops early."""

    def __init__(self, name: str = "CenterBot", config: dict | None = None) -> None:
        super().__init__(name=name, config=config or {})
        seed = (config or {}).get("seed")
        self._rng = random.Random(seed)

    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        board = chess.Board(fen)
        scored: list[tuple[str, float]] = []

        for uci in legal_moves:
            move = chess.Move.from_uci(uci)
            score = 0.0

            # Reward landing on centre squares
            score += _CENTER_SQUARES.get(move.to_square, 0)

            # Reward captures
            if board.is_capture(move):
                captured = board.piece_at(move.to_square)
                if captured:
                    score += captured.piece_type  # rough value

            # Reward developing minor pieces
            piece = board.piece_at(move.from_square)
            if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
                # Moving from back rank = development
                from_rank = chess.square_rank(move.from_square)
                if (piece.color == chess.WHITE and from_rank == 0) or \
                   (piece.color == chess.BLACK and from_rank == 7):
                    score += 2

            # Reward castling
            if board.is_castling(move):
                score += 4

            # Promotion bonus
            if move.promotion:
                score += 8

            # Small randomness to break ties
            score += self._rng.random() * 0.5

            scored.append((uci, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]
