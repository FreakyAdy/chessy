"""
test_referee.py — Referee Correctness Test Suite
═════════════════════════════════════════════════

Covers all mandatory scenarios plus additional edge cases.
"""

from __future__ import annotations

import unittest

from chess_arena.arena.board import BoardState
from chess_arena.arena.referee import Referee, MoveValidity, GameStatus


class TestScholarsMate(unittest.TestCase):
    """Scholar's Mate — White delivers checkmate on f7."""

    def test_checkmate_detected(self):
        fen = "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.CHECKMATE)

    def test_no_legal_moves_in_checkmate(self):
        fen = "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
        ref = Referee(board=BoardState.from_fen(fen))
        self.assertEqual(len(ref.legal_moves), 0)


class TestStalemate(unittest.TestCase):
    """Stalemate position — Black has no legal moves but is not in check."""

    def test_stalemate_detected(self):
        fen = "5bnr/4p1pq/4Qpkr/7p/7P/4P3/PPPP1PP1/RNB1KBNR b KQ - 0 10"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.STALEMATE)


class TestEnPassant(unittest.TestCase):
    """En passant capture must be legal after opponent's double pawn push."""

    def test_en_passant_legal(self):
        # Play: e2e4, d7d5, e4e5, f7f5 → e5f6 should be legal
        ref = Referee()
        ref.apply_move("e2e4")
        ref.apply_move("d7d5")
        ref.apply_move("e4e5")
        ref.apply_move("f7f5")

        result = ref.apply_move("e5f6")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        # The f5 pawn should be gone (captured en passant)
        board = ref.board
        import chess
        self.assertIsNone(board.inner.piece_at(chess.F5))

    def test_en_passant_not_legal_later(self):
        """En passant right expires after one move."""
        ref = Referee()
        ref.apply_move("e2e4")
        ref.apply_move("d7d5")
        ref.apply_move("e4e5")
        ref.apply_move("f7f5")
        ref.apply_move("a2a3")     # White plays something else
        ref.apply_move("a7a6")     # Black plays something else
        # Now e5f6 is no longer legal (en passant expired)
        result = ref.apply_move("e5f6")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)


class TestCastling(unittest.TestCase):
    """Castling rules — through check, out of check, rights lost."""

    def test_castling_through_check_illegal(self):
        # White king e1, rook h1, black rook on f8 attacks f1
        # e1g1 castling would pass king through f1 which is attacked
        fen = "5r2/8/8/8/8/8/8/4K2R w K - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e1g1")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)
        self.assertIn("check", result.reason.lower())

    def test_castling_into_check_illegal(self):
        # White king e1, rook h1, black rook on g8 attacks g1
        fen = "6r1/8/8/8/8/8/8/4K2R w K - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e1g1")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)

    def test_castling_out_of_check_illegal(self):
        # White king in check, cannot castle
        fen = "4r3/8/8/8/8/8/8/4K2R w K - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e1g1")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)

    def test_kingside_castling_legal(self):
        fen = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e1g1")
        self.assertEqual(result.validity, MoveValidity.LEGAL)

    def test_queenside_castling_legal(self):
        fen = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e1c1")
        self.assertEqual(result.validity, MoveValidity.LEGAL)


class TestPawnPromotion(unittest.TestCase):
    """Pawn promotion — pawn on 7th rank promotes when reaching 8th."""

    def test_promotion_to_queen(self):
        fen = "8/4P3/8/8/8/8/8/4K2k w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e7e8q")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        # Verify the pawn became a queen
        import chess
        piece = ref.board.inner.piece_at(chess.E8)
        self.assertIsNotNone(piece)
        self.assertEqual(piece.piece_type, chess.QUEEN)
        self.assertEqual(piece.color, chess.WHITE)

    def test_promotion_to_knight(self):
        fen = "8/4P3/8/8/8/8/8/4K2k w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e7e8n")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        import chess
        piece = ref.board.inner.piece_at(chess.E8)
        self.assertEqual(piece.piece_type, chess.KNIGHT)

    def test_promotion_without_specifying_piece_illegal(self):
        """Must specify promotion piece — bare e7e8 is illegal in python-chess."""
        fen = "8/4P3/8/8/8/8/8/4K2k w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e7e8")
        # python-chess requires promotion specification
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)


class TestFiftyMoveRule(unittest.TestCase):
    """50-move rule — draw when halfmove clock reaches 100."""

    def test_fifty_move_draw(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 100 50"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.DRAW_FIFTY_MOVE)


class TestInsufficientMaterial(unittest.TestCase):
    """Draw by insufficient material — K vs K, K+B vs K, K+N vs K."""

    def test_king_vs_king(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.DRAW_INSUFFICIENT)

    def test_king_bishop_vs_king(self):
        fen = "4k3/8/8/8/8/8/8/4KB2 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.DRAW_INSUFFICIENT)

    def test_king_knight_vs_king(self):
        fen = "4k3/8/8/8/8/8/8/4KN2 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        status = ref.current_status()
        self.assertEqual(status, GameStatus.DRAW_INSUFFICIENT)


class TestCheck(unittest.TestCase):
    """Check detection."""

    def test_check_after_move(self):
        # White queen gives check from e1 to e8 line
        fen = "4k3/8/8/8/8/8/8/4QK2 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        result = ref.apply_move("e1e7")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        self.assertEqual(result.game_status, GameStatus.CHECK)


class TestIllegalMoves(unittest.TestCase):
    """Various illegal move scenarios."""

    def test_move_wrong_color(self):
        ref = Referee()  # White to move
        result = ref.apply_move("e7e5")  # Black pawn
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)

    def test_malformed_uci(self):
        ref = Referee()
        result = ref.apply_move("zzz")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)

    def test_move_off_board(self):
        ref = Referee()
        result = ref.apply_move("e2e9")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)

    def test_move_into_check(self):
        """A pinned piece cannot move — would expose king to check."""
        # White king on e1, white rook on e4 (pinned), black rook on e8
        # Moving the white rook off the e-file exposes the king
        fen = "4r3/8/8/8/4R3/8/8/4K3 w - - 0 1"
        ref = Referee(board=BoardState.from_fen(fen))
        # Try to move the rook sideways (breaks the pin)
        result = ref.apply_move("e4d4")
        self.assertEqual(result.validity, MoveValidity.ILLEGAL)


class TestMoveResultOutput(unittest.TestCase):
    """Verify the MoveResult structure."""

    def test_legal_move_result_fields(self):
        ref = Referee()
        result = ref.apply_move("e2e4")
        self.assertEqual(result.validity, MoveValidity.LEGAL)
        self.assertEqual(result.move_uci, "e2e4")
        self.assertEqual(result.san, "e4")
        # FEN should show the pawn on e4 (rank 4) and it's Black's turn
        self.assertIn("4P3", result.fen)
        self.assertEqual(result.active_color, "Black")
        self.assertEqual(result.game_status, GameStatus.ONGOING)


if __name__ == "__main__":
    unittest.main()
