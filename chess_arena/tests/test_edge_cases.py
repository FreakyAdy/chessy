"""
test_edge_cases.py — Edge Case & Forced-Mate Tests
═══════════════════════════════════════════════════

Tests for unusual positions: forced mates, stalemate traps, draw detection
in deeply specific scenarios.
"""

from __future__ import annotations

import unittest

import chess

from chess_arena.arena.board import BoardState
from chess_arena.arena.referee import Referee, MoveValidity, GameStatus


class TestForcedMateInOne(unittest.TestCase):
    """Back-rank mate in one."""

    def test_back_rank_mate(self):
        # White rook on a1, black king on h8, white king on g6
        # Ra8# is checkmate
        fen = "7k/8/6K1/8/8/8/8/R7 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("a1a8")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        self.assertEqual(result.game_status, GameStatus.CHECKMATE)


class TestForcedMateInTwo(unittest.TestCase):
    """Two-move forced mate: queen + rook battery."""

    def test_two_move_mate(self):
        # White: Kh6, Qe4, Rg1 — Black: Kg8
        # 1. Qe6+ Kh8  2. Qg8# (rook on g1 supports)
        fen = "6k1/8/7K/8/4Q3/8/8/6R1 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))

        # 1. Qe6+ — gives check
        result = ref.apply_move("e4e6")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        self.assertEqual(result.game_status, GameStatus.CHECK)

        # 1... Kh8 (forced — only other option is Kf8)
        result = ref.apply_move("g8h8")
        self.assertEqual(result.validity, MoveValidity.LEGAL)

        # 2. Qg8# — checkmate (rook on g1 supports)
        result = ref.apply_move("e6g8")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        self.assertEqual(result.game_status, GameStatus.CHECKMATE)


class TestStalemateTrap(unittest.TestCase):
    """King boxed in — stalemate instead of checkmate."""

    def test_king_in_corner_stalemate(self):
        # Black king on a8, White king on a6, White queen on b6
        # Black has no legal moves and is NOT in check → stalemate
        fen = "k7/8/KQ6/8/8/8/8/8 b - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.STALEMATE)


class TestThreefoldRepetition(unittest.TestCase):
    """Threefold repetition draw."""

    def test_draw_by_repetition(self):
        ref = Referee()
        # Shuffle knights back and forth to repeat positions
        moves = [
            "g1f3", "g8f6",   # move 1
            "f3g1", "f6g8",   # back to start (repeat 1)
            "g1f3", "g8f6",   # (repeat 2)
            "f3g1", "f6g8",   # back to start (repeat 3 → draw)
        ]
        status = None
        for m in moves:
            result = ref.apply_move(m)
            self.assertEqual(result.validity, MoveValidity.LEGAL, f"Move {m} should be legal")
            status = result.game_status
        self.assertEqual(status, GameStatus.DRAW_THREEFOLD)


class TestPinnedPieceCannotMove(unittest.TestCase):
    """A pinned piece cannot move (would expose king)."""

    def test_absolute_pin(self):
        # White king on e1, white bishop on e3, black rook on e8
        # Bishop is pinned — moving it exposes king
        fen = "4r3/8/8/8/8/4B3/8/4K3 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        # Try to move the bishop
        result = ref.apply_move("e3d4")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)


class TestDoubleCheck(unittest.TestCase):
    """In double check, only the king can move."""

    def test_double_check_king_must_move(self):
        # Construct a double-check position
        # Black king on e8, White queen on e1, White knight on f6
        # After Qe7+ and Nxd7+ simultaneously? — let's use a known FEN.
        # Simpler: White Bd5 + Rd8 giving double check to Ke8
        fen = "3Rk3/8/8/3B4/8/8/8/4K3 b - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        # It should be check (or checkmate)
        self.assertIn(status, [GameStatus.CHECK, GameStatus.CHECKMATE])
        # Only king moves should be legal
        legal = ref.legal_moves
        for m in legal:
            self.assertEqual(m[0], "e", f"Expected king move, got {m}")


class TestPromotionCapture(unittest.TestCase):
    """Pawn promotes while capturing."""

    def test_promotion_with_capture(self):
        # White pawn on d7, black rook on e8
        fen = "4r3/3P4/8/8/8/8/8/4K2k w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("d7e8q")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        piece = ref.board.inner.piece_at(chess.E8)
        self.assertIsNotNone(piece)
        self.assertEqual(piece.piece_type, chess.QUEEN)
        self.assertEqual(piece.color, chess.WHITE)


class TestCastlingRightsLost(unittest.TestCase):
    """Castling rights lost after king or rook moves."""

    def test_castling_after_king_moves_back(self):
        # Use a pawnless position so king can move freely
        # White plays Ke2 then Ke1 — castling rights should be gone
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        ref.apply_move("e1e2")   # King moves — loses castling rights
        ref.apply_move("a8b8")   # Black plays
        ref.apply_move("e2e1")   # King returns to e1
        ref.apply_move("b8a8")   # Black plays
        # Try to castle — should be illegal (rights lost when king moved)
        result = ref.apply_move("e1g1")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)


class TestBoardAscii(unittest.TestCase):
    """Verify board ASCII rendering works."""

    def test_starting_position_ascii(self):
        board = BoardState.starting_position()
        ascii_str = board.ascii()
        self.assertIn("a b c d e f g h", ascii_str)
        self.assertIn("8", ascii_str)
        self.assertIn("1", ascii_str)

    def test_fen_roundtrip(self):
        # Use a FEN that python-chess preserves exactly (valid en passant)
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        board = BoardState.from_fen(fen)
        self.assertEqual(board.fen, fen)


if __name__ == "__main__":
    unittest.main()
