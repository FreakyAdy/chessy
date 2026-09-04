"""
test_web.py — Tests for FastAPI Endpoints, Bot Upload Gate & WebSocket Streaming
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import unittest
from fastapi.testclient import TestClient

from chess_arena.web.app import app


class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root_serves_html(self):
        """GET / should serve index.html with 200 OK."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Chess Arena", response.text)
        self.assertIn("chessboard", response.text)

    def test_list_bots(self):
        """GET /api/bots should list available bots."""
        response = self.client.get("/api/bots")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("bots", data)
        bot_names = [b["name"] for b in data["bots"]]
        self.assertIn("GreedyBot", bot_names)
        self.assertIn("Minimax-d2", bot_names)

    def test_audit_endpoint(self):
        """POST /api/audit should audit an agent and return eligibility score."""
        payload = {"source": "chess_arena.agents.greedy_agent:GreedyAgent"}
        response = self.client.post("/api/audit", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_eligible"])
        self.assertGreaterEqual(data["score"], 80)
        self.assertEqual(len(data["critical_issues"]), 0)

    def test_upload_invalid_file_extension(self):
        """POST /api/upload should reject non-.py files."""
        fake_file = io.BytesIO(b"not code")
        response = self.client.post(
            "/api/upload",
            files={"file": ("malicious.exe", fake_file, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only .py", response.json()["detail"])

    def test_upload_valid_bot(self):
        """POST /api/upload should audit and accept a valid Python agent."""
        code = b"""
from chess_arena.arena.adapter import ChessAgent

class ValidWebBot(ChessAgent):
    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        return legal_moves[0]
"""
        fake_file = io.BytesIO(code)
        response = self.client.post(
            "/api/upload",
            files={"file": ("web_test_bot.py", fake_file, "text/x-python")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_eligible"])
        self.assertGreaterEqual(data["score"], 85)
        self.assertEqual(data["class_name"], "ValidWebBot")

        # Cleanup test uploaded file
        uploaded_path = os.path.join("uploaded_agents", "web_test_bot.py")
        if os.path.exists(uploaded_path):
            os.remove(uploaded_path)

    def test_tournament_validation_min_bots(self):
        """POST /api/tournament/start should reject fewer than 2 bots."""
        payload = {
            "bot_ids": ["greedy"],
            "format": "round_robin",
            "games_per_pair": 2,
            "time_limit": 5.0,
            "move_delay": 0.25,
        }
        response = self.client.post("/api/tournament/start", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("At least 2 bots", response.json()["detail"])

    def test_tournament_validation_max_bots(self):
        """POST /api/tournament/start should reject more than 5 bots."""
        payload = {
            "bot_ids": ["greedy", "minimax_d2", "center_control", "random", "bot5", "bot6"],
            "format": "round_robin",
            "games_per_pair": 2,
            "time_limit": 5.0,
            "move_delay": 0.25,
        }
        response = self.client.post("/api/tournament/start", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Maximum of 5 bots", response.json()["detail"])

    def test_websocket_live_connection(self):
        """WebSocket /ws/live should connect and send initial state snapshot."""
        with self.client.websocket_connect("/ws/live") as websocket:
            data = websocket.receive_json()
            self.assertEqual(data["type"], "state_snapshot")
            self.assertIn("fen", data["data"])
            self.assertIn("standings", data["data"])

    def test_delete_bot_lifecycle(self):
        # Create a dummy bot in uploaded_agents
        dummy_path = Path("uploaded_agents/test_unit_del.py")
        dummy_path.write_text("# dummy test bot", encoding="utf-8")
        self.assertTrue(dummy_path.exists())

        # Test deleting custom bot
        resp = self.client.delete("/api/bots/uploaded_test_unit_del")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))
        self.assertFalse(dummy_path.exists())

        # Test deleting non-existent bot
        resp_404 = self.client.delete("/api/bots/non_existent_bot_123")
        self.assertEqual(resp_404.status_code, 404)

    def test_delete_builtin_bot_forbidden(self):
        # Should forbid deleting built-in agents
        resp = self.client.delete("/api/bots/greedy")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()

