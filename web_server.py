#!/usr/bin/env python3
"""
web_server.py — Chess Arena Live Web UI Server Entry Point
═════════════════════════════════════════════════════════

Usage:
    python web_server.py
    python web_server.py --port 8080
    python web_server.py --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import os
import sys
import uvicorn

# Ensure UTF-8 output on Windows terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chess Arena Live Web UI — Real-time match streaming, board visualization & 5-bot uploader"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="Port to bind (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes",
    )

    args = parser.parse_args()

    print("\n" + "═" * 65)
    print("  ♔  CHESS ARENA — LIVE WEB UI & TOURNAMENT SUITE")
    print("═" * 65)
    print(f"  ➜ Web Interface : http://{args.host}:{args.port}")
    print(f"  ➜ WebSocket API : ws://{args.host}:{args.port}/ws/live")
    print(f"  ➜ Bot Uploader  : Up to 5 custom Python bots with instant audit")
    print("  ➜ Press Ctrl+C to stop.")
    print("═" * 65 + "\n")

    uvicorn.run(
        "chess_arena.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
