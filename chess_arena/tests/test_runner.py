"""
test_runner.py — Integration Tests for the Game Runner
══════════════════════════════════════════════════════

Full game between two random agents, verifying PGN output and outcome structure.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from chess_arena.arena.adapter import InProcessAgent
from chess_arena.arena.runner import GameRunner, GameResult
from chess_arena.agents.random_agent import RandomAgent


class TestRandomVsRandomGame(unittest.TestCase):
    """Play a full game between two random agents."""

    def test_game_completes(self):
        agent_w = InProcessAgent(RandomAgent(name="White-Random", config={"seed": 42}))
        agent_b = InProcessAgent(RandomAgent(name="Black-Random", config={"seed": 99}))

        runner = GameRunner(
            white=agent_w,
            black=agent_b,
            move_time_limit=5.0,
            max_moves=300,
            display_board=False,
        )
        outcome = runner.run()

        self.assertIn(outcome.result, [GameResult.WIN_WHITE, GameResult.WIN_BLACK, GameResult.DRAW])
        self.assertGreater(outcome.total_moves, 0)
        self.assertEqual(outcome.white_name, "White-Random")
        self.assertEqual(outcome.black_name, "Black-Random")

    def test_pgn_saved(self):
        agent_w = InProcessAgent(RandomAgent(name="PGN-White", config={"seed": 42}))
        agent_b = InProcessAgent(RandomAgent(name="PGN-Black", config={"seed": 99}))

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = GameRunner(
                white=agent_w,
                black=agent_b,
                move_time_limit=5.0,
                max_moves=300,
                display_board=False,
                pgn_dir=tmpdir,
                game_id="test_game_001",
            )
            outcome = runner.run()

            self.assertIsNotNone(outcome.pgn_path)
            self.assertTrue(os.path.exists(outcome.pgn_path))

            with open(outcome.pgn_path, "r", encoding="utf-8") as f:
                pgn_content = f.read()

            self.assertIn("[White", pgn_content)
            self.assertIn("[Black", pgn_content)
            self.assertIn("[Result", pgn_content)


class TestForfeitOnIllegalMove(unittest.TestCase):
    """An agent that returns an illegal move should lose by forfeit."""

    def test_illegal_move_forfeits(self):
        from chess_arena.arena.adapter import ChessAgent

        class IllegalAgent(ChessAgent):
            def get_move(self, fen: str, legal_moves: list[str]) -> str:
                return "a1h8"  # almost certainly illegal

        agent_w = InProcessAgent(IllegalAgent(name="Cheater", config={}))
        agent_b = InProcessAgent(RandomAgent(name="Honest", config={}))

        runner = GameRunner(
            white=agent_w,
            black=agent_b,
            move_time_limit=5.0,
            max_moves=300,
            display_board=False,
        )
        outcome = runner.run()

        self.assertEqual(outcome.result, GameResult.WIN_BLACK)
        self.assertIn("FORFEIT", outcome.termination)


class TestMultipleGamesReproducible(unittest.TestCase):
    """Same seed → same game."""

    def test_deterministic_with_seed(self):
        def run_game(seed_w, seed_b):
            w = InProcessAgent(RandomAgent(name="W", config={"seed": seed_w}))
            b = InProcessAgent(RandomAgent(name="B", config={"seed": seed_b}))
            runner = GameRunner(white=w, black=b, max_moves=200, display_board=False)
            outcome = runner.run()
            return [r.move_uci for r in outcome.move_log]

        moves1 = run_game(123, 456)
        moves2 = run_game(123, 456)
        self.assertEqual(moves1, moves2)


if __name__ == "__main__":
    unittest.main()
