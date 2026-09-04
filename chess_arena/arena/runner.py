"""
runner.py — Single-Game Runner
══════════════════════════════

Orchestrates one complete chess game between two agents:

1. Creates a fresh board & referee.
2. Alternates ``get_move`` calls between White and Black.
3. Handles timeouts and illegal moves (→ forfeit).
4. Logs moves and produces a PGN file.
5. Returns a structured :pyclass:`GameOutcome`.
"""

from __future__ import annotations

import datetime
import enum
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, Union

import chess
import chess.pgn

from rich.console import Console

from chess_arena.arena.board import BoardState
from chess_arena.arena.referee import Referee, MoveResult, MoveValidity, GameStatus
from chess_arena.arena.display import LiveGameDisplay


# ═════════════════════════════════════════════════════════════════════════════
#  Agent protocol (so we can accept either AgentProcess or InProcessAgent)
# ═════════════════════════════════════════════════════════════════════════════

class AgentLike(Protocol):
    """Minimal duck-type shared by AgentProcess and InProcessAgent."""
    name: str
    def request_move(self, fen: str, legal_moves: list[str], timeout: float) -> str: ...
    def is_alive(self) -> bool: ...


# ═════════════════════════════════════════════════════════════════════════════
#  Result Types
# ═════════════════════════════════════════════════════════════════════════════

class GameResult(enum.Enum):
    WIN_WHITE = "1-0"
    WIN_BLACK = "0-1"
    DRAW = "1/2-1/2"


@dataclass
class GameOutcome:
    """Everything you need to know about a finished game."""
    result: GameResult
    termination: str                      # e.g. "CHECKMATE", "FORFEIT (timeout)"
    white_name: str
    black_name: str
    total_moves: int
    pgn_path: Optional[str] = None
    move_log: list[MoveResult] = field(default_factory=list)

    @property
    def winner_name(self) -> Optional[str]:
        if self.result == GameResult.WIN_WHITE:
            return self.white_name
        if self.result == GameResult.WIN_BLACK:
            return self.black_name
        return None

    def summary(self) -> str:
        lines = [
            "",
            "═══ GAME OVER ═══",
            f"  Result      : {self.termination}",
            f"  Winner      : {self.winner_name or 'Draw'}",
            f"  White       : {self.white_name}",
            f"  Black       : {self.black_name}",
            f"  Total Moves : {self.total_moves}",
        ]
        if self.pgn_path:
            lines.append(f"  PGN         : {self.pgn_path}")
        lines.append("═════════════════")
        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  Game Runner
# ═════════════════════════════════════════════════════════════════════════════

class GameRunner:
    """Run a single game between two agents.

    Parameters
    ----------
    white, black:
        Objects satisfying :pyclass:`AgentLike` (AgentProcess or InProcessAgent).
    move_time_limit:
        Seconds each agent has per move.
    max_moves:
        Safety cap (full moves) before declaring a draw.
    display_board:
        Print ASCII board to stdout after each move.
    pgn_dir:
        Directory to save PGN files (``None`` → don't save).
    game_id:
        Identifier used in the PGN filename and headers.
    """

    def __init__(
        self,
        white: AgentLike,
        black: AgentLike,
        *,
        move_time_limit: float = 5.0,
        max_moves: int = 500,
        display_board: bool = False,
        move_delay: float = 0.15,
        game_pause: float = 2.5,
        console: Optional[Console] = None,
        pgn_dir: Optional[str] = None,
        game_id: str = "game",
    ) -> None:
        self.white = white
        self.black = black
        self.move_time_limit = move_time_limit
        self.max_moves = max_moves
        self.display_board = display_board
        self.move_delay = move_delay
        self.game_pause = game_pause
        self.console = console
        self.pgn_dir = pgn_dir
        self.game_id = game_id

    # ── Main loop ────────────────────────────────────────────────────────
    def run(self, starting_fen: Optional[str] = None) -> GameOutcome:
        """Execute the game to completion and return the outcome."""

        board = (
            BoardState.from_fen(starting_fen)
            if starting_fen
            else BoardState.starting_position()
        )
        referee = Referee(board=board, max_moves=self.max_moves)

        agents = {chess.WHITE: self.white, chess.BLACK: self.black}
        san_moves: list[str] = []     # for PGN
        move_results: list[MoveResult] = []
        ply = 0

        # ── Live display setup ───────────────────────────────────────
        live_display: Optional[LiveGameDisplay] = None
        outcome: Optional[GameOutcome] = None

        try:
            if self.display_board:
                live_display = LiveGameDisplay(
                    white_name=self.white.name,
                    black_name=self.black.name,
                    game_id=self.game_id,
                    move_delay=self.move_delay,
                    console=self.console,
                )
                live_display.start()
                live_display.update(board, None, 0, san_moves)

            while True:
                active_color = board.active_color
                agent = agents[active_color]
                color_name = "White" if active_color == chess.WHITE else "Black"

                legal = referee.legal_moves
                if not legal:
                    # No legal moves → checkmate or stalemate
                    status = referee.current_status()
                    if status == GameStatus.CHECKMATE:
                        loser_color = board.active_color
                        winner = GameResult.WIN_BLACK if loser_color == chess.WHITE else GameResult.WIN_WHITE
                        outcome = self._finish(
                            winner, "CHECKMATE", san_moves, move_results, ply, starting_fen
                        )
                    else:
                        outcome = self._finish(
                            GameResult.DRAW, status.value, san_moves, move_results, ply, starting_fen
                        )
                    return outcome

                # -- Request a move from the agent --------------------------------
                try:
                    uci_move = agent.request_move(
                        referee.fen, legal, timeout=self.move_time_limit
                    )
                except TimeoutError:
                    outcome = self._forfeit(
                        color_name, agent.name, "timeout",
                        san_moves, move_results, ply,
                    )
                    return outcome
                except Exception as exc:
                    outcome = self._forfeit(
                        color_name, agent.name, f"crash: {exc}",
                        san_moves, move_results, ply,
                    )
                    return outcome

                # -- Validate via the referee -------------------------------------
                result = referee.apply_move(uci_move)

                if result.validity == MoveValidity.ILLEGAL:
                    outcome = self._forfeit(
                        color_name, agent.name,
                        f"illegal move {uci_move} ({result.reason})",
                        san_moves, move_results, ply,
                    )
                    return outcome

                ply += 1
                san_moves.append(result.san or uci_move)
                move_results.append(result)

                # -- Display (live in-place update) ----------------------------
                if live_display is not None:
                    live_display.update(board, result, ply, san_moves)

                # -- Check for game end -------------------------------------------
                status = result.game_status
                if status == GameStatus.CHECKMATE:
                    winner = GameResult.WIN_WHITE if active_color == chess.WHITE else GameResult.WIN_BLACK
                    outcome = self._finish(
                        winner, "CHECKMATE", san_moves, move_results, ply, starting_fen,
                    )
                    return outcome
                if status in (
                    GameStatus.STALEMATE,
                    GameStatus.DRAW_FIFTY_MOVE,
                    GameStatus.DRAW_THREEFOLD,
                    GameStatus.DRAW_INSUFFICIENT,
                ):
                    outcome = self._finish(
                        GameResult.DRAW, status.value, san_moves, move_results, ply, starting_fen,
                    )
                    return outcome

            # Fallback if loop exits
            status = referee.current_status()
            if status == GameStatus.CHECKMATE:
                loser_color = board.active_color
                winner = GameResult.WIN_BLACK if loser_color == chess.WHITE else GameResult.WIN_WHITE
                outcome = self._finish(winner, "CHECKMATE", san_moves, move_results, ply, starting_fen)
            else:
                outcome = self._finish(GameResult.DRAW, status.value, san_moves, move_results, ply, starting_fen)
            return outcome

        finally:
            if live_display is not None:
                if outcome is not None:
                    live_display.show_result(
                        board,
                        outcome.termination,
                        outcome.winner_name,
                        ply,
                        san_moves,
                        pause_seconds=self.game_pause,
                    )
                else:
                    live_display.stop()

    # ── Internal helpers ─────────────────────────────────────────────────
    def _forfeit(
        self,
        color_name: str,
        agent_name: str,
        reason: str,
        san_moves: list[str],
        move_results: list[MoveResult],
        ply: int,
    ) -> GameOutcome:
        """Handle an agent forfeit (illegal move / timeout / crash)."""
        if color_name == "White":
            result = GameResult.WIN_BLACK
        else:
            result = GameResult.WIN_WHITE
        termination = f"FORFEIT ({agent_name}: {reason})"
        pgn_path = self._save_pgn(san_moves, result.value, termination)
        return GameOutcome(
            result=result,
            termination=termination,
            white_name=self.white.name,
            black_name=self.black.name,
            total_moves=ply,
            pgn_path=pgn_path,
            move_log=move_results,
        )

    def _finish(
        self,
        result: GameResult,
        termination: str,
        san_moves: list[str],
        move_results: list[MoveResult],
        ply: int,
        starting_fen: Optional[str] = None,
    ) -> GameOutcome:
        pgn_path = self._save_pgn(san_moves, result.value, termination, starting_fen)
        return GameOutcome(
            result=result,
            termination=termination,
            white_name=self.white.name,
            black_name=self.black.name,
            total_moves=ply,
            pgn_path=pgn_path,
            move_log=move_results,
        )

    def _save_pgn(
        self,
        san_moves: list[str],
        result_str: str,
        termination: str,
        starting_fen: Optional[str] = None,
    ) -> Optional[str]:
        if self.pgn_dir is None:
            return None

        os.makedirs(self.pgn_dir, exist_ok=True)
        path = os.path.join(self.pgn_dir, f"{self.game_id}.pgn")

        game = chess.pgn.Game()
        game.headers["Event"] = "Chess Arena"
        game.headers["Site"] = "Local"
        game.headers["Date"] = datetime.date.today().isoformat()
        game.headers["Round"] = self.game_id
        game.headers["White"] = self.white.name
        game.headers["Black"] = self.black.name
        game.headers["Result"] = result_str
        game.headers["Termination"] = termination

        if starting_fen and starting_fen != chess.STARTING_FEN:
            game.headers["FEN"] = starting_fen
            game.headers["SetUp"] = "1"
            board = chess.Board(starting_fen)
        else:
            board = chess.Board()

        node = game
        for san in san_moves:
            try:
                move = board.parse_san(san)
                node = node.add_variation(move)
                board.push(move)
            except Exception:
                # Fallback: store raw SAN as a comment
                node = node.add_variation(chess.Move.null())
                node.comment = san
                break

        with open(path, "w", encoding="utf-8") as f:
            f.write(str(game))
            f.write("\n\n")

        return path
