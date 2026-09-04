#!/usr/bin/env python3
"""
main.py — Chess Arena Entry Point
══════════════════════════════════

Load agents from config, run a tournament, print results.

Usage
-----
    python main.py                     # use default config.yaml
    python main.py --config my.yaml    # custom config
    python main.py --format single_elimination
    python main.py --display           # show ASCII board each move
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows terminals
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import yaml
from rich.console import Console
from rich.panel import Panel
from rich import box

from chess_arena.arena.adapter import AgentProcess, InProcessAgent
from chess_arena.arena.tournament import Tournament

console = Console(color_system="truecolor", force_terminal=True)


def load_config(path: str) -> dict[str, Any]:
    """Load YAML configuration file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def spawn_agents(
    agent_configs: list[dict],
    *,
    use_subprocess: bool = True,
) -> list:
    """Instantiate agents from config entries.

    Parameters
    ----------
    agent_configs:
        List of dicts, each with keys: module, class, name, config.
    use_subprocess:
        If True, wrap each agent in a subprocess (production mode).
        If False, load in-process (for testing).
    """
    agents = []
    for entry in agent_configs:
        module_path = entry["module"]
        class_name = entry["class"]
        name = entry["name"]
        config = entry.get("config", {})

        if use_subprocess:
            try:
                ap = AgentProcess.spawn(module_path, class_name, name, config)
                agents.append(ap)
                console.print(f"  [green]✓[/] {name} ({module_path}.{class_name})")
            except RuntimeError as e:
                console.print(f"  [red]✗[/] {name}: {e}")
                sys.exit(1)
        else:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            agent = cls(name=name, config=config)
            agents.append(InProcessAgent(agent))
            console.print(f"  [green]✓[/] {name} ({module_path}.{class_name}) [dim](in-process)[/]")

    return agents


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chess Arena — Multi-Agent Competition Framework"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["round_robin", "single_elimination"],
        default=None,
        help="Override tournament format from config.",
    )
    parser.add_argument(
        "--display", "-d",
        action="store_true",
        default=None,
        help="Show live updating chessboard in terminal.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Delay between moves for live display in seconds (default: 0.15).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=None,
        help="Pause duration (seconds) after each game finishes (default: 2.5).",
    )
    parser.add_argument(
        "--no-subprocess",
        action="store_true",
        help="Run agents in-process (for debugging).",
    )
    parser.add_argument(
        "--games-per-pair", "-g",
        type=int,
        default=None,
        help="Override number of games per pair.",
    )
    parser.add_argument(
        "--time-limit", "-t",
        type=float,
        default=None,
        help="Override move time limit (seconds).",
    )
    parser.add_argument(
        "--verify-agent", "-v",
        nargs="?",
        const="uploaded_agents/template_agent.py",
        metavar="PATH",
        help="Audit a friend's model for rule compliance, move legality, and tournament eligibility.",
    )
    parser.add_argument(
        "--web", "-w",
        action="store_true",
        help="Launch the live Web UI & tournament streaming server.",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Port for the Web UI server (default: 8000).",
    )
    args = parser.parse_args()

    # ── Web UI Server ────────────────────────────────────────────────────
    if args.web:
        import uvicorn
        console.print(
            Panel(
                f"[bold white]♔  CHESS ARENA — LIVE WEB UI[/]\n"
                f"[dim]Running at http://127.0.0.1:{args.port}[/]\n"
                f"[cyan]WebSocket streaming & 5-bot uploader active[/]",
                box=box.DOUBLE_EDGE,
                style="bold cyan",
                expand=False,
            )
        )
        uvicorn.run("chess_arena.web.app:app", host="127.0.0.1", port=args.port, log_level="info")
        sys.exit(0)

    # ── Model Audit Gate ─────────────────────────────────────────────────
    if args.verify_agent is not None:
        from chess_arena.arena.validator import ModelAuditor
        auditor = ModelAuditor(time_limit=args.time_limit or 5.0, console=console)
        report = auditor.audit(args.verify_agent)
        auditor.render_report(report)
        sys.exit(0 if report.is_eligible else 1)

    # ── Load config ──────────────────────────────────────────────────────
    config_path = args.config
    if not os.path.exists(config_path):
        console.print(f"[red]Config file not found:[/] {config_path}")
        sys.exit(1)

    cfg = load_config(config_path)

    # Apply CLI overrides
    tournament_format = args.format or cfg.get("tournament", {}).get("format", "round_robin")
    games_per_pair = args.games_per_pair or cfg.get("tournament", {}).get("games_per_pair", 2)
    move_time_limit = args.time_limit or cfg.get("match", {}).get("move_time_limit", 5.0)
    max_moves = cfg.get("match", {}).get("max_moves", 500)
    display_board = (
        args.display
        if args.display is not None
        else cfg.get("match", {}).get(
            "display_board", cfg.get("output", {}).get("display_board", False)
        )
    )
    move_delay = (
        args.delay
        if args.delay is not None
        else cfg.get("match", {}).get("move_delay", 0.15)
    )
    game_pause = (
        args.pause
        if args.pause is not None
        else cfg.get("match", {}).get("game_pause", 2.5)
    )
    pgn_dir = cfg.get("output", {}).get("games_dir", "games")

    # ── Banner ───────────────────────────────────────────────────────────
    console.print(
        Panel(
            "[bold white]♔  CHESS ARENA  ♚[/]\n"
            "[dim]Multi-Agent Competition Framework[/]",
            box=box.DOUBLE_EDGE,
            style="bold cyan",
            expand=False,
        )
    )

    # ── Spawn agents ─────────────────────────────────────────────────────
    agent_configs = cfg.get("agents", [])
    if len(agent_configs) < 2:
        console.print("[red]Need at least 2 agents in config.[/]")
        sys.exit(1)

    console.print("\n[bold]Loading agents…[/]")
    agents = spawn_agents(
        agent_configs,
        use_subprocess=not args.no_subprocess,
    )

    # ── Ensure unique names ──────────────────────────────────────────────
    names = [a.name for a in agents]
    if len(names) != len(set(names)):
        console.print("[red]Agent names must be unique![/]")
        sys.exit(1)

    # ── Run tournament ───────────────────────────────────────────────────
    console.print()
    try:
        tourney = Tournament(
            agents=agents,
            tournament_format=tournament_format,
            games_per_pair=games_per_pair,
            move_time_limit=move_time_limit,
            max_moves=max_moves,
            display_board=display_board,
            move_delay=move_delay,
            game_pause=game_pause,
            pgn_dir=pgn_dir,
        )
        result = tourney.run()
    finally:
        # Always clean up subprocess agents
        console.print("\n[dim]Shutting down agents…[/]")
        for a in agents:
            try:
                a.shutdown()
            except Exception:
                pass

    # ── Save results summary ─────────────────────────────────────────────
    results_dir = cfg.get("output", {}).get("results_dir", "results")
    os.makedirs(results_dir, exist_ok=True)
    results_path = os.path.join(results_dir, "standings.txt")

    with open(results_path, "w", encoding="utf-8") as f:
        f.write("Chess Arena — Final Standings\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Format: {result.format}\n")
        f.write(f"Total games: {len(result.outcomes)}\n\n")
        f.write(f"{'#':<4} {'Agent':<25} {'Pts':>6} {'W':>4} {'D':>4} {'L':>4} {'GP':>4}\n")
        f.write("-" * 60 + "\n")
        for i, r in enumerate(result.ranked, 1):
            f.write(
                f"{i:<4} {r.name:<25} {r.points:>6.1f} {r.wins:>4} "
                f"{r.draws:>4} {r.losses:>4} {r.games_played:>4}\n"
            )
        f.write("\n")

    console.print(f"\n[dim]Standings saved to: {results_path}[/]")
    console.print("[bold green]Done![/]")


if __name__ == "__main__":
    main()
