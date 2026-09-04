"""
adapter.py — ChessAgent Base Class & Subprocess Wrapper
════════════════════════════════════════════════════════

Defines the interface every competing agent must implement and a
subprocess-based executor that enforces time limits and isolation.
"""

from __future__ import annotations

import importlib
import importlib.util
import multiprocessing
import multiprocessing.queues
import os
import queue
import sys
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


# ═════════════════════════════════════════════════════════════════════════════
#  Agent Interface
# ═════════════════════════════════════════════════════════════════════════════

class ChessAgent(ABC):
    """Base class that every competing chess agent **must** subclass.

    Only one method needs to be implemented: :pymeth:`get_move`.

    Example
    -------
    >>> class MyAgent(ChessAgent):
    ...     def get_move(self, fen, legal_moves):
    ...         return legal_moves[0]       # always pick the first legal move
    """

    def __init__(self, name: str, config: dict) -> None:
        """Initialise the agent.

        Parameters
        ----------
        name:
            Human-readable display name (used in PGN headers / leaderboard).
        config:
            Arbitrary configuration dictionary forwarded from ``config.yaml``.
        """
        self.name = name
        self.config = config

    @abstractmethod
    def get_move(self, fen: str, legal_moves: list[str]) -> str:
        """Choose a move.

        Parameters
        ----------
        fen:
            Current board position in Forsyth–Edwards Notation.
        legal_moves:
            Every legal move in UCI format for the side to move.

        Returns
        -------
        str
            Exactly ONE move in UCI format that appears in *legal_moves*.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


# ═════════════════════════════════════════════════════════════════════════════
#  Subprocess isolation wrapper
# ═════════════════════════════════════════════════════════════════════════════

def _agent_worker(
    module_path: str,
    class_name: str,
    agent_name: str,
    agent_config: dict,
    request_queue: multiprocessing.Queue,
    response_queue: multiprocessing.Queue,
) -> None:
    """Target function running in a child process.

    Instantiates the agent **once**, then loops:
      1. Read ``(fen, legal_moves)`` from *request_queue*.
      2. Call ``agent.get_move(fen, legal_moves)``.
      3. Put the result (or an error) onto *response_queue*.

    The sentinel value ``None`` on the request queue signals shutdown.
    """
    try:
        if os.path.exists(module_path) and os.path.isfile(module_path):
            dir_name = os.path.dirname(os.path.abspath(module_path))
            if dir_name not in sys.path:
                sys.path.insert(0, dir_name)
            mod_name = os.path.splitext(os.path.basename(module_path))[0]
            spec = importlib.util.spec_from_file_location(mod_name, os.path.abspath(module_path))
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load module spec from file: {module_path}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        else:
            mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        agent: ChessAgent = cls(name=agent_name, config=agent_config)
    except Exception:
        response_queue.put(("INIT_ERROR", traceback.format_exc()))
        return

    response_queue.put(("READY", None))

    while True:
        item = request_queue.get()
        if item is None:                    # shutdown sentinel
            break
        fen, legal_moves = item
        try:
            move = agent.get_move(fen, legal_moves)
            response_queue.put(("MOVE", move))
        except Exception:
            response_queue.put(("ERROR", traceback.format_exc()))


@dataclass
class AgentProcess:
    """Manages a child process running a single :pyclass:`ChessAgent`.

    Usage
    -----
    >>> ap = AgentProcess.spawn("agents.random_agent", "RandomAgent", "Bot", {})
    >>> move = ap.request_move(fen, legal_moves, timeout=5.0)
    >>> ap.shutdown()
    """

    name: str
    module_path: str
    class_name: str
    config: dict
    _process: Optional[multiprocessing.Process] = None
    _req_q: Optional[multiprocessing.Queue] = None
    _res_q: Optional[multiprocessing.Queue] = None

    # ── Factory ──────────────────────────────────────────────────────────
    @classmethod
    def spawn(
        cls,
        module_path: str,
        class_name: str,
        name: str,
        config: dict,
    ) -> "AgentProcess":
        """Create and start the child process.

        Raises ``RuntimeError`` if the agent fails to initialise.
        """
        req_q: multiprocessing.Queue = multiprocessing.Queue()
        res_q: multiprocessing.Queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target=_agent_worker,
            args=(module_path, class_name, name, config, req_q, res_q),
            daemon=True,
        )
        proc.start()

        # Wait for READY or INIT_ERROR
        try:
            tag, payload = res_q.get(timeout=30)
        except queue.Empty:
            proc.terminate()
            raise RuntimeError(
                f"Agent '{name}' ({module_path}.{class_name}) "
                "did not respond within 30 s during initialisation."
            )

        if tag == "INIT_ERROR":
            proc.terminate()
            raise RuntimeError(
                f"Agent '{name}' failed to initialise:\n{payload}"
            )

        ap = cls(
            name=name,
            module_path=module_path,
            class_name=class_name,
            config=config,
            _process=proc,
            _req_q=req_q,
            _res_q=res_q,
        )
        return ap

    # ── Public API ───────────────────────────────────────────────────────
    def request_move(
        self,
        fen: str,
        legal_moves: list[str],
        timeout: float = 5.0,
    ) -> str:
        """Send a position to the agent and wait for a move.

        Returns the UCI move string.

        Raises
        ------
        TimeoutError
            If the agent does not respond within *timeout* seconds.
        RuntimeError
            If the agent crashes or returns an error.
        """
        if self._req_q is None or self._res_q is None:
            raise RuntimeError("Agent process is not running.")

        self._req_q.put((fen, legal_moves))

        try:
            tag, payload = self._res_q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"Agent '{self.name}' timed out after {timeout:.1f}s."
            )

        if tag == "ERROR":
            raise RuntimeError(
                f"Agent '{self.name}' raised an exception:\n{payload}"
            )
        return payload  # the UCI move string

    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._process.is_alive()

    def shutdown(self) -> None:
        """Gracefully stop the child process."""
        if self._req_q is not None:
            try:
                self._req_q.put(None)  # sentinel
            except Exception:
                pass
        if self._process is not None and self._process.is_alive():
            self._process.join(timeout=5)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2)

    def __repr__(self) -> str:
        alive = self.is_alive()
        return (
            f"AgentProcess(name={self.name!r}, alive={alive})"
        )

    def __del__(self) -> None:
        self.shutdown()


# ═════════════════════════════════════════════════════════════════════════════
#  In-process adapter (used for testing / when isolation isn't needed)
# ═════════════════════════════════════════════════════════════════════════════

class InProcessAgent:
    """Wraps a :pyclass:`ChessAgent` instance so it exposes the same
    ``request_move`` / ``shutdown`` API as :pyclass:`AgentProcess`,
    but runs in the calling process (handy for unit tests and debugging).
    """

    def __init__(self, agent: ChessAgent) -> None:
        self._agent = agent
        self.name = agent.name

    def request_move(
        self,
        fen: str,
        legal_moves: list[str],
        timeout: float = 5.0,
    ) -> str:
        return self._agent.get_move(fen, legal_moves)

    def is_alive(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"InProcessAgent(name={self.name!r})"
