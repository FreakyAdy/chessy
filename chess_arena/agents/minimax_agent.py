"""
minimax_agent.py — Simple Minimax Agent
═══════════════════════════════════════

Uses a basic minimax search with alpha-beta pruning and a simple
material evaluation function.  Depth is configurable (default: 3).
"""

from __future__ import annotations

import random
from typing import Optional

import chess

from chess_arena.arena.adapter import ChessAgent


# Standard piece values for material evaluation
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# Piece-square tables for positional bonus (simplified)
_PAWN_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]

_KNIGHT_TABLE = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]


def _evaluate(board: chess.Board) -> float:
    """Static evaluation: material + simple piece-square tables.

    Returns a score from White's perspective (positive = White is better).
    """
    if board.is_checkmate():
        return -9999 if board.turn == chess.WHITE else 9999
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0.0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        value = _PIECE_VALUES.get(piece.piece_type, 0)

        # Positional bonus
        if piece.color == chess.WHITE:
            idx = sq
        else:
            idx = chess.square_mirror(sq)

        if piece.piece_type == chess.PAWN:
            value += _PAWN_TABLE[idx]
        elif piece.piece_type == chess.KNIGHT:
            value += _KNIGHT_TABLE[idx]

        if piece.color == chess.WHITE:
            score += value
        else:
            score -= value

    return score


def _minimax(
    board: chess.Board,
    depth: int,
    alpha: float,
    beta: float,
    maximizing: bool,
) -> float:
    """Minimax with alpha-beta pruning."""
    if depth == 0 or board.is_game_over():
        return _evaluate(board)

    if maximizing:
        max_eval = -float("inf")
        for move in board.legal_moves:
            board.push(move)
            eval_score = _minimax(board, depth - 1, alpha, beta, False)
            board.pop()
            max_eval = max(max_eval, eval_score)
            alpha = max(alpha, eval_score)
            if beta <= alpha:
                break
        return max_eval
    else:
        min_eval = float("inf")
        for move in board.legal_moves:
            board.push(move)
            eval_score = _minimax(board, depth - 1, alpha, beta, True)
            board.pop()
            min_eval = min(min_eval, eval_score)
            beta = min(beta, eval_score)
            if beta <= alpha:
                break
        return min_eval


class MinimaxAgent(ChessAgent):
    """Minimax with alpha-beta pruning and basic material evaluation.

    Config options:
        depth (int): Search depth (default: 3). Higher = stronger but slower.
    """

    def __init__(self, name: str = "MinimaxBot", config: dict | None = None) -> None:
        super().__init__(name=name, config=config or {})
        self.depth = (config or {}).get("depth", 3)
        seed = (config or {}).get("seed")
        self._rng = random.Random(seed)

    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        board = chess.Board(fen)
        maximizing = board.turn == chess.WHITE

        best_score = -float("inf") if maximizing else float("inf")
        best_moves: list[str] = []

        for uci in legal_moves:
            move = chess.Move.from_uci(uci)
            board.push(move)
            score = _minimax(
                board, self.depth - 1,
                -float("inf"), float("inf"),
                not maximizing,
            )
            board.pop()

            if maximizing:
                if score > best_score:
                    best_score = score
                    best_moves = [uci]
                elif score == best_score:
                    best_moves.append(uci)
            else:
                if score < best_score:
                    best_score = score
                    best_moves = [uci]
                elif score == best_score:
                    best_moves.append(uci)

        return self._rng.choice(best_moves) if best_moves else legal_moves[0]
