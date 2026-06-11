"""KickOff gateway — one button in, one event stream out.

POST /api/launch    start a matchday run (coordinator -> planner -> simulator)
GET  /api/stream    SSE feed of MongoDB change events (the live UI signal)
GET  /api/state     snapshot for late joiners / refreshes
GET  /api/health    liveness + dependency status

The gateway is deliberately thin: agents write everything to MongoDB Atlas,
and the UI is driven by the change stream. The gateway never fabricates
simulation state.
"""

import asyncio
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from agents.common import config, mongo
from agents.common.corridors import CORRIDORS, KICKOFF_TICK, MAX_TICKS, TICK_MINUTES, TOTAL_FANS
from agents.common.dispatch import dispatch, extract_json
from gateway.hub import _jsonable, hub

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="KickOff Agent Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_active_run: dict = {"run_id": None, "task": None}


@app.on_event("startup")
async def _startup():
    hub.start(asyncio.get_running_loop())


@app.on_event("shutdown")
async def _shutdown():
    hub.stop()


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


SCENARIO_NOTES = (
    "Group-stage matchday, 82,500 sellout at MetLife Stadium. Clear evening, "
    "light wind. NJ Transit reports normal service at gates-open. Expect the "
    "usual Manhattan-side crush 60-30 minutes before kickoff."
)


async def _orchestrate(run_id: str) -> None:
    db = mongo.db()
    try:
        # 1. Coordinator -> planner over A2A: produce the transport plan.
        launch_msg = json.dumps(
            {"action": "launch", "run_id": run_id, "scenario": SCENARIO_NOTES, "attendance": TOTAL_FANS}
        )
        plan_text = await dispatch("coordinator", launch_msg)
        plan = extract_json(plan_text) or {}
        if "error" in plan or not plan.get("corridors"):
            logger.warning("planner produced no usable plan (%s); falling back to baseline", str(plan)[:200])
            plan = {"corridors": [], "narrative": "Baseline plan (planner unavailable)."}

        db[mongo.RUNS].update_one(
            {"run_id": run_id},
            {"$set": {"status": "plan_ready", "plan_narrative": plan.get("narrative", ""), "risks": plan.get("risks", [])}},
        )

        # 2. Simulator runs the matchday (engine writes every tick to Atlas).
        exec_msg = json.dumps({"action": "execute", "run_id": run_id, "plan": plan})
        await dispatch("simulator", exec_msg)
    except Exception as e:  # noqa: BLE001
        logger.exception("orchestration failed for %s", run_id)
        db[mongo.RUNS].update_one(
            {"run_id": run_id},
            {"$set": {"status": "failed", "error": str(e)[:500], "finished_at": datetime.now(timezone.utc)}},
        )


@app.post("/api/launch")
async def launch():
    if _active_run["task"] is not None and not _active_run["task"].done():
        return JSONResponse(
            {"run_id": _active_run["run_id"], "status": "already_running"},
            status_code=409,
        )

    run_id = "run-" + secrets.token_hex(3)
    mongo.db()[mongo.RUNS].insert_one(
        {
            "run_id": run_id,
            "status": "planning",
            "created_at": datetime.now(timezone.utc),
            "venue": "MetLife Stadium",
            "attendance": TOTAL_FANS,
            "kickoff_tick": KICKOFF_TICK,
            "max_ticks": MAX_TICKS,
            "tick_minutes": TICK_MINUTES,
            "agent_mode": config.AGENT_MODE,
            "autopilot": config.AUTOPILOT,
        }
    )
    task = asyncio.create_task(_orchestrate(run_id))
    _active_run.update(run_id=run_id, task=task)
    return {"run_id": run_id, "status": "planning"}


# ---------------------------------------------------------------------------
# Stream + state
# ---------------------------------------------------------------------------


@app.get("/api/stream")
async def stream(request: Request, run_id: str | None = None):
    queue = hub.subscribe()

    async def gen():
        try:
            yield {"event": "hello", "data": json.dumps({"run_id": run_id, "connected": hub.connected})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                doc = event.get("doc", {})
                if run_id and doc.get("run_id") not in (None, run_id):
                    continue
                yield {"event": "change", "data": json.dumps(event)}
        finally:
            hub.unsubscribe(queue)

    return EventSourceResponse(gen())


@app.get("/api/state")
async def state(run_id: str | None = None):
    db = mongo.db()
    if run_id is None:
        latest = db[mongo.RUNS].find_one(sort=[("created_at", -1)])
        run_id = latest["run_id"] if latest else None
    if run_id is None:
        return {"run": None}

    run = db[mongo.RUNS].find_one({"run_id": run_id}, {"_id": 0})
    corridors = list(db[mongo.CORRIDOR_STATE].find({"run_id": run_id}, {"_id": 0}))
    last_tick = db[mongo.TICKS].find_one({"run_id": run_id}, {"_id": 0}, sort=[("tick", -1)])
    decisions = list(db[mongo.AGENT_DECISIONS].find({"run_id": run_id}, {"_id": 0}).sort("ts", -1).limit(30))
    alerts = list(db[mongo.SURGE_ALERTS].find({"run_id": run_id}, {"_id": 0}).sort("ts", -1).limit(20))
    plan = db[mongo.TRANSPORT_PLANS].find_one({"run_id": run_id}, {"_id": 0})
    return _jsonable(
        {
            "run": run,
            "corridors": corridors,
            "last_tick": last_tick,
            "decisions": decisions,
            "alerts": alerts,
            "plan": plan,
        }
    )


@app.get("/api/config")
async def get_config():
    return {
        "corridors": CORRIDORS,
        "fans_total": TOTAL_FANS,
        "kickoff_tick": KICKOFF_TICK,
        "max_ticks": MAX_TICKS,
        "tick_minutes": TICK_MINUTES,
        "agent_mode": config.AGENT_MODE,
        "autopilot": config.AUTOPILOT,
    }


@app.get("/api/health")
async def health():
    try:
        mongo.client().admin.command("ping")
        atlas = "ok"
    except Exception as e:  # noqa: BLE001
        atlas = f"down: {str(e)[:80]}"
    return {"status": "ok", "atlas": atlas, "change_stream": hub.connected, "agent_mode": config.AGENT_MODE}


# ---------------------------------------------------------------------------
# Static frontend (built by `make build` into gateway/static)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")
