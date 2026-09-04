"""
test_validator.py — Tests for ModelAuditor & Verification Gate
═════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

from chess_arena.arena.validator import ModelAuditor


class TestModelAuditor(unittest.TestCase):
    def setUp(self):
        self.auditor = ModelAuditor(time_limit=2.0)

    def test_audit_valid_greedy_agent(self):
        """GreedyAgent should pass compliance checks and be eligible."""
        report = self.auditor.audit("chess_arena.agents.greedy_agent:GreedyAgent")
        self.assertTrue(report.is_eligible, f"GreedyAgent should be eligible, got: {report.summary}")
        self.assertGreaterEqual(report.score, 80)
        self.assertEqual(len(report.critical_issues), 0)
        self.assertGreater(report.total_positions_tested, 0)

    def test_audit_template_agent_file(self):
        """uploaded_agents/template_agent.py should pass compliance checks."""
        template_path = "uploaded_agents/template_agent.py"
        if not os.path.exists(template_path):
            self.skipTest(f"{template_path} does not exist")

        report = self.auditor.audit(template_path)
        self.assertTrue(report.is_eligible, f"Template agent should be eligible, got: {report.summary}")
        self.assertGreaterEqual(report.score, 85)
        self.assertEqual(len(report.critical_issues), 0)

    def test_audit_illegal_move_agent(self):
        """An agent returning an illegal move must be disqualified."""
        code = """
from chess_arena.arena.adapter import ChessAgent

class IllegalBot(ChessAgent):
    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        return "e2e5"  # Illegal pawn move (cannot jump 3 squares)
"""
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name

        try:
            report = self.auditor.audit(temp_path)
            self.assertFalse(report.is_eligible, "IllegalBot must NOT be eligible")
            self.assertIn("DISQUALIFIED", report.summary)
            self.assertGreater(len(report.critical_issues), 0)
            self.assertTrue(any("illegal move" in issue.lower() for issue in report.critical_issues))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_audit_crashing_agent(self):
        """An agent that crashes or throws uncaught exceptions must be disqualified."""
        code = """
from chess_arena.arena.adapter import ChessAgent

class CrashBot(ChessAgent):
    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        raise ValueError("Simulated agent engine crash!")
"""
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name

        try:
            report = self.auditor.audit(temp_path)
            self.assertFalse(report.is_eligible, "CrashBot must NOT be eligible")
            self.assertIn("DISQUALIFIED", report.summary)
            self.assertGreater(len(report.critical_issues), 0)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
