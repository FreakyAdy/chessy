"""
display.py — Live In-Place Terminal Chess Display
═════════════════════════════════════════════════

Renders a single live-updating chessboard per game that updates in-place
after each move. When a game completes, it stops and preserves the final
board with the victory banner permanently on screen, before the next game
starts on its own fresh live board.

Uses solid piece glyphs with tuned square palettes to ensure:
1. White pieces (especially pawns) are brilliant, solid, opaque white.
2. Black pieces are crisp, solid black.
3. Every piece has identical monospace metrics, eliminating glyph overflow.
"""

from __future__ import annotations

import sys
import time
from typing import Optional

import chess
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from chess_arena.arena.board import BoardState
from chess_arena.arena.referee import MoveResult, GameStatus


# ── Ensure Windows terminal uses UTF-8 ───────────────────────────────────────
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Piece rendering ──────────────────────────────────────────────────────────
# We use solid filled glyphs for BOTH White and Black pieces.
# Hollow outline glyphs (like ♙, ♘) in Windows fonts:
# - Render as dark/muddy emoji-style glyphs where white pawns look black/grey
# - Have irregular font advance widths that overflow the square borders
# With solid filled glyphs, 'bold bright_white' renders brilliant solid white,
# and 'bold #101010' renders deep solid black.
_PIECE_SYMBOLS = {
    chess.KING: "♚",
    chess.QUEEN: "♛",
    chess.ROOK: "♜",
    chess.BISHOP: "♝",
    chess.KNIGHT: "♞",
    chess.PAWN: "♟",
}

# Refined wood palette tuned for high contrast with both white and black pieces
_LIGHT_SQ = "#b5936e"        # Warm golden oak (high contrast against white and black)
_DARK_SQ = "#80522c"         # Rich walnut (high contrast against white and black)
_EMPTY_LIGHT = "#9c7c58"     # Subtle wood dot on light square
_EMPTY_DARK = "#5e381b"      # Subtle wood dot on dark square
_HIGHLIGHT = "#7aa832"       # Last-move highlight (vibrant moss olive)
_CHECK_SQ = "#dc2626"        # King in check highlight (crimson red)



class LiveGameDisplay:
    """Manages an in-place updating chess board in the terminal.

    When the game is active, moves update in-place without scrolling.
    When the game finishes, it freezes the final board and prints it
    permanently so each game's outcome remains visible in the terminal.
    """

    def __init__(
        self,
        white_name: str,
        black_name: str,
        game_id: str = "",
        move_delay: float = 0.15,
        console: Optional[Console] = None,
    ) -> None:
        self.white_name = white_name
        self.black_name = black_name
        self.game_id = game_id
        self.move_delay = move_delay

        self._console = console or Console(color_system="truecolor", force_terminal=True)
        self._live: Optional[Live] = None
        self._captured_white: list[str] = []
        self._captured_black: list[str] = []
        self._last_from: Optional[int] = None
        self._last_to: Optional[int] = None
        self._final_status: Optional[str] = None
        self._winner: Optional[str] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> None:
        """Start the live updating display for this game."""
        self._live = Live(
            "",
            console=self._console,
            auto_refresh=False,
            transient=True,
        )
        self._live.start()

    def stop(self) -> None:
        """Clean up the live display."""
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    # ── Main update ──────────────────────────────────────────────────────
    def update(
        self,
        board: BoardState,
        last_result: Optional[MoveResult],
        ply: int,
        san_history: list[str],
    ) -> None:
        """Redraw the board in place with the current position."""
        if self._live is None:
            return

        # Track the last move squares for highlighting
        if last_result and last_result.move_uci and len(last_result.move_uci) >= 4:
            try:
                self._last_from = chess.parse_square(last_result.move_uci[:2])
                self._last_to = chess.parse_square(last_result.move_uci[2:4])
            except ValueError:
                self._last_from = self._last_to = None
        else:
            self._last_from = self._last_to = None

        self._track_captures(board)

        panel = self._build_display(board, last_result, ply, san_history)
        self._live.update(panel, refresh=True)

        if self.move_delay > 0:
            time.sleep(self.move_delay)

    def show_result(
        self,
        board: BoardState,
        termination: str,
        winner: Optional[str],
        ply: int,
        san_history: list[str],
        pause_seconds: float = 2.5,
    ) -> None:
        """Display the final game position, victory banner, and freeze permanently.

        1. Shows the final position on the live screen with victory banner.
        2. Pauses so the user can see the pieces and the outcome.
        3. Stops the live context.
        4. Permanently prints the final board panel to terminal history so
           each game stays visible as subsequent games are played.
        """
        self._final_status = termination
        self._winner = winner

        final_panel = self._build_display(board, None, ply, san_history)

        if self._live is not None:
            self._live.update(final_panel, refresh=True)
            if pause_seconds > 0:
                time.sleep(pause_seconds)
            self.stop()

        # Permanently print the final board for this game
        self._console.print(final_panel)

    # ── Renderable Construction ──────────────────────────────────────────
    def _build_display(
        self,
        board: BoardState,
        last_result: Optional[MoveResult],
        ply: int,
        san_history: list[str],
    ) -> Panel:
        """Build the compact 3-column dashboard (78 cols wide, 12 lines tall)."""
        inner_board = board.inner

        # ── 1. Board Table (Width: 27, Height: 9 lines) ───────────────
        board_table = Table(
            show_header=False,
            show_edge=False,
            show_lines=False,
            padding=(0, 0),
            box=None,
        )
        board_table.add_column(width=3, justify="center")
        for _ in range(8):
            board_table.add_column(width=3, justify="center")

        in_check = inner_board.is_check()

        for rank in range(7, -1, -1):
            row: list[Text] = [Text(f" {rank + 1} ", style="bold dim")]
            for file in range(8):
                sq = chess.square(file, rank)
                piece = inner_board.piece_at(sq)
                is_light = (rank + file) % 2 != 0

                is_hl = (sq == self._last_from or sq == self._last_to)
                is_check_king = (
                    in_check
                    and piece
                    and piece.piece_type == chess.KING
                    and piece.color == inner_board.turn
                )

                if piece:
                    char = _PIECE_SYMBOLS.get(piece.piece_type, "?")
                    if piece.color == chess.WHITE:
                        if is_check_king:
                            fg, bg = "#ffffff", "#ef4444"
                        elif is_hl:
                            fg, bg = "#14532d", "#bef264"
                        else:
                            fg, bg = "#1c1917", "#f5f5f4"
                    else:
                        if is_check_king:
                            fg, bg = "#fca5a5", "#7f1d1d"
                        elif is_hl:
                            fg, bg = "#bef264", "#14532d"
                        else:
                            fg, bg = "#f5f5f4", "#1c1917"
                    cell = Text(f" {char} ", style=f"bold {fg} on {bg}")
                else:
                    if is_hl:
                        cell = Text(" · ", style="bold #ffffff on #65a30d")
                    else:
                        bg = _LIGHT_SQ if is_light else _DARK_SQ
                        fg = _EMPTY_LIGHT if is_light else _EMPTY_DARK
                        cell = Text(" · ", style=f"{fg} on {bg}")

                row.append(cell)

            board_table.add_row(*row)

        # File coordinate labels (perfectly aligned with columns)
        file_labels = [Text("   ", style="dim")]
        for f in "abcdefgh":
            file_labels.append(Text(f" {f} ", style="bold dim"))
        board_table.add_row(*file_labels)

        # ── 2. Match & Players Panel (Width: 27, Height: 11 lines) ─────
        w_caps = "".join(self._captured_white) or "—"
        b_caps = "".join(self._captured_black) or "—"

        info_table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 0),
        )
        info_table.add_column(width=23, no_wrap=True)

        w_name_short = self.white_name[:12]
        b_name_short = self.black_name[:12]
        # Use clean 1-cell chess king glyphs instead of wide 3D emojis
        info_table.add_row(Text(f" ♔ White: {w_name_short}", style="bold #ffffff"))
        info_table.add_row(Text(f"   Caps: {w_caps[:12]}", style="dim"))
        info_table.add_row(Text(f" ♚ Black: {b_name_short}", style="bold #d0d0d0"))
        info_table.add_row(Text(f"   Caps: {b_caps[:12]}", style="dim"))
        info_table.add_row(Text(" ─────────────────────", style="dim"))

        move_num = (ply // 2) + 1
        active_color = "White" if inner_board.turn == chess.WHITE else "Black"

        if self._final_status:
            term_clean = self._final_status
            if term_clean.startswith("DRAW (") and term_clean.endswith(")"):
                term_clean = term_clean[6:-1]

            if self._winner:
                info_table.add_row(Text(f" 👑 {self._winner[:12]} wins!", style="bold green"))
                info_table.add_row(Text(f"    {term_clean[:18]}", style="green"))
            else:
                info_table.add_row(Text(" 🤝 Draw", style="bold yellow"))
                info_table.add_row(Text(f"    {term_clean[:18]}", style="yellow"))
            info_table.add_row(Text(f"    in {ply} plies ({move_num}m)", style="dim"))
        else:
            info_table.add_row(Text(f" ▶ Turn: {active_color} (m.{move_num})", style="bold cyan"))
            last_str = last_result.san if (last_result and last_result.san) else "—"
            info_table.add_row(Text(f" Last: {last_str}", style="cyan"))

            if in_check:
                info_table.add_row(Text(" Status: ⚡ CHECK!", style="bold red"))
            elif last_result and last_result.game_status == GameStatus.CHECKMATE:
                info_table.add_row(Text(" Status: 👑 CHECKMATE", style="bold green"))
            else:
                info_table.add_row(Text(" Status: ONGOING", style="dim"))

        info_panel = Panel(
            info_table,
            title="[bold]Match[/]",
            border_style="dim",
            box=box.ROUNDED,
            width=27,
            height=11,
        )

        # ── 3. Moves History Panel (Width: 19, Height: 11 lines) ──────
        moves_table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 0),
        )
        moves_table.add_column(width=4, justify="right")
        moves_table.add_column(width=6, justify="left")
        moves_table.add_column(width=6, justify="left")

        total_moves = len(san_history)
        start_idx = max(0, total_moves - 16)
        if start_idx % 2 != 0:
            start_idx -= 1

        displayed_count = 0
        for i in range(start_idx, total_moves, 2):
            m_num = (i // 2) + 1
            w_san = san_history[i] if i < total_moves else ""
            b_san = san_history[i + 1] if i + 1 < total_moves else ""

            w_style = "bold cyan" if i == total_moves - 1 else "white"
            b_style = "bold cyan" if i + 1 == total_moves - 1 else "dim white"

            moves_table.add_row(
                Text(f"{m_num}.", style="dim"),
                Text(f" {w_san[:5]}", style=w_style),
                Text(f" {b_san[:5]}", style=b_style),
            )
            displayed_count += 1
            if displayed_count >= 8:
                break

        if not san_history:
            moves_table.add_row(Text(""), Text(" —", style="dim italic"), Text(""))

        moves_panel = Panel(
            moves_table,
            title="[bold]Moves[/]",
            border_style="dim",
            box=box.ROUNDED,
            width=19,
            height=11,
        )

        # ── 4. Combine into 1-row dashboard table (Total: 73 cols) ────
        dash_table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=(0, 1),
        )
        dash_table.add_column(width=27)
        dash_table.add_column(width=27)
        dash_table.add_column(width=19)

        dash_table.add_row(board_table, info_panel, moves_panel)

        # ── 5. Outer master panel (Total: 78 cols) ────────────────────
        if self._final_status:
            term_clean = self._final_status
            if term_clean.startswith("DRAW (") and term_clean.endswith(")"):
                term_clean = term_clean[6:-1]

            if self._winner:
                header_title = f"[bold green]👑 {self._winner} WINS! ({term_clean})[/]"
                if self.game_id:
                    header_title += f" — [bold white]{self.game_id}[/]"
                border_style = "bold green"
            else:
                header_title = f"[bold yellow]🤝 DRAW ({term_clean})[/]"
                if self.game_id:
                    header_title += f" — [bold white]{self.game_id}[/]"
                border_style = "bold yellow"
        else:
            header_title = f"[bold cyan]♔ CHESS ARENA ♚[/]"
            if self.game_id:
                header_title += f" — [bold white]{self.game_id}[/]"
            border_style = "cyan"

        return Panel(
            dash_table,
            title=header_title,
            subtitle=f"[dim]{self.white_name} vs {self.black_name}[/]",
            border_style=border_style,
            box=box.DOUBLE_EDGE,
            padding=(0, 0),
            width=78,
        )

    # ── Capture tracking ─────────────────────────────────────────────────
    def _track_captures(self, board: BoardState) -> None:
        """Update captured-piece lists by diffing material."""
        inner = board.inner
        remaining = {chess.WHITE: [], chess.BLACK: []}

        for sq in chess.SQUARES:
            piece = inner.piece_at(sq)
            if piece:
                remaining[piece.color].append(piece.piece_type)

        full_set = [
            chess.QUEEN,
            chess.ROOK, chess.ROOK,
            chess.BISHOP, chess.BISHOP,
            chess.KNIGHT, chess.KNIGHT,
            chess.PAWN, chess.PAWN, chess.PAWN, chess.PAWN,
            chess.PAWN, chess.PAWN, chess.PAWN, chess.PAWN,
        ]

        black_remaining = list(remaining[chess.BLACK])
        black_missing = list(full_set)
        for p in black_remaining:
            if p in black_missing:
                black_missing.remove(p)
        self._captured_white = [
            _PIECE_SYMBOLS.get(p, "?") for p in sorted(black_missing, reverse=True)
        ]

        white_remaining = list(remaining[chess.WHITE])
        white_missing = list(full_set)
        for p in white_remaining:
            if p in white_missing:
                white_missing.remove(p)
        self._captured_black = [
            _PIECE_SYMBOLS.get(p, "?") for p in sorted(white_missing, reverse=True)
        ]
