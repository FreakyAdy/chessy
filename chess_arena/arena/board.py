"""
board.py — Board State Management & FEN Utilities
═══════════════════════════════════════════════════

Wraps `python-chess` to provide a clean, immutable-style board interface.
The board is the **ground truth** for every game — agents never touch it
directly; all mutations go through the Referee.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

import chess


# ── Pretty piece symbols for ASCII rendering ─────────────────────────────────
_UNICODE_PIECES = {
    "R": "♜", "N": "♞", "B": "♝", "Q": "♛", "K": "♚", "P": "♟",
    "r": "♖", "n": "♘", "b": "♗", "q": "♕", "k": "♔", "p": "♙",
}


@dataclass
class BoardState:
    """High-level wrapper around :pyclass:`chess.Board`.

    * Exposes helpers the rest of the arena needs (FEN, legal-move list,
      ASCII art, position hashing, draw detection).
    * Keeps a **position history** for threefold-repetition detection that
      survives push / pop cycles.
    """

    _board: chess.Board = field(default_factory=chess.Board)
    _position_history: list[int] = field(default_factory=list)

    # ── Construction helpers ─────────────────────────────────────────────
    @classmethod
    def from_fen(cls, fen: str) -> "BoardState":
        """Create a ``BoardState`` from an arbitrary FEN string."""
        board = chess.Board(fen)
        state = cls(_board=board)
        state._position_history.append(board.board_fen().__hash__())
        return state

    @classmethod
    def starting_position(cls) -> "BoardState":
        """Standard opening position."""
        return cls.from_fen(chess.STARTING_FEN)

    # ── FEN ──────────────────────────────────────────────────────────────
    @property
    def fen(self) -> str:
        return self._board.fen()

    # ── Turn info ────────────────────────────────────────────────────────
    @property
    def active_color(self) -> chess.Color:
        return self._board.turn

    @property
    def active_color_name(self) -> str:
        return "White" if self._board.turn == chess.WHITE else "Black"

    @property
    def fullmove_number(self) -> int:
        return self._board.fullmove_number

    @property
    def halfmove_clock(self) -> int:
        return self._board.halfmove_clock

    # ── Legal moves ──────────────────────────────────────────────────────
    def legal_moves_uci(self) -> list[str]:
        """Return every legal move as a UCI string (e.g. ``'e2e4'``)."""
        return [m.uci() for m in self._board.legal_moves]

    def is_legal(self, uci_move: str) -> bool:
        """Check whether *uci_move* is legal **without** pushing it."""
        try:
            move = chess.Move.from_uci(uci_move)
        except (chess.InvalidMoveError, ValueError):
            return False
        return move in self._board.legal_moves

    # ── Mutators ─────────────────────────────────────────────────────────
    def push_uci(self, uci_move: str) -> chess.Move:
        """Push a UCI move string.  Returns the ``chess.Move`` object.

        Raises ``ValueError`` if the move is not legal.
        """
        move = chess.Move.from_uci(uci_move)
        if move not in self._board.legal_moves:
            raise ValueError(f"Illegal move: {uci_move}")
        self._board.push(move)
        self._position_history.append(self._board.board_fen().__hash__())
        return move

    def copy(self) -> "BoardState":
        """Deep copy (safe for speculative / analysis use)."""
        new = BoardState(
            _board=self._board.copy(),
            _position_history=list(self._position_history),
        )
        return new

    # ── Status queries ───────────────────────────────────────────────────
    @property
    def is_check(self) -> bool:
        return self._board.is_check()

    @property
    def is_checkmate(self) -> bool:
        return self._board.is_checkmate()

    @property
    def is_stalemate(self) -> bool:
        return self._board.is_stalemate()

    @property
    def is_insufficient_material(self) -> bool:
        return self._board.is_insufficient_material()

    @property
    def is_fifty_moves(self) -> bool:
        return self._board.is_fifty_moves()

    @property
    def is_threefold_repetition(self) -> bool:
        return self._board.is_repetition(3)

    @property
    def is_game_over(self) -> bool:
        return self._board.is_game_over(claim_draw=True)

    @property
    def result_string(self) -> Optional[str]:
        """``'1-0'``, ``'0-1'``, ``'1/2-1/2'``, or ``None``."""
        if not self.is_game_over:
            return None
        return self._board.result(claim_draw=True)

    # ── Board visualisation ──────────────────────────────────────────────
    def ascii(self, use_unicode: bool = True) -> str:
        """Return a nicely formatted ASCII/Unicode board string.

        Includes file labels (a–h) and rank numbers (1–8).
        """
        lines: list[str] = []
        board_str = str(self._board)
        rows = board_str.split("\n")
        for rank_idx, row in enumerate(rows):
            rank_label = str(8 - rank_idx)
            if use_unicode:
                pretty = ""
                for ch in row:
                    if ch in _UNICODE_PIECES:
                        pretty += _UNICODE_PIECES[ch]
                    else:
                        pretty += ch
                lines.append(f"  {rank_label} │ {pretty}")
            else:
                lines.append(f"  {rank_label} │ {row}")
        lines.append("    ╰───────────────────")
        lines.append("      a b c d e f g h")
        return "\n".join(lines)

    # ── Internals exposed for referee ────────────────────────────────────
    @property
    def inner(self) -> chess.Board:
        """Direct access to the underlying ``chess.Board`` — use sparingly."""
        return self._board

    def __repr__(self) -> str:
        return f"BoardState(fen='{self.fen}')"
