"""
sample_friend_bot.py — Custom Chess Agent for Chess Arena
═════════════════════════════════════════════════════════

A complete, fully-compliant custom chess agent you can upload directly
into the Chess Arena Web UI or CLI.

Strategy:
---------
- Prioritizes pawn promotions (queening).
- Evaluates piece captures using classical piece values (Q=9, R=5, B=3, N=3, P=1).
- Prefers tactical checks and controlling the center squares (e4, d4, e5, d5).
- Safe fallback guaranteeing 100% legal moves under all FIDE edge cases.
"""

from __future__ import annotations

import random
import chess

from chess_arena.arena.adapter import ChessAgent


class TacticalRaiderBot(ChessAgent):
    """An aggressive heuristic chess bot prioritizing captures, checks, and central control."""

    # Standard piece values in centipawns
    PIECE_VALUES = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
        chess.KING: 20000,
    }

    # Central squares bonus
    CENTER_SQUARES = {
        chess.E4, chess.D4, chess.E5, chess.D5,
        chess.C4, chess.F4, chess.C5, chess.F5,
    }

    def __init__(self, name: str = "TacticalRaider", config: dict | None = None) -> None:
        super().__init__(name=name, config=config or {})

    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        """Choose a move given the current FEN and list of legal UCI moves.

        Parameters
        ----------
        fen:
            Board state in Forsyth–Edwards Notation.
        legal_moves:
            List of legal moves in UCI format (e.g. ['e2e4', 'g1f3', ...]).

        Returns
        -------
        str:
            One strictly legal move in UCI format.
        """
        # Safety fallback
        if not legal_moves:
            return ""
        if len(legal_moves) == 1:
            return legal_moves[0]

        board = chess.Board(fen)
        best_move = legal_moves[0]
        best_score = -float("inf")

        for uci in legal_moves:
            try:
                move = chess.Move.from_uci(uci)
            except Exception:
                continue

            score = 0.0

            # 1. Pawn Promotion Bonus (Prioritize Queening)
            if move.promotion:
                if move.promotion == chess.QUEEN:
                    score += 850
                else:
                    score += 250

            # 2. Capture Bonus (MVV-LVA: Most Valuable Victim - Least Valuable Attacker)
            if board.is_capture(move):
                captured_piece = board.piece_at(move.to_square)
                attacker_piece = board.piece_at(move.from_square)

                victim_val = self.PIECE_VALUES.get(captured_piece.piece_type, 100) if captured_piece else 100
                attacker_val = self.PIECE_VALUES.get(attacker_piece.piece_type, 100) if attacker_piece else 100

                # Favorable exchange bonus
                score += (victim_val * 10) - (attacker_val // 2)

            # 3. Check Bonus
            board.push(move)
            if board.is_check():
                score += 60
            if board.is_checkmate():
                score += 100000  # Winning move!
            board.pop()

            # 4. Central Control Bonus
            if move.to_square in self.CENTER_SQUARES:
                score += 25

            # 5. Small random tie-breaker to prevent deterministic repetition
            score += random.uniform(0.0, 5.0)

            if score > best_score:
                best_score = score
                best_move = uci

        return best_move
