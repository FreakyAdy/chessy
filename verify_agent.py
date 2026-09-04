"""
verify_agent.py — Standalone Model Eligibility & Compliance Auditor CLI
═══════════════════════════════════════════════════════════════════════

Usage:
  python verify_agent.py uploaded_agents/friend_bot.py
  python verify_agent.py chess_arena.agents.greedy_agent:GreedyAgent
  python verify_agent.py --help

Interactive Mode:
  python verify_agent.py
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from rich.console import Console
from rich.prompt import Prompt

from chess_arena.arena.validator import ModelAuditor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit external/friend chess models for rule compliance, move legality, and tournament eligibility.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to Python agent file (.py) or module spec (e.g. 'uploaded_agents/my_bot.py' or 'module:Class')",
    )
    parser.add_argument(
        "--class-name",
        "-c",
        default=None,
        help="Name of the agent class to audit (auto-discovered if omitted)",
    )
    parser.add_argument(
        "--time-limit",
        "-t",
        type=float,
        default=5.0,
        help="Maximum move time limit in seconds to benchmark against (default: 5.0)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code if any warning or critical issue is found",
    )

    args = parser.parse_args()
    console = Console(color_system="truecolor", force_terminal=True)

    source = args.source
    if not source:
        console.print("[bold cyan]═════════════════════════════════════════════════════════════════════[/]")
        console.print("[bold white] 🛡️  CHESS ARENA — MODEL ELIGIBILITY & RULE-COMPLIANCE AUDITOR [/]")
        console.print("[bold cyan]═════════════════════════════════════════════════════════════════════[/]")
        console.print("[dim]Audit any friend's model to verify move legality, latency, and sandbox stability.[/]\n")

        # Check for files in uploaded_agents/
        os.makedirs("uploaded_agents", exist_ok=True)
        uploaded = glob.glob("uploaded_agents/*.py")
        if uploaded:
            console.print("[bold]Found models in [cyan]uploaded_agents/[/]:[/]")
            for u in uploaded:
                console.print(f"  • [yellow]{u}[/]")
            console.print()

        source = Prompt.ask(
            "[bold green]Enter agent file path or module path[/]",
            default="uploaded_agents/template_agent.py" if os.path.exists("uploaded_agents/template_agent.py") else "chess_arena/agents/greedy_agent.py",
        )

    if not source or not source.strip():
        console.print("[red]No source provided. Aborting.[/]")
        sys.exit(1)

    auditor = ModelAuditor(time_limit=args.time_limit, console=console)
    report = auditor.audit(
        source=source.strip(),
        class_name=args.class_name,
    )
    auditor.render_report(report)

    if not report.is_eligible or (args.strict and report.warning_count > 0):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
