"""
tournament_bridge.py — Asynchronous Tournament Coordinator & WebSocket Broadcaster
═════════════════════════════════════════════════════════════════════════════════

Bridges the chess engine, referee, and subprocess agent runners with an async
event stream consumed by WebSockets in real time.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

import chess
import chess.pgn

from chess_arena.arena.adapter import AgentProcess, ChessAgent, InProcessAgent
from chess_arena.arena.referee import GameStatus, MoveResult, Referee
from chess_arena.arena.validator import ModelAuditor, load_agent_class

logger = logging.getLogger("chess_arena.web.bridge")


@dataclass
class StandingRecord:
    name: str
    points: float = 0.0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    games_played: int = 0


class TournamentBridge:
    """Coordinates tournament execution and streams live state over WebSockets."""

    def __init__(self) -> None:
        self.active_task: Optional[asyncio.Task] = None
        self.is_running: bool = False
        self.is_paused: bool = False
        self.pause_event: asyncio.Event = asyncio.Event()
        self.pause_event.set()  # Not paused initially
        self.move_delay: float = 0.25  # seconds between moves
        self.time_limit: float = 5.0
        self.tournament_format: str = "round_robin"
        self.games_per_pair: int = 2

        # Active state
        self.current_match_index: int = 0
        self.total_matches: int = 0
        self.current_fen: str = chess.STARTING_FEN
        self.current_white: str = ""
        self.current_black: str = ""
        self.current_move_uci: str = ""
        self.current_move_san: str = ""
        self.move_history: List[Dict[str, Any]] = []
        self.standings: Dict[str, StandingRecord] = {}
        self.match_results: List[Dict[str, Any]] = []
        self.pgn_records: Dict[int, str] = {}

        # Connected WebSocket listeners
        self.listeners: Set[asyncio.Queue] = set()

    def register_listener(self) -> asyncio.Queue:
        """Register a new WebSocket client queue."""
        q: asyncio.Queue = asyncio.Queue()
        self.listeners.add(q)
        return q

    def unregister_listener(self, q: asyncio.Queue) -> None:
        """Remove a disconnected WebSocket client queue."""
        self.listeners.discard(q)

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast an event payload to all connected WebSocket clients."""
        payload = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        }
        dead = []
        for q in self.listeners:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            self.listeners.discard(q)

    def get_state_snapshot(self) -> Dict[str, Any]:
        """Return full state snapshot for newly connected clients."""
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "move_delay": self.move_delay,
            "current_match": self.current_match_index,
            "total_matches": self.total_matches,
            "white": self.current_white,
            "black": self.current_black,
            "fen": self.current_fen,
            "last_move_uci": self.current_move_uci,
            "last_move_san": self.current_move_san,
            "move_history": self.move_history[-30:],
            "standings": [
                {
                    "name": r.name,
                    "points": r.points,
                    "wins": r.wins,
                    "draws": r.draws,
                    "losses": r.losses,
                    "games_played": r.games_played,
                }
                for r in sorted(self.standings.values(), key=lambda s: s.points, reverse=True)
            ],
            "recent_results": self.match_results[-5:],
        }

    def set_speed(self, delay: float) -> None:
        """Update move delay speed in real-time."""
        self.move_delay = max(0.02, min(3.0, delay))

    def pause(self) -> None:
        """Pause tournament execution."""
        self.is_paused = True
        self.pause_event.clear()

    def resume(self) -> None:
        """Resume tournament execution."""
        self.is_paused = False
        self.pause_event.set()

    async def stop(self) -> None:
        """Halt the running tournament immediately."""
        self.is_running = False
        self.is_paused = False
        self.pause_event.set()
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
            try:
                await self.active_task
            except asyncio.CancelledError:
                pass
        self.active_task = None
        await self.broadcast("tournament_stopped", {"message": "Tournament stopped by user."})

    def start_tournament(
        self,
        bot_configs: List[Dict[str, Any]],
        tournament_format: str = "round_robin",
        games_per_pair: int = 2,
        time_limit: float = 5.0,
    ) -> bool:
        """Launch the tournament runner in a background asyncio task."""
        if self.is_running:
            return False

        self.tournament_format = tournament_format
        self.games_per_pair = games_per_pair
        self.time_limit = time_limit
        self.is_running = True
        self.is_paused = False
        self.pause_event.set()

        # Initialize standings
        self.standings = {b["name"]: StandingRecord(name=b["name"]) for b in bot_configs}
        self.match_results = []
        self.pgn_records = {}
        self.move_history = []
        self.current_fen = chess.STARTING_FEN

        loop = asyncio.get_event_loop()
        self.active_task = loop.create_task(self._run_tournament_loop(bot_configs))
        return True

    async def _run_tournament_loop(self, bot_configs: List[Dict[str, Any]]) -> None:
        """Execute all tournament games in order with real-time broadcasts."""
        try:
            # Build match pairings
            pairings = self._generate_pairings(bot_configs)
            self.total_matches = len(pairings)
            self.current_match_index = 0

            await self.broadcast("tournament_start", {
                "total_matches": self.total_matches,
                "format": self.tournament_format,
                "bots": [b["name"] for b in bot_configs],
            })

            for match_idx, (p1_cfg, p2_cfg) in enumerate(pairings, 1):
                if not self.is_running:
                    break

                self.current_match_index = match_idx
                self.current_white = p1_cfg["name"]
                self.current_black = p2_cfg["name"]
                self.move_history = []
                self.current_fen = chess.STARTING_FEN

                await self._play_single_game(match_idx, p1_cfg, p2_cfg)
                # Short break between matches
                await asyncio.sleep(1.0)

            # Finalize tournament
            ranked = sorted(self.standings.values(), key=lambda s: s.points, reverse=True)
            await self.broadcast("tournament_end", {
                "champion": ranked[0].name if ranked else "None",
                "final_standings": [
                    {
                        "rank": i,
                        "name": r.name,
                        "points": r.points,
                        "wins": r.wins,
                        "draws": r.draws,
                        "losses": r.losses,
                        "games_played": r.games_played,
                    }
                    for i, r in enumerate(ranked, 1)
                ],
            })

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Error in tournament loop: %s", exc)
            await self.broadcast("tournament_error", {"error": str(exc)})
        finally:
            self.is_running = False
            self.is_paused = False

    def _generate_pairings(
        self, bot_configs: List[Dict[str, Any]]
    ) -> List[tuple[Dict[str, Any], Dict[str, Any]]]:
        """Generate list of (white_config, black_config) matches."""
        pairings = []
        n = len(bot_configs)
        for i in range(n):
            for j in range(i + 1, n):
                for g in range(self.games_per_pair):
                    if g % 2 == 0:
                        pairings.append((bot_configs[i], bot_configs[j]))
                    else:
                        pairings.append((bot_configs[j], bot_configs[i]))
        return pairings

    def _spawn_agent(self, cfg: Dict[str, Any]):
        """Spawn agent either in subprocess or in-process."""
        module_path = cfg["module"]
        class_name = cfg["class"]
        name = cfg["name"]
        agent_config = cfg.get("config", {})

        # Try subprocess isolation
        try:
            return AgentProcess.spawn(module_path, class_name, name, agent_config)
        except Exception:
            # Fallback in-process
            target_class, _, _ = load_agent_class(module_path, class_name)
            instance = target_class(name=name, config=agent_config)
            return InProcessAgent(instance)

    async def _play_single_game(
        self,
        match_idx: int,
        white_cfg: Dict[str, Any],
        black_cfg: Dict[str, Any],
    ) -> None:
        """Run a single match and broadcast moves to WebSockets."""
        white_agent = None
        black_agent = None

        try:
            # Spawn agents
            loop = asyncio.get_running_loop()
            white_agent = await loop.run_in_executor(None, self._spawn_agent, white_cfg)
            black_agent = await loop.run_in_executor(None, self._spawn_agent, black_cfg)

            board = chess.Board()
            referee = Referee()
            game_pgn = chess.pgn.Game()
            game_pgn.headers["Event"] = "Chess Arena Live Tournament"
            game_pgn.headers["Site"] = "Chess Arena Web UI"
            game_pgn.headers["White"] = white_cfg["name"]
            game_pgn.headers["Black"] = black_cfg["name"]
            game_pgn.headers["Round"] = str(match_idx)
            pgn_node = game_pgn

            await self.broadcast("match_start", {
                "match_number": match_idx,
                "total_matches": self.total_matches,
                "white": white_cfg["name"],
                "black": black_cfg["name"],
                "fen": board.fen(),
            })

            move_count = 0
            max_moves = 300
            outcome_str = ""
            termination_reason = ""

            while not board.is_game_over() and move_count < max_moves and self.is_running:
                # Handle pause
                await self.pause_event.wait()

                active_color = "white" if board.turn == chess.WHITE else "black"
                active_agent = white_agent if board.turn == chess.WHITE else black_agent
                legal_moves_uci = [m.uci() for m in board.legal_moves]

                # Request move from agent with timing
                t_start = time.perf_counter()
                try:
                    if hasattr(active_agent, "request_move"):
                        move_uci = await loop.run_in_executor(
                            None,
                            active_agent.request_move,
                            board.fen(),
                            legal_moves_uci,
                            self.time_limit,
                        )
                    else:
                        move_uci = await loop.run_in_executor(
                            None,
                            active_agent.get_move,
                            board.fen(),
                            legal_moves_uci,
                        )
                except TimeoutError as exc:
                    outcome_str = "0-1" if board.turn == chess.WHITE else "1-0"
                    termination_reason = f"{active_agent.name} timed out ({self.time_limit:.1f}s)"
                    break
                except Exception as exc:
                    outcome_str = "0-1" if board.turn == chess.WHITE else "1-0"
                    termination_reason = f"{active_agent.name} crashed: {exc}"
                    break

                elapsed = time.perf_counter() - t_start

                # Validate move
                try:
                    chess_move = chess.Move.from_uci(move_uci)
                    if chess_move not in board.legal_moves:
                        outcome_str = "0-1" if board.turn == chess.WHITE else "1-0"
                        termination_reason = f"{active_agent.name} played illegal move '{move_uci}'"
                        break
                except Exception as exc:
                    outcome_str = "0-1" if board.turn == chess.WHITE else "1-0"
                    termination_reason = f"{active_agent.name} played invalid move '{move_uci}': {exc}"
                    break

                san_move = board.san(chess_move)

                # Push move
                board.push(chess_move)
                pgn_node = pgn_node.add_variation(chess_move)
                move_count += 1

                self.current_fen = board.fen()
                self.current_move_uci = move_uci
                self.current_move_san = san_move

                from_sq = chess.square_name(chess_move.from_square)
                to_sq = chess.square_name(chess_move.to_square)

                move_entry = {
                    "move_number": board.fullmove_number,
                    "turn": active_color,
                    "uci": move_uci,
                    "san": san_move,
                    "from": from_sq,
                    "to": to_sq,
                    "elapsed_s": round(elapsed, 4),
                }
                self.move_history.append(move_entry)

                # Material count
                white_captured = self._get_captured_pieces(board, chess.WHITE)
                black_captured = self._get_captured_pieces(board, chess.BLACK)

                # Broadcast move event
                await self.broadcast("move", {
                    "match_number": match_idx,
                    "move_number": board.fullmove_number,
                    "turn": active_color,
                    "next_turn": "white" if board.turn == chess.WHITE else "black",
                    "uci": move_uci,
                    "san": san_move,
                    "from": from_sq,
                    "to": to_sq,
                    "fen": self.current_fen,
                    "elapsed_s": round(elapsed, 4),
                    "time_limit": self.time_limit,
                    "legal_moves_count": len(list(board.legal_moves)),
                    "halfmove_clock": board.halfmove_clock,
                    "is_check": board.is_check(),
                    "is_checkmate": board.is_checkmate(),
                    "white_captured": white_captured,
                    "black_captured": black_captured,
                })

                # Sleep to animate move
                await asyncio.sleep(self.move_delay)

            # Match outcome determination
            if not outcome_str:
                if board.is_checkmate():
                    if board.turn == chess.WHITE:
                        outcome_str = "0-1"
                        termination_reason = f"Checkmate! {black_cfg['name']} wins."
                    else:
                        outcome_str = "1-0"
                        termination_reason = f"Checkmate! {white_cfg['name']} wins."
                elif board.is_stalemate():
                    outcome_str = "1/2-1/2"
                    termination_reason = "Draw by Stalemate."
                elif board.is_insufficient_material():
                    outcome_str = "1/2-1/2"
                    termination_reason = "Draw by Insufficient Material."
                elif board.can_claim_threefold_repetition():
                    outcome_str = "1/2-1/2"
                    termination_reason = "Draw by Threefold Repetition."
                elif board.can_claim_fifty_moves():
                    outcome_str = "1/2-1/2"
                    termination_reason = "Draw by 50-Move Rule."
                else:
                    outcome_str = "1/2-1/2"
                    termination_reason = "Match concluded."

            # Update PGN headers and save
            game_pgn.headers["Result"] = outcome_str
            exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
            pgn_str = game_pgn.accept(exporter)
            self.pgn_records[match_idx] = pgn_str

            # Update standings
            w_rec = self.standings[white_cfg["name"]]
            b_rec = self.standings[black_cfg["name"]]
            w_rec.games_played += 1
            b_rec.games_played += 1

            if outcome_str == "1-0":
                w_rec.points += 1.0
                w_rec.wins += 1
                b_rec.losses += 1
                winner = white_cfg["name"]
            elif outcome_str == "0-1":
                b_rec.points += 1.0
                b_rec.wins += 1
                w_rec.losses += 1
                winner = black_cfg["name"]
            else:
                w_rec.points += 0.5
                b_rec.points += 0.5
                w_rec.draws += 1
                b_rec.draws += 1
                winner = "Draw"

            result_summary = {
                "match_number": match_idx,
                "white": white_cfg["name"],
                "black": black_cfg["name"],
                "outcome": outcome_str,
                "winner": winner,
                "reason": termination_reason,
                "total_moves": move_count,
            }
            self.match_results.append(result_summary)

            # Broadcast match conclusion and updated standings
            await self.broadcast("match_end", {
                "match_number": match_idx,
                "result": result_summary,
                "pgn": pgn_str,
            })

            await self.broadcast("standings", {
                "standings": [
                    {
                        "name": r.name,
                        "points": r.points,
                        "wins": r.wins,
                        "draws": r.draws,
                        "losses": r.losses,
                        "games_played": r.games_played,
                    }
                    for r in sorted(self.standings.values(), key=lambda s: s.points, reverse=True)
                ]
            })

        finally:
            # Clean up child processes cleanly
            if white_agent and hasattr(white_agent, "shutdown"):
                try:
                    white_agent.shutdown()
                except Exception:
                    pass
            if black_agent and hasattr(black_agent, "shutdown"):
                try:
                    black_agent.shutdown()
                except Exception:
                    pass

    def _get_captured_pieces(self, board: chess.Board, color: chess.Color) -> List[str]:
        """Compute list of pieces captured by this color."""
        # Initial piece count
        initial_pieces = {'p': 8, 'n': 2, 'b': 2, 'r': 2, 'q': 1}
        opp_color = not color
        remaining_pieces = {'p': 0, 'n': 0, 'b': 0, 'r': 0, 'q': 0}

        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.color == opp_color:
                symbol = piece.symbol().lower()
                if symbol in remaining_pieces:
                    remaining_pieces[symbol] += 1

        captured = []
        for symbol, count in initial_pieces.items():
            diff = count - remaining_pieces[symbol]
            for _ in range(max(0, diff)):
                captured.append(symbol.upper() if opp_color == chess.WHITE else symbol.lower())
        return captured
