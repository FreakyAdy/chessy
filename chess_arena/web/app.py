"""
app.py — FastAPI Web Application & API Endpoints for Chess Arena
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chess_arena.arena.validator import ModelAuditor, load_agent_class
from chess_arena.web.tournament_bridge import TournamentBridge

app = FastAPI(title="Chess Arena Live Web UI", version="1.0.0")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PROJECT_ROOT = BASE_DIR.parent.parent
UPLOAD_DIR = PROJECT_ROOT / "uploaded_agents"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Shared Tournament Bridge
bridge = TournamentBridge()

# Built-in agent roster definitions
BUILTIN_AGENTS = [
    {
        "id": "greedy",
        "name": "GreedyBot",
        "module": "chess_arena.agents.greedy_agent",
        "class": "GreedyAgent",
        "type": "heuristic",
        "description": "Material capture maximizer (Q=9, R=5, B=3, N=3, P=1)",
        "is_uploaded": False,
        "is_eligible": True,
        "score": 95,
    },
    {
        "id": "minimax_d2",
        "name": "Minimax-d2",
        "module": "chess_arena.agents.minimax_agent",
        "class": "MinimaxAgent",
        "type": "search",
        "description": "Depth-2 Minimax with Alpha-Beta pruning & piece-square tables",
        "is_uploaded": False,
        "is_eligible": True,
        "score": 98,
        "config": {"depth": 2},
    },
    {
        "id": "center_control",
        "name": "CenterControlBot",
        "module": "chess_arena.agents.center_control_agent",
        "class": "CenterControlAgent",
        "type": "heuristic",
        "description": "Positional heuristic prioritizing center occupation (e4, d4, e5, d5)",
        "is_uploaded": False,
        "is_eligible": True,
        "score": 93,
    },
    {
        "id": "random",
        "name": "RandomBot",
        "module": "chess_arena.agents.random_agent",
        "class": "RandomAgent",
        "type": "baseline",
        "description": "Uniform random legal move selector (control baseline)",
        "is_uploaded": False,
        "is_eligible": True,
        "score": 90,
    },
]


@app.get("/")
async def root():
    """Serve the single-page application."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    return FileResponse(str(index_path))


@app.get("/api/bots")
async def list_bots():
    """List all available bots (built-in + uploaded community models)."""
    bots = list(BUILTIN_AGENTS)

    # Scan uploaded_agents/
    uploaded_files = glob.glob(str(UPLOAD_DIR / "*.py"))
    for file_path in uploaded_files:
        basename = os.path.basename(file_path)
        if basename == "__init__.py":
            continue

        bot_id = f"uploaded_{Path(file_path).stem}"
        name = Path(file_path).stem.replace("_", " ").title()

        # Audit check / cache
        try:
            auditor = ModelAuditor(time_limit=1.0)
            report = auditor.audit(file_path, display_progress=False)
            is_eligible = report.is_eligible
            score = report.score
            class_name = report.class_name
        except Exception:
            is_eligible = False
            score = 0
            class_name = "Unknown"

        bots.append({
            "id": bot_id,
            "name": name,
            "module": str(file_path),
            "class": class_name,
            "type": "community",
            "description": f"Uploaded custom model from {basename}",
            "is_uploaded": True,
            "is_eligible": is_eligible,
            "score": score,
            "filename": basename,
        })

    return {"bots": bots}


@app.post("/api/upload")
async def upload_bot(file: UploadFile = File(...)):
    """Upload a candidate .py agent file and immediately run the eligibility audit."""
    if not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py Python agent files are supported.")

    # Limit to maximum 5 uploaded custom bots
    existing_uploads = [
        f for f in glob.glob(str(UPLOAD_DIR / "*.py"))
        if os.path.basename(f) != "template_agent.py" and os.path.basename(f) != "__init__.py"
    ]
    if len(existing_uploads) >= 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum of 5 custom uploaded bots reached. Please delete an existing bot to upload a new one.",
        )

    # Save file to uploaded_agents/
    safe_filename = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    target_path = UPLOAD_DIR / safe_filename

    with open(target_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Run ModelAuditor
    auditor = ModelAuditor(time_limit=5.0)
    report = auditor.audit(str(target_path), display_progress=False)

    return {
        "filename": safe_filename,
        "path": str(target_path),
        "is_eligible": report.is_eligible,
        "score": report.score,
        "passed_checks": report.passed_checks,
        "total_checks": report.total_checks,
        "class_name": report.class_name,
        "critical_findings": report.critical_issues,
        "warnings": report.warnings,
        "latency": {
            "avg_ms": round(report.latency.avg_ms, 2),
            "p95_ms": round(report.latency.p95_ms, 2),
            "max_ms": round(report.latency.max_ms, 2),
        },
        "bot": {
            "id": f"uploaded_{target_path.stem}",
            "name": target_path.stem.replace("_", " ").title(),
            "module": str(target_path),
            "class": report.class_name,
            "type": "community",
            "is_uploaded": True,
            "is_eligible": report.is_eligible,
            "score": report.score,
        },
    }


@app.post("/api/audit")
async def audit_bot(data: Dict[str, Any]):
    """Run full qualification audit on any specified source or file."""
    source = data.get("source")
    if not source:
        raise HTTPException(status_code=400, detail="Missing 'source' parameter.")

    auditor = ModelAuditor(time_limit=float(data.get("time_limit", 5.0)))
    report = auditor.audit(source, class_name=data.get("class_name"), display_progress=False)

    return {
        "source": source,
        "model_name": report.model_name,
        "class_name": report.class_name,
        "is_eligible": report.is_eligible,
        "score": report.score,
        "passed_checks": report.passed_checks,
        "total_checks": report.total_checks,
        "critical_issues": report.critical_issues,
        "warnings": report.warnings,
        "benchmark_details": report.benchmark_details,
        "latency": {
            "avg_ms": round(report.latency.avg_ms, 2),
            "p95_ms": round(report.latency.p95_ms, 2),
            "max_ms": round(report.latency.max_ms, 2),
        },
    }


class TournamentStartRequest(BaseModel):
    bot_ids: List[str]
    format: str = "round_robin"
    games_per_pair: int = 2
    time_limit: float = 5.0
    move_delay: float = 0.25


@app.post("/api/tournament/start")
async def start_tournament(req: TournamentStartRequest):
    """Launch tournament with the chosen 2-5 bots."""
    if len(req.bot_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 bots must be selected to start a tournament.")
    if len(req.bot_ids) > 5:
        raise HTTPException(status_code=400, detail="Maximum of 5 bots allowed in the tournament.")

    # Resolve bot configurations
    all_bots = (await list_bots())["bots"]
    bot_map = {b["id"]: b for b in all_bots}

    selected_configs = []
    for bid in req.bot_ids:
        if bid not in bot_map:
            raise HTTPException(status_code=404, detail=f"Bot with id '{bid}' not found.")
        b = bot_map[bid]
        if not b["is_eligible"]:
            raise HTTPException(
                status_code=400,
                detail=f"Bot '{b['name']}' is not eligible. Please run audit and resolve rule violations first.",
            )
        selected_configs.append({
            "name": b["name"],
            "module": b["module"],
            "class": b["class"],
            "config": b.get("config", {}),
        })

    bridge.set_speed(req.move_delay)
    success = bridge.start_tournament(
        bot_configs=selected_configs,
        tournament_format=req.format,
        games_per_pair=req.games_per_pair,
        time_limit=req.time_limit,
    )

    if not success:
        raise HTTPException(status_code=409, detail="A tournament is already running. Stop it first.")

    return {"status": "started", "matches": bridge.total_matches, "bots": [b["name"] for b in selected_configs]}


@app.post("/api/tournament/pause")
async def pause_tournament():
    bridge.pause()
    return {"status": "paused"}


@app.post("/api/tournament/resume")
async def resume_tournament():
    bridge.resume()
    return {"status": "resumed"}


class SpeedRequest(BaseModel):
    delay: float


@app.post("/api/tournament/speed")
async def set_speed(req: SpeedRequest):
    bridge.set_speed(req.delay)
    return {"status": "speed_updated", "delay": bridge.move_delay}


@app.post("/api/tournament/stop")
async def stop_tournament():
    await bridge.stop()
    return {"status": "stopped"}


@app.get("/api/state")
async def get_state():
    return bridge.get_state_snapshot()


@app.get("/api/pgn/{match_number}")
async def get_pgn(match_number: int):
    """Retrieve PGN string for a match."""
    if match_number not in bridge.pgn_records:
        raise HTTPException(status_code=404, detail="PGN for this match not found.")
    return PlainTextResponse(
        bridge.pgn_records[match_number],
        media_type="application/x-chess-pgn",
        headers={"Content-Disposition": f"attachment; filename=game_{match_number:04d}.pgn"},
    )


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time live streaming of moves, clocks, FEN, and tournament standings."""
    await websocket.accept()
    q = bridge.register_listener()

    try:
        # Send initial snapshot immediately upon connection
        await websocket.send_json({
            "type": "state_snapshot",
            "data": bridge.get_state_snapshot(),
        })

        while True:
            payload = await q.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        bridge.unregister_listener(q)
