"""Seed the KickOff Atlas database: collections, indexes, baseline plan.

Run once after creating the cluster:  make seed

Deliberately does NOT create surge_history — the simulator creates that
collection live, mid-run, through the MongoDB MCP server to demonstrate
schema evolution on a running system.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.common import mongo
from agents.common.corridors import CORRIDORS, KICKOFF_TICK, MAX_TICKS, TICK_MINUTES, TOTAL_FANS


def seed() -> None:
    db = mongo.db()
    existing = set(db.list_collection_names())

    for name in [
        mongo.RUNS,
        mongo.TRANSPORT_PLANS,
        mongo.CORRIDOR_STATE,
        mongo.TICKS,
        mongo.AGENT_DECISIONS,
        mongo.SURGE_ALERTS,
    ]:
        if name not in existing:
            db.create_collection(name)
            print(f"  created collection {name}")

    db[mongo.CORRIDOR_STATE].create_index([("run_id", 1), ("corridor_id", 1)], unique=True)
    db[mongo.TICKS].create_index([("run_id", 1), ("tick", 1)], unique=True)
    db[mongo.AGENT_DECISIONS].create_index([("run_id", 1), ("tick", 1)])
    db[mongo.SURGE_ALERTS].create_index([("run_id", 1), ("corridor_id", 1), ("status", 1)])
    print("  indexes ensured")

    # Baseline plan template the planner agent reads as its starting point.
    db[mongo.TRANSPORT_PLANS].update_one(
        {"plan_id": "baseline"},
        {
            "$set": {
                "plan_id": "baseline",
                "kind": "template",
                "venue": "MetLife Stadium, East Rutherford NJ",
                "event": "FIFA World Cup 2026",
                "attendance": TOTAL_FANS,
                "tick_minutes": TICK_MINUTES,
                "kickoff_tick": KICKOFF_TICK,
                "max_ticks": MAX_TICKS,
                "corridors": CORRIDORS,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    print("  baseline transport plan upserted")
    print("Seed complete.")


if __name__ == "__main__":
    seed()
