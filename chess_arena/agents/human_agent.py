"""
human_agent.py — CLI Human Player Agent
════════════════════════════════════════

Lets a human play via the terminal.  Shows the board, legal moves,
and accepts UCI input.  Useful for debugging and testing.
"""

from __future__ import annotations

import chess

from chess_arena.arena.adapter import ChessAgent
from chess_arena.arena.board import BoardState


class HumanAgent(ChessAgent):
    """Interactive CLI agent — prompts the human for a UCI move."""

    def __init__(self, name: str = "Human", config: dict | None = None) -> None:
        super().__init__(name=name, config=config or {})

    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        board = BoardState.from_fen(fen)

        print("\n" + "─" * 50)
        print(f"  {self.name}'s turn  ({board.active_color_name})")
        print(board.ascii())
        print(f"\n  FEN: {fen}")
        print(f"  Legal moves ({len(legal_moves)}):")

        # Group legal moves by source square for readability
        grouped: dict[str, list[str]] = {}
        for m in legal_moves:
            src = m[:2]
            grouped.setdefault(src, []).append(m)

        for src, moves in sorted(grouped.items()):
            piece = board.inner.piece_at(chess.parse_square(src))
            piece_sym = piece.symbol().upper() if piece else "?"
            print(f"    {piece_sym} {src}: {', '.join(moves)}")

        while True:
            try:
                raw = input(f"\n  {self.name} move (UCI): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  [Resigning]")
                return "0000"  # null move → will be caught as illegal → forfeit
            if raw in legal_moves:
                return raw
            print(f"  '{raw}' is not in the legal move list. Try again.")
