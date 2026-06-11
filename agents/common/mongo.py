"""MongoDB access for the deterministic engine, gateway, and seed script.

Agent *reasoning* reads/writes go through the MongoDB MCP server (see
mcp.py) — that is the partner-track integration. This module is the plain
driver used for high-frequency telemetry (per-tick corridor state), the
gateway's change-stream watchers, and schema seeding, where an LLM tool
round-trip would add nothing.
"""

from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from agents.common import config

# Collection names — the canonical schema. surge_history is intentionally
# absent: the simulator creates it mid-run through MCP to demonstrate
# schema evolution on a live database.
RUNS = "runs"
TRANSPORT_PLANS = "transport_plans"
CORRIDOR_STATE = "corridor_state"
TICKS = "ticks"
AGENT_DECISIONS = "agent_decisions"
SURGE_ALERTS = "surge_alerts"
SURGE_HISTORY = "surge_history"  # created mid-simulation, never seeded

WATCHED_COLLECTIONS = [
    RUNS,
    TRANSPORT_PLANS,
    CORRIDOR_STATE,
    TICKS,
    AGENT_DECISIONS,
    SURGE_ALERTS,
    SURGE_HISTORY,
]


@lru_cache(maxsize=1)
def client() -> MongoClient:
    return MongoClient(config.required("MONGODB_URI"), serverSelectionTimeoutMS=10_000)


def db() -> Database:
    return client()[config.MONGODB_DB]
