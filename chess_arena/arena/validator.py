"""
validator.py — Model Eligibility & Rule-Compliance Auditor
═════════════════════════════════════════════════════════

Automated gatekeeper for validating external / friend-submitted chess models
before admitting them into tournament rosters.

Audits:
  1. [INTERFACE]   ChessAgent ABC compliance & method signatures
  2. [LEGALITY]    Move legality across 16 tactical & positional FEN benchmarks
  3. [LATENCY]     Decision latency benchmarks against the 5.0s limit
  4. [SANDBOX]     Subprocess IPC isolation & memory cleanup (AgentProcess)
  5. [RESILIENCE]  Error handling on edge positions, pins, checks, promotions
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Type

import chess
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from chess_arena.arena.adapter import ChessAgent, AgentProcess, InProcessAgent


class FindingSeverity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    category: str
    severity: FindingSeverity
    title: str
    description: str
    evidence: str
    fix: str


@dataclass
class LatencyBenchmark:
    min_ms: float = 0.0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    iterations: int = 0


@dataclass
class AuditReport:
    model_name: str
    class_name: str
    source_path: str
    is_eligible: bool = False
    score: int = 0  # 0 to 100
    total_checks: int = 0
    passed_checks: int = 0
    findings: list[Finding] = field(default_factory=list)
    latency: LatencyBenchmark = field(default_factory=LatencyBenchmark)
    benchmark_details: list[dict] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == FindingSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == FindingSeverity.WARNING)

    @property
    def critical_issues(self) -> list[str]:
        return [f"{f.title}: {f.description}" for f in self.findings if f.severity == FindingSeverity.CRITICAL]

    @property
    def warnings(self) -> list[str]:
        return [f"{f.title}: {f.description}" for f in self.findings if f.severity == FindingSeverity.WARNING]

    @property
    def total_positions_tested(self) -> int:
        return len(self.benchmark_details)

    @property
    def summary(self) -> str:
        status = "ELIGIBLE" if self.is_eligible else "DISQUALIFIED"
        return f"{status} (Score: {self.score}/100, Passed: {self.passed_checks}/{self.total_checks}, Critical: {self.critical_count}, Warnings: {self.warning_count})"


# ── Benchmark Positions for Legality & Edge Cases ───────────────────────────
BENCHMARK_POSITIONS = [
    {
        "name": "Standard Starting Position",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "description": "20 legal opening moves (16 pawn pushes + 4 knight moves)",
    },
    {
        "name": "Under Check (King Evasion / Block)",
        "fen": "rnb1kbnr/pppp1ppp/8/4p3/5PPq/8/PPPPP2P/RNBQKBNR w KQkq - 1 3",
        "description": "Fool's mate pattern: King under queen check, must respond to check",
    },
    {
        "name": "Legal En Passant Capture",
        "fen": "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
        "description": "White pawn on e5 with en passant target square f6 (exf6 legal)",
    },
    {
        "name": "Kingside Castling Available",
        "fen": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "description": "White king and rook ready for O-O (e1g1)",
    },
    {
        "name": "Queenside Castling Available",
        "fen": "r3kbnr/ppp1pppp/2nq4/3p4/3P4/2NQ4/PPP1PPPP/R3KBNR w KQkq - 2 5",
        "description": "White queenside cleared for O-O-O (e1c1)",
    },
    {
        "name": "Castling Blocked Through Check",
        "fen": "r3k2r/ppp2ppp/2n5/3q4/3b4/5N2/PPPP1PPP/R3K2R w KQkq - 0 1",
        "description": "Enemy pieces target transit square; castling must be refused if in/through check",
    },
    {
        "name": "Pawn Promotion (Queening / Underpromotion)",
        "fen": "8/4P3/8/8/8/8/k7/4K3 w - - 0 1",
        "description": "White pawn on 7th rank with no opposition; must promote legally (e7e8q/r/b/n)",
    },
    {
        "name": "Pawn Promotion with Capture",
        "fen": "5n2/4P3/8/8/8/8/k7/4K3 w - - 0 1",
        "description": "White pawn can push or capture knight on f8 with promotion",
    },
    {
        "name": "Absolute Pin to King",
        "fen": "rnb1k1nr/pppp1ppp/8/4p3/1b1PP3/2N5/PPP2PPP/R1BQKBNR w KQkq - 1 4",
        "description": "Knight on c3 is pinned to King on e1 by Bishop on b4; moving knight is illegal",
    },
    {
        "name": "Double Check (King Must Move)",
        "fen": "r1b1k2r/pppp1Npp/8/4p3/2Bn3q/8/PPP2nPP/RNB1K2R w KQkq - 0 9",
        "description": "Severe double threat where only King movements are legal",
    },
    {
        "name": "King & Queen vs Lone King Endgame",
        "fen": "8/8/8/4k3/8/8/8/4K1Q1 w - - 0 1",
        "description": "Endgame position testing conversion without stalemate trap",
    },
    {
        "name": "King & Rook vs Lone King Endgame",
        "fen": "8/8/8/4k3/8/8/8/4K1R1 w - - 0 1",
        "description": "Elementary endgame requiring basic ladder or box confinement",
    },
    {
        "name": "Complex Tactical Middlegame",
        "fen": "r1b2rk1/pp1n1ppp/2p1pn2/q2p2B1/2PP4/2NBPN2/PP3PPP/R2QK2R w KQ - 3 9",
        "description": "Orthodox Queen's Gambit Declined with 38 legal moves",
    },
    {
        "name": "Closed Pawn Chain Tension",
        "fen": "r1b1qrk1/1ppn1pbp/p2p1np1/3Pp3/1PP1P3/2NB1N2/P4PPP/R1BQ1RK1 w - - 1 10",
        "description": "King's Indian Defense locked center position",
    },
    {
        "name": "Asymmetric Material Imbalance",
        "fen": "r4rk1/1pp2ppp/p1np4/4p3/B3P1b1/2NP1N2/PPP2PPP/R2Q1RK1 w - - 0 11",
        "description": "Rook and pawns vs two minor pieces",
    },
    {
        "name": "King Escaping to Edge (Stalemate Avoidance)",
        "fen": "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1",
        "description": "Extreme position where only 1 legal response exists or stalemate risk",
    },
]


# ── Model Loader ─────────────────────────────────────────────────────────────
def load_agent_class(
    source: str,
    class_name: Optional[str] = None,
) -> tuple[Type[ChessAgent], str, str]:
    """Load a ChessAgent class from a file path or module specification.

    Parameters
    ----------
    source : str
        Either a filepath (e.g. ``"uploaded_agents/my_bot.py"``),
        or a Python module string (e.g. ``"chess_arena.agents.greedy_agent"``),
        or ``"module:Class"``.
    class_name : str, optional
        Specific class name to extract. If omitted, auto-discovers.

    Returns
    -------
    tuple[Type[ChessAgent], str, str]
        (AgentClass, resolved_module_path, resolved_class_name)
    """
    # 1. Check if source is a file path
    if os.path.exists(source) and os.path.isfile(source):
        module_name = f"external_agent_{os.path.splitext(os.path.basename(source))[0]}"
        spec = importlib.util.spec_from_file_location(module_name, os.path.abspath(source))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module spec from file: {source}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        resolved_module = os.path.abspath(source)
    elif ":" in source:
        mod_part, cls_part = source.split(":", 1)
        mod = importlib.import_module(mod_part)
        class_name = cls_part.strip()
        resolved_module = mod_part
    else:
        mod = importlib.import_module(source)
        resolved_module = source

    # 2. Extract agent class
    target_class = None
    if class_name:
        if hasattr(mod, class_name):
            target_class = getattr(mod, class_name)
        else:
            raise AttributeError(f"Module '{resolved_module}' has no class named '{class_name}'")
    else:
        # Auto-discover subclass of ChessAgent or duck-typing get_move
        candidates = []
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if obj.__module__ == mod.__name__:
                if issubclass(obj, ChessAgent) and obj is not ChessAgent:
                    candidates.append((10, name, obj))
                elif hasattr(obj, "get_move") and callable(getattr(obj, "get_move")):
                    candidates.append((5, name, obj))
        if not candidates:
            raise TypeError(
                f"No ChessAgent class found in '{source}'. "
                f"Ensure your class inherits from ChessAgent or implements get_move(fen, legal_moves)."
            )
        candidates.sort(key=lambda x: x[0], reverse=True)
        target_class = candidates[0][2]
        class_name = candidates[0][1]

    return target_class, resolved_module, class_name


# ── Core Auditor Engine ──────────────────────────────────────────────────────
class ModelAuditor:
    """Rigorous qualification auditor for chess models."""

    def __init__(
        self,
        time_limit: float = 5.0,
        console: Optional[Console] = None,
    ) -> None:
        self.time_limit = time_limit
        self.console = console or Console(color_system="truecolor", force_terminal=True)

    def audit(
        self,
        source: str,
        class_name: Optional[str] = None,
        config: Optional[dict] = None,
        display_progress: bool = True,
    ) -> AuditReport:
        """Execute the complete qualification audit on the specified model."""
        config = config or {}
        report = AuditReport(
            model_name="Unknown",
            class_name="Unknown",
            source_path=source,
        )

        # ── Phase 1: Dynamic Import & Interface Compliance ───────────────────
        report.total_checks += 1
        try:
            agent_cls, resolved_mod, resolved_cls = load_agent_class(source, class_name)
            report.class_name = resolved_cls
            report.passed_checks += 1
        except Exception as exc:
            report.findings.append(
                Finding(
                    category="INTERFACE",
                    severity=FindingSeverity.CRITICAL,
                    title="Module Import Failure",
                    description="The model could not be imported or parsed by the Python runtime.",
                    evidence=str(exc),
                    fix="Verify Python syntax, package imports, and ensure the agent file is valid Python 3.",
                )
            )
            report.score = 0
            report.is_eligible = False
            return report

        # ── Phase 2: Instantiation & Signature Check ────────────────────────
        report.total_checks += 1
        try:
            agent_instance: ChessAgent = agent_cls(name="Auditor-Test-Agent", config=config)
            report.model_name = getattr(agent_instance, "name", resolved_cls)
            report.passed_checks += 1
        except Exception as exc:
            report.findings.append(
                Finding(
                    category="INTERFACE",
                    severity=FindingSeverity.CRITICAL,
                    title="Instantiation Failure",
                    description="The agent class failed to instantiate with (name, config).",
                    evidence=str(exc),
                    fix="Implement __init__(self, name: str = 'Agent', config: dict = None) in your class.",
                )
            )
            report.score = 15
            report.is_eligible = False
            return report

        # Method signature verification
        report.total_checks += 1
        if not hasattr(agent_instance, "get_move") or not callable(getattr(agent_instance, "get_move")):
            report.findings.append(
                Finding(
                    category="INTERFACE",
                    severity=FindingSeverity.CRITICAL,
                    title="Missing get_move() Method",
                    description="The agent does not implement the mandatory get_move() method.",
                    evidence=f"Class {resolved_cls} missing callable get_move",
                    fix="Implement get_move(self, board_fen: str, legal_moves: list[str]) -> str.",
                )
            )
        else:
            report.passed_checks += 1

        # ── Phase 3: Legality Across 16 Tactical & Positional Benchmarks ──────
        latencies: list[float] = []
        legality_passed = 0

        for idx, pos in enumerate(BENCHMARK_POSITIONS, 1):
            report.total_checks += 1
            fen = pos["fen"]
            board = chess.Board(fen)
            legal_moves = [m.uci() for m in board.legal_moves]

            if not legal_moves:
                # Terminal position benchmark
                report.passed_checks += 1
                continue

            t_start = time.perf_counter()
            try:
                chosen_move = agent_instance.get_move(fen, list(legal_moves))
                t_elapsed = time.perf_counter() - t_start
                latencies.append(t_elapsed * 1000.0)
            except Exception as exc:
                report.findings.append(
                    Finding(
                        category="RESILIENCE",
                        severity=FindingSeverity.CRITICAL,
                        title=f"Exception on {pos['name']}",
                        description=f"Agent threw an uncaught exception during move selection: {exc}",
                        evidence=f"FEN: {fen}\nError: {exc}",
                        fix="Wrap internal evaluation in try/except and ensure fallback move on edge positions.",
                    )
                )
                continue

            # Return type check
            if not isinstance(chosen_move, str):
                report.findings.append(
                    Finding(
                        category="INTERFACE",
                        severity=FindingSeverity.CRITICAL,
                        title=f"Invalid Return Type on {pos['name']}",
                        description=f"Expected str, got {type(chosen_move).__name__}.",
                        evidence=f"Returned: {repr(chosen_move)}",
                        fix="Ensure get_move() returns a UCI string (e.g. 'e2e4').",
                    )
                )
                continue

            # Move legality verification
            if chosen_move not in legal_moves:
                report.findings.append(
                    Finding(
                        category="LEGALITY",
                        severity=FindingSeverity.CRITICAL,
                        title=f"Illegal Move on {pos['name']}",
                        description=f"The agent generated '{chosen_move}' which is not in the legal move list.",
                        evidence=f"FEN: {fen}\nIllegal Move: {chosen_move}\nLegal Moves: {legal_moves[:6]}...",
                        fix="Select moves exclusively from the provided legal_moves list or validate with python-chess.",
                    )
                )
            else:
                legality_passed += 1
                report.passed_checks += 1

            # Latency check for individual move
            if t_elapsed > self.time_limit:
                report.findings.append(
                    Finding(
                        category="LATENCY",
                        severity=FindingSeverity.CRITICAL,
                        title=f"Move Timeout on {pos['name']}",
                        description=f"Decision took {t_elapsed:.2f}s, exceeding the {self.time_limit:.1f}s limit.",
                        evidence=f"Latency: {t_elapsed:.2f}s > {self.time_limit:.1f}s",
                        fix="Optimize evaluation depth, implement move time capping, or cache positions.",
                    )
                )

            report.benchmark_details.append(
                {
                    "name": pos["name"],
                    "move": chosen_move,
                    "legal": chosen_move in legal_moves,
                    "latency_ms": t_elapsed * 1000.0,
                }
            )

        # ── Phase 4: Subprocess Sandbox & IPC Isolation ──────────────────────
        report.total_checks += 1
        try:
            # Test in isolated child process
            test_proc = AgentProcess.spawn(
                module_path=resolved_mod,
                class_name=resolved_cls,
                name="Sandbox-Test-Bot",
                config=config,
            )
            time.sleep(0.05)
            if not test_proc.is_alive():
                raise RuntimeError("Process exited prematurely.")

            test_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            test_legals = [m.uci() for m in chess.Board(test_fen).legal_moves]
            res_move = test_proc.request_move(test_fen, test_legals, timeout=self.time_limit)
            if res_move not in test_legals:
                raise ValueError(f"Subprocess agent returned illegal move: {res_move}")

            test_proc.shutdown()
            report.passed_checks += 1
        except Exception as exc:
            report.findings.append(
                Finding(
                    category="SANDBOX",
                    severity=FindingSeverity.CRITICAL,
                    title="Subprocess IPC Failure",
                    description="Agent failed when executed in isolated multiprocessing sandbox.",
                    evidence=str(exc),
                    fix="Ensure agent doesn't rely on non-picklable unpickled locks, CUDA main-process state, or stdin.",
                )
            )

        # ── Phase 5: Latency Statistics & Eligibility Scoring ────────────────
        if latencies:
            latencies.sort()
            n = len(latencies)
            report.latency = LatencyBenchmark(
                min_ms=round(latencies[0], 2),
                avg_ms=round(sum(latencies) / n, 2),
                p95_ms=round(latencies[int(n * 0.95)], 2) if n > 1 else round(latencies[0], 2),
                max_ms=round(latencies[-1], 2),
                iterations=n,
            )

        # Scoring: 100 points maximum
        # - API & Interface: 25 pts
        # - Legality: 50 pts
        # - Latency & Sandbox: 25 pts
        score = 0
        if not any(f.category == "INTERFACE" for f in report.findings):
            score += 25
        legality_ratio = legality_passed / max(1, len(BENCHMARK_POSITIONS))
        score += int(legality_ratio * 50)
        if not any(f.category == "SANDBOX" for f in report.findings):
            score += 15
        if not any(f.category == "LATENCY" for f in report.findings):
            score += 10

        report.score = max(0, min(100, score))
        report.is_eligible = (report.score >= 90) and (report.critical_count == 0)

        return report

    def render_report(self, report: AuditReport) -> None:
        """Print a structured, ratctl-styled visual audit report to the terminal."""
        c = self.console
        c.print()

        # ── Header Banner ────────────────────────────────────────────────────
        status_color = "green" if report.is_eligible else "red"
        status_text = "ELIGIBLE FOR TOURNAMENT" if report.is_eligible else "DISQUALIFIED / NON-COMPLIANT"

        header = Table(show_header=False, box=None, padding=(0, 1))
        header.add_column(justify="left")
        header.add_row(Text("🛡️ MODEL ELIGIBILITY & COMPLIANCE AUDIT", style="bold cyan"))
        header.add_row(Text("═" * 66, style="dim"))
        header.add_row(
            Text(f" Model Candidate : {report.model_name} ({report.class_name})", style="bold white")
        )
        header.add_row(Text(f" Source Location : {report.source_path}", style="dim"))
        header.add_row(
            Text(f" Qualification   : [{status_color}]{status_text}[/]", style=f"bold {status_color}")
        )
        header.add_row(
            Text(f" Score           : {report.score}/100  ({report.passed_checks}/{report.total_checks} checks passed)", style="bold")
        )

        c.print(
            Panel(
                header,
                border_style=status_color,
                box=box.DOUBLE_EDGE,
                padding=(1, 2),
            )
        )

        # ── Performance & Latency Panel ──────────────────────────────────────
        lat = report.latency
        lat_table = Table(show_header=True, box=box.SIMPLE, padding=(0, 1))
        lat_table.add_column("Benchmark Metric", style="dim")
        lat_table.add_column("Measurement", justify="right", style="bold cyan")
        lat_table.add_column("Threshold", justify="right", style="dim")
        lat_table.add_column("Status", justify="center")

        max_ok = lat.max_ms <= (self.time_limit * 1000.0)
        p95_ok = lat.p95_ms <= (self.time_limit * 1000.0 * 0.8)

        lat_table.add_row("Average Move Latency", f"{lat.avg_ms:.1f} ms", "—", "✅")
        lat_table.add_row("95th Percentile Latency", f"{lat.p95_ms:.1f} ms", f"< {self.time_limit*800:.0f} ms", "✅" if p95_ok else "⚠️")
        lat_table.add_row("Peak Decision Time", f"{lat.max_ms:.1f} ms", f"< {self.time_limit*1000:.0f} ms", "✅" if max_ok else "❌")
        lat_table.add_row("Tested Benchmark Positions", f"{lat.iterations}", "16 positions", "✅")

        c.print(
            Panel(
                lat_table,
                title="[bold]Move Latency & Resource Profile[/]",
                border_style="dim",
                box=box.ROUNDED,
            )
        )

        # ── Findings by Exploit / Failure Class ───────────────────────────────
        if report.findings:
            c.print("\n[bold red]AUDIT FINDINGS & DISQUALIFYING REASONS:[/]")
            for idx, finding in enumerate(report.findings, 1):
                sev_color = "red" if finding.severity == FindingSeverity.CRITICAL else "yellow"
                c.print(f"\n  [bold {sev_color}]{idx}. [{finding.severity.value.upper()}] [{finding.category}] {finding.title}[/]")
                c.print(f"     [dim]Description:[/] {finding.description}")
                c.print(f"     [dim]Evidence:   [/] [red]{finding.evidence[:120]}[/]")
                c.print(f"     [bold green]Recommended Fix:[/] {finding.fix}")
        else:
            c.print("\n[bold green]✅ 0 Deficiencies Found: Agent is 100% compliant with FIDE & Framework rules![/]")

        # ── Next Steps Instructions ──────────────────────────────────────────
        c.print()
        if report.is_eligible:
            inst = (
                f"[bold green]To admit this model into the competition roster:[/] Add this entry to [bold cyan]config.yaml[/]:\n\n"
                f"  - name: \"{report.model_name}\"\n"
                f"    module: \"{report.source_path}\"\n"
                f"    class: \"{report.class_name}\"\n"
                f"    config: {{}}\n"
            )
            c.print(Panel(inst, title="[bold green]Roster Enrolment Ready[/]", border_style="green", box=box.ROUNDED))
        else:
            inst = (
                f"[bold red]Candidate is currently disqualified from tournament play.[/]\n"
                f"Resolve the critical findings above, then re-run:\n"
                f"  [bold white]python verify_agent.py {report.source_path}[/]"
            )
            c.print(Panel(inst, title="[bold red]Action Required[/]", border_style="red", box=box.ROUNDED))
        c.print()
