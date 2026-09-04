"""
tournament.py — Round-Robin & Single-Elimination Scheduler
══════════════════════════════════════════════════════════

Manages multi-agent competitions:

* **Round Robin** — every agent plays every other agent (N games each pair,
  alternating colours).
* **Single Elimination** — bracket-style knockout (best of N, alternating
  colours).

Tracks standings, prints a rich leaderboard, and writes a full PGN archive.
"""

from __future__ import annotations

import itertools
import math
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from chess_arena.arena.runner import GameRunner, GameOutcome, GameResult


# ═════════════════════════════════════════════════════════════════════════════
#  Agent protocol
# ═════════════════════════════════════════════════════════════════════════════

class AgentLike(Protocol):
    name: str
    def request_move(self, fen: str, legal_moves: list[str], timeout: float) -> str: ...
    def is_alive(self) -> bool: ...


# ═════════════════════════════════════════════════════════════════════════════
#  Standings
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class PlayerRecord:
    """Win/draw/loss record for one agent."""
    name: str
    wins: int = 0
    draws: int = 0
    losses: int = 0

    @property
    def points(self) -> float:
        return self.wins + 0.5 * self.draws

    @property
    def games_played(self) -> int:
        return self.wins + self.draws + self.losses

    @property
    def win_rate(self) -> float:
        if self.games_played == 0:
            return 0.0
        return self.wins / self.games_played


@dataclass
class TournamentResult:
    """Final summary of a completed tournament."""
    format: str
    standings: list[PlayerRecord]
    outcomes: list[GameOutcome] = field(default_factory=list)

    @property
    def ranked(self) -> list[PlayerRecord]:
        return sorted(
            self.standings,
            key=lambda r: (r.points, r.wins, -r.losses),
            reverse=True,
        )


# ═════════════════════════════════════════════════════════════════════════════
#  Tournament
# ═════════════════════════════════════════════════════════════════════════════

class Tournament:
    """Run a full tournament among a pool of agents.

    Parameters
    ----------
    agents:
        List of agent handles (AgentProcess or InProcessAgent).
    tournament_format:
        ``"round_robin"`` or ``"single_elimination"``.
    games_per_pair:
        Number of games per pairing (round robin).  Rounded up to next even
        number so that colours alternate fairly.
    move_time_limit:
        Per-move time budget in seconds.
    max_moves:
        Per-game safety cap (full moves).
    display_board:
        Print ASCII board after every move.
    pgn_dir:
        Where to save PGN files.
    """

    def __init__(
        self,
        agents: list[AgentLike],
        *,
        tournament_format: str = "round_robin",
        games_per_pair: int = 2,
        move_time_limit: float = 5.0,
        max_moves: int = 500,
        display_board: bool = False,
        move_delay: float = 0.15,
        game_pause: float = 2.5,
        pgn_dir: str = "games",
    ) -> None:
        if len(agents) < 2:
            raise ValueError("Need at least 2 agents for a tournament.")

        self.agents = agents
        self.format = tournament_format
        self.games_per_pair = games_per_pair if games_per_pair % 2 == 0 else games_per_pair + 1
        self.move_time_limit = move_time_limit
        self.max_moves = max_moves
        self.display_board = display_board
        self.move_delay = move_delay
        self.game_pause = game_pause
        self.pgn_dir = pgn_dir

        self.console = Console(color_system="truecolor", force_terminal=True)
        self._records: dict[str, PlayerRecord] = {
            a.name: PlayerRecord(name=a.name) for a in agents
        }
        self._outcomes: list[GameOutcome] = []
        self._game_counter = 0

    # ── Public API ───────────────────────────────────────────────────────
    def run(self) -> TournamentResult:
        if self.format == "round_robin":
            return self._run_round_robin()
        elif self.format == "single_elimination":
            return self._run_single_elimination()
        else:
            raise ValueError(f"Unknown format: {self.format!r}")

    # ── Round Robin ──────────────────────────────────────────────────────
    def _run_round_robin(self) -> TournamentResult:
        pairs = list(itertools.combinations(self.agents, 2))
        total_games = len(pairs) * self.games_per_pair
        self.console.print(
            Panel(
                f"[bold cyan]Round Robin Tournament[/]\n"
                f"  Agents       : {len(self.agents)}\n"
                f"  Pairings     : {len(pairs)}\n"
                f"  Games/pair   : {self.games_per_pair}\n"
                f"  Total games  : {total_games}\n"
                f"  Time limit   : {self.move_time_limit}s/move",
                box=box.DOUBLE_EDGE,
            )
        )

        for a, b in pairs:
            for game_idx in range(self.games_per_pair):
                # Alternate colours
                if game_idx % 2 == 0:
                    white, black = a, b
                else:
                    white, black = b, a
                self._play_game(white, black)
                self._print_standings()

        result = TournamentResult(
            format="round_robin",
            standings=list(self._records.values()),
            outcomes=list(self._outcomes),
        )
        self._print_final(result)
        return result

    # ── Single Elimination ───────────────────────────────────────────────
    def _run_single_elimination(self) -> TournamentResult:
        bracket = list(self.agents)
        # Pad to next power of 2 with byes
        size = 1
        while size < len(bracket):
            size *= 2

        self.console.print(
            Panel(
                f"[bold cyan]Single Elimination Tournament[/]\n"
                f"  Agents  : {len(bracket)}\n"
                f"  Bracket : {size} slots\n"
                f"  Rounds  : {int(math.log2(size))}\n"
                f"  Time    : {self.move_time_limit}s/move",
                box=box.DOUBLE_EDGE,
            )
        )

        round_num = 1
        while len(bracket) > 1:
            self.console.print(f"\n[bold yellow]── Round {round_num} ──[/]")
            next_round: list[AgentLike] = []
            for i in range(0, len(bracket), 2):
                if i + 1 >= len(bracket):
                    # Bye
                    self.console.print(f"  {bracket[i].name} gets a bye.")
                    next_round.append(bracket[i])
                    continue
                winner = self._play_match(bracket[i], bracket[i + 1])
                next_round.append(winner)
            bracket = next_round
            round_num += 1
            self._print_standings()

        self.console.print(
            f"\n[bold green]🏆 Champion: {bracket[0].name}[/]"
        )

        result = TournamentResult(
            format="single_elimination",
            standings=list(self._records.values()),
            outcomes=list(self._outcomes),
        )
        self._print_final(result)
        return result

    def _play_match(self, a: AgentLike, b: AgentLike) -> AgentLike:
        """Play a best-of-N match and return the winner."""
        a_wins = 0
        b_wins = 0
        for game_idx in range(self.games_per_pair):
            if game_idx % 2 == 0:
                white, black = a, b
            else:
                white, black = b, a
            outcome = self._play_game(white, black)
            if outcome.result == GameResult.WIN_WHITE:
                if white is a:
                    a_wins += 1
                else:
                    b_wins += 1
            elif outcome.result == GameResult.WIN_BLACK:
                if black is a:
                    a_wins += 1
                else:
                    b_wins += 1
        # Tiebreak: whoever won more games; if tied, first player advances
        if a_wins >= b_wins:
            self.console.print(
                f"  [green]{a.name}[/] beats [red]{b.name}[/] "
                f"({a_wins}–{b_wins})"
            )
            return a
        else:
            self.console.print(
                f"  [green]{b.name}[/] beats [red]{a.name}[/] "
                f"({b_wins}–{a_wins})"
            )
            return b

    # ── Core: play one game ──────────────────────────────────────────────
    def _play_game(
        self, white: AgentLike, black: AgentLike
    ) -> GameOutcome:
        self._game_counter += 1
        game_id = f"game_{self._game_counter:04d}"

        self.console.print(
            f"\n[bold]Game {self._game_counter}:[/] "
            f"{white.name} (White) vs {black.name} (Black)"
        )

        runner = GameRunner(
            white=white,
            black=black,
            move_time_limit=self.move_time_limit,
            max_moves=self.max_moves,
            display_board=self.display_board,
            move_delay=self.move_delay,
            game_pause=self.game_pause,
            console=self.console,
            pgn_dir=self.pgn_dir,
            game_id=game_id,
        )
        outcome = runner.run()
        self._outcomes.append(outcome)

        # Update records
        self._update_records(outcome)

        # Print result
        if outcome.result == GameResult.WIN_WHITE:
            self.console.print(
                f"  → [green]{white.name} wins[/] ({outcome.termination}) "
                f"in {outcome.total_moves} moves"
            )
        elif outcome.result == GameResult.WIN_BLACK:
            self.console.print(
                f"  → [green]{black.name} wins[/] ({outcome.termination}) "
                f"in {outcome.total_moves} moves"
            )
        else:
            self.console.print(
                f"  → [yellow]Draw[/] ({outcome.termination}) "
                f"in {outcome.total_moves} moves"
            )

        return outcome

    def _update_records(self, outcome: GameOutcome) -> None:
        w = self._records[outcome.white_name]
        b = self._records[outcome.black_name]
        if outcome.result == GameResult.WIN_WHITE:
            w.wins += 1
            b.losses += 1
        elif outcome.result == GameResult.WIN_BLACK:
            b.wins += 1
            w.losses += 1
        else:
            w.draws += 1
            b.draws += 1

    # ── Display ──────────────────────────────────────────────────────────
    def _print_standings(self) -> None:
        table = Table(
            title="[bold]Leaderboard[/]",
            box=box.ROUNDED,
            show_lines=True,
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Agent", style="bold cyan")
        table.add_column("Pts", justify="right", style="bold green")
        table.add_column("W", justify="right")
        table.add_column("D", justify="right")
        table.add_column("L", justify="right")
        table.add_column("GP", justify="right", style="dim")
        table.add_column("Win%", justify="right")

        ranked = sorted(
            self._records.values(),
            key=lambda r: (r.points, r.wins, -r.losses),
            reverse=True,
        )
        for i, r in enumerate(ranked, 1):
            table.add_row(
                str(i),
                r.name,
                f"{r.points:.1f}",
                str(r.wins),
                str(r.draws),
                str(r.losses),
                str(r.games_played),
                f"{r.win_rate:.0%}" if r.games_played else "—",
            )

        self.console.print(table)

    def _print_final(self, result: TournamentResult) -> None:
        self.console.print("\n")
        self.console.rule("[bold green]FINAL STANDINGS", style="green")
        self._print_standings()

        # Save combined PGN archive
        if self.pgn_dir and self._outcomes:
            archive_path = os.path.join(self.pgn_dir, "tournament_archive.pgn")
            with open(archive_path, "w", encoding="utf-8") as f:
                for outcome in self._outcomes:
                    if outcome.pgn_path and os.path.exists(outcome.pgn_path):
                        with open(outcome.pgn_path, "r", encoding="utf-8") as pf:
                            f.write(pf.read())
                            f.write("\n\n")
            self.console.print(
                f"\n[dim]Full PGN archive saved to: {archive_path}[/]"
            )
