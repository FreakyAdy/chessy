"""
referee.py — Move Validator & Game Arbiter
══════════════════════════════════════════

The Referee is the **single source of truth**.  It:

* Validates every move against `python-chess`'s legal-move generator.
* Detects check, checkmate, stalemate, and all draw conditions.
* Returns structured :pyclass:`MoveResult` objects so the runner / UI can
  act on them uniformly.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional

import chess

from chess_arena.arena.board import BoardState


# ═════════════════════════════════════════════════════════════════════════════
#  Enums & Result Types
# ═════════════════════════════════════════════════════════════════════════════

class MoveValidity(enum.Enum):
    """Whether a move was accepted by the referee."""
    LEGAL = "LEGAL"
    ILLEGAL = "ILLEGAL"


class GameStatus(enum.Enum):
    """Status of the game after a move (or at any query point)."""
    ONGOING = "ONGOING"
    CHECK = "CHECK"
    CHECKMATE = "CHECKMATE"
    STALEMATE = "STALEMATE"
    DRAW_FIFTY_MOVE = "DRAW (50-move rule)"
    DRAW_THREEFOLD = "DRAW (threefold repetition)"
    DRAW_INSUFFICIENT = "DRAW (insufficient material)"
    DRAW_AGREEMENT = "DRAW (by agreement)"
    FORFEIT = "FORFEIT"


@dataclass(frozen=True)
class MoveResult:
    """Structured outcome returned after every move attempt."""

    validity: MoveValidity
    reason: str                           # human-readable explanation
    fen: str                              # board FEN after the move (or unchanged if illegal)
    game_status: GameStatus
    move_number: int                      # fullmove counter
    active_color: str                     # whose turn it is AFTER the move
    move_uci: str                         # the move that was attempted
    san: Optional[str] = None             # Standard Algebraic Notation (only for legal moves)

    def __str__(self) -> str:
        lines = [
            f"Move    : {self.move_uci}" + (f"  ({self.san})" if self.san else ""),
            f"Status  : {self.validity.value}" + (f" — {self.reason}" if self.validity == MoveValidity.ILLEGAL else ""),
            f"FEN     : {self.fen}",
            f"Game    : {self.game_status.value}",
            f"Turn    : {self.active_color} (move {self.move_number})",
        ]
        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  Referee
# ═════════════════════════════════════════════════════════════════════════════

class Referee:
    """Validates moves and arbitrates game endings.

    Parameters
    ----------
    board:
        A :pyclass:`BoardState` instance (usually the starting position).
    max_moves:
        Safety cap — declare a draw if the game reaches this many full moves.
    """

    def __init__(
        self,
        board: Optional[BoardState] = None,
        max_moves: int = 500,
    ) -> None:
        self.board = board or BoardState.starting_position()
        self.max_moves = max_moves
        self._move_log: list[MoveResult] = []

    # ── Core: validate & apply a move ────────────────────────────────────
    def apply_move(self, uci_move: str) -> MoveResult:
        """Try to apply *uci_move* to the current board.

        * If **legal**, the board state is updated and a ``MoveResult``
          with ``LEGAL`` validity is returned.
        * If **illegal**, the board is untouched and a ``MoveResult``
          with ``ILLEGAL`` validity and a descriptive reason is returned.
        """
        # -- Parse the UCI string -------------------------------------------
        try:
            move = chess.Move.from_uci(uci_move)
        except (chess.InvalidMoveError, ValueError):
            return self._illegal(uci_move, "Malformed UCI string.")

        # -- Legality check (the ONLY authority) ----------------------------
        if move not in self.board.inner.legal_moves:
            reason = self._diagnose_illegality(move)
            return self._illegal(uci_move, reason)

        # -- Apply ----------------------------------------------------------
        san = self.board.inner.san(move)
        self.board.push_uci(uci_move)
        status = self._evaluate_status()

        result = MoveResult(
            validity=MoveValidity.LEGAL,
            reason="OK",
            fen=self.board.fen,
            game_status=status,
            move_number=self.board.fullmove_number,
            active_color=self.board.active_color_name,
            move_uci=uci_move,
            san=san,
        )
        self._move_log.append(result)
        return result

    def validate_move(self, move_or_board: Any, maybe_move: Optional[str] = None) -> Any:
        """Convenience method to check move validity without throwing."""
        if maybe_move is not None:
            uci_move = maybe_move
            board = move_or_board
            try:
                m = chess.Move.from_uci(uci_move)
                b = board.inner if hasattr(board, "inner") else board
                return type("ValidationResult", (), {"is_valid": m in b.legal_moves})()
            except Exception:
                return type("ValidationResult", (), {"is_valid": False})()
        else:
            res = self.apply_move(move_or_board)
            return type("ValidationResult", (), {"is_valid": res.validity == MoveValidity.LEGAL, "result": res})()

    # ── Query helpers ────────────────────────────────────────────────────
    def current_status(self) -> GameStatus:
        """Evaluate the game status for the **current** position."""
        return self._evaluate_status()

    @property
    def move_log(self) -> list[MoveResult]:
        return list(self._move_log)

    @property
    def legal_moves(self) -> list[str]:
        return self.board.legal_moves_uci()

    @property
    def fen(self) -> str:
        return self.board.fen

    # ── Internal ─────────────────────────────────────────────────────────
    def _evaluate_status(self) -> GameStatus:
        """Check the board for all end conditions."""
        b = self.board

        if b.is_checkmate:
            return GameStatus.CHECKMATE
        if b.is_stalemate:
            return GameStatus.STALEMATE
        if b.is_fifty_moves:
            return GameStatus.DRAW_FIFTY_MOVE
        if b.is_threefold_repetition:
            return GameStatus.DRAW_THREEFOLD
        if b.is_insufficient_material:
            return GameStatus.DRAW_INSUFFICIENT
        if b.fullmove_number >= self.max_moves:
            return GameStatus.DRAW_FIFTY_MOVE  # safety cap
        if b.is_check:
            return GameStatus.CHECK
        return GameStatus.ONGOING

    def _illegal(self, uci: str, reason: str) -> MoveResult:
        return MoveResult(
            validity=MoveValidity.ILLEGAL,
            reason=reason,
            fen=self.board.fen,
            game_status=self._evaluate_status(),
            move_number=self.board.fullmove_number,
            active_color=self.board.active_color_name,
            move_uci=uci,
        )

    def _diagnose_illegality(self, move: chess.Move) -> str:
        """Attempt to give a meaningful reason for an illegal move."""
        board = self.board.inner
        piece = board.piece_at(move.from_square)

        if piece is None:
            sq = chess.square_name(move.from_square)
            return f"No piece on {sq}."

        if piece.color != board.turn:
            return "That piece belongs to the opponent."

        # Check if move would leave king in check
        test = board.copy()
        test.push(move)
        if test.was_into_check():
            return "Move leaves the king in check."

        # Castling specifics
        if piece.piece_type == chess.KING and chess.square_distance(
            move.from_square, move.to_square
        ) > 1:
            if board.is_check():
                return "Cannot castle out of check."
            # Check squares the king passes through
            between_bb = chess.between(move.from_square, move.to_square)
            for sq in chess.SquareSet(between_bb):
                if board.is_attacked_by(not board.turn, sq):
                    return "Cannot castle through check."
            return "Castling is not legal here (rights lost or path blocked)."

        return "Move violates piece movement rules."

    def __repr__(self) -> str:
        return f"Referee(fen={self.board.fen!r})"
