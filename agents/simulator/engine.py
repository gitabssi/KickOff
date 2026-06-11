"""The matchday engine — deterministic fan-flow physics for MetLife Stadium.

The engine advances one tick at a time (1 tick = 2 simulated minutes,
~1.2 real seconds), moving 82,500 fans through four transport corridors:

  demand curve -> origin queues -> corridor departures -> in-transit -> stadium

Every tick it persists corridor_state and a tick snapshot to MongoDB Atlas;
the gateway's change-stream watcher turns those writes into the live UI.

The engine is deliberately deterministic (the Race Condition keynote repo
calls this the autopilot pattern): LLM reasoning happens *around* the
physics, not inside it. Concierge and coordinator agents are dispatched
asynchronously — their decisions land whenever the model answers and take
effect on the next tick, so the animation never stalls on an LLM call.
"""

import asyncio
import logging
import math
from datetime import datetime, timezone

from agents.common import mongo
from agents.common.corridors import (
    CORRIDORS,
    CRITICAL_QUEUE_RATIO,
    INCIDENTS,
    KICKOFF_TICK,
    MAX_TICKS,
    SURGE_CLEAR_RATIO,
    SURGE_QUEUE_RATIO,
    TICK_MINUTES,
    TOTAL_FANS,
)

logger = logging.getLogger(__name__)

TICK_REAL_SECONDS = 1.2
CONCIERGE_ROUND_INTERVAL = 12  # ticks between scheduled concierge rounds
DEMAND_PEAK_TICK = 50
DEMAND_SIGMA = 26.0
MAX_BOOST = 1.6
MIN_SHARE = 0.02


def _now():
    return datetime.now(timezone.utc)


def demand_at(tick: int) -> float:
    """Fan arrivals into the transport network at a tick (gaussian curve,
    normalized so the area over ticks 1..KICKOFF_TICK is TOTAL_FANS)."""
    if tick < 1 or tick > KICKOFF_TICK:
        return 0.0
    norm = sum(
        math.exp(-((t - DEMAND_PEAK_TICK) ** 2) / (2 * DEMAND_SIGMA**2))
        for t in range(1, KICKOFF_TICK + 1)
    )
    weight = math.exp(-((tick - DEMAND_PEAK_TICK) ** 2) / (2 * DEMAND_SIGMA**2))
    return TOTAL_FANS * weight / norm


class CorridorSim:
    def __init__(self, spec: dict):
        self.spec = spec
        self.id = spec["corridor_id"]
        self.base_capacity = spec["capacity_per_tick"]
        self.share = spec["preference_share"]
        self.transit_ticks = spec["transit_ticks"]
        self.queued = 0.0
        self.delivered = 0.0
        self.arrived_total = 0.0
        self.in_transit: dict[int, float] = {}  # arrival_tick -> fans
        self.boost = 1.0
        self.incident_factor = 1.0
        self.incident_note = ""
        self.status = "ok"
        self.surge_id: str | None = None
        self.surge_started_tick: int | None = None
        self.coordinator_called = False
        self.last_departed = 0.0

    @property
    def capacity_now(self) -> float:
        return self.base_capacity * self.boost * self.incident_factor

    @property
    def in_transit_total(self) -> float:
        return sum(self.in_transit.values())

    def queue_ratio(self) -> float:
        cap = max(self.capacity_now, 1.0)
        return self.queued / cap


class MatchdayEngine:
    """One instance per simulation run."""

    def __init__(
        self,
        run_id: str,
        plan: dict | None = None,
        dispatcher=None,
        pace: float = TICK_REAL_SECONDS,
        persist: bool = True,
    ):
        self.run_id = run_id
        self.tick = 0
        self.pace = pace
        self.persist = persist
        self.corridors = {c["corridor_id"]: CorridorSim(c) for c in CORRIDORS}
        self._apply_plan(plan or {})
        # dispatcher(kind, payload) -> coroutine; wired by the simulator agent
        # to fire concierge/coordinator agents. None = pure physics (tests).
        self.dispatcher = dispatcher
        self.pending_effects: list[dict] = []
        self.background_tasks: set[asyncio.Task] = set()
        self.surge_history_created = False
        self.db = mongo.db() if persist else None

    # ------------------------------------------------------------------
    # Plan + effects
    # ------------------------------------------------------------------

    def _apply_plan(self, plan: dict) -> None:
        """Apply planner output: per-corridor share and capacity overrides."""
        for c in plan.get("corridors", []):
            sim = self.corridors.get(c.get("corridor_id"))
            if not sim:
                continue
            if isinstance(c.get("preference_share"), (int, float)):
                sim.share = max(MIN_SHARE, float(c["preference_share"]))
            if isinstance(c.get("capacity_per_tick"), (int, float)):
                sim.base_capacity = float(c["capacity_per_tick"])
        self._normalize_shares()

    def _normalize_shares(self) -> None:
        total = sum(c.share for c in self.corridors.values())
        for c in self.corridors.values():
            c.share = c.share / total

    def queue_effect(self, effect: dict) -> None:
        """Called from agent-completion callbacks; consumed on next tick."""
        self.pending_effects.append(effect)

    def _apply_effects(self) -> list[dict]:
        applied = []
        effects, self.pending_effects = self.pending_effects, []
        for e in effects:
            action = e.get("action")
            cid = e.get("corridor_id")
            sim = self.corridors.get(cid)
            try:
                if action == "boost_capacity" and sim:
                    magnitude = min(0.5, max(0.05, float(e.get("magnitude", 0.2))))
                    sim.boost = min(MAX_BOOST, sim.boost + magnitude)
                    applied.append(e)
                elif action == "divert" and sim:
                    target = self.corridors.get(e.get("divert_to", ""))
                    magnitude = min(0.2, max(0.02, float(e.get("magnitude", 0.1))))
                    if target and sim.share - magnitude >= MIN_SHARE:
                        sim.share -= magnitude
                        target.share += magnitude
                        self._normalize_shares()
                        applied.append(e)
                elif action in ("hold", "advise"):
                    applied.append(e)
            except (TypeError, ValueError) as err:
                logger.warning("bad effect %s: %s", e, err)
        return applied

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    def _advance_physics(self) -> None:
        demand = demand_at(self.tick)
        for sim in self.corridors.values():
            arrivals = demand * sim.share
            sim.queued += arrivals
            sim.arrived_total += arrivals

            departed = min(sim.queued, sim.capacity_now)
            sim.queued -= departed
            sim.last_departed = departed
            if departed > 0:
                eta = self.tick + sim.transit_ticks
                sim.in_transit[eta] = sim.in_transit.get(eta, 0.0) + departed

            landed = sim.in_transit.pop(self.tick, 0.0)
            sim.delivered += landed

    def _apply_incidents(self) -> list[dict]:
        fired = []
        for inc in INCIDENTS:
            sim = self.corridors[inc["corridor_id"]]
            if self.tick == inc["tick"]:
                sim.incident_factor = inc["capacity_factor"]
                sim.incident_note = inc["headline"]
                fired.append(inc)
            elif self.tick == inc["tick"] + inc["duration_ticks"]:
                sim.incident_factor = 1.0
                sim.incident_note = ""
        return fired

    def _update_surge_states(self) -> list[dict]:
        """Surge lifecycle per corridor. Returns surge events for dispatch."""
        events = []
        for sim in self.corridors.values():
            ratio = sim.queue_ratio()
            if sim.surge_id is None and ratio >= SURGE_QUEUE_RATIO:
                sim.surge_id = f"{self.run_id}-{sim.id}-t{self.tick}"
                sim.surge_started_tick = self.tick
                sim.coordinator_called = False
                sim.status = "surge"
                events.append({"kind": "surge_start", "corridor": sim, "ratio": ratio})
            elif sim.surge_id is not None:
                if ratio >= CRITICAL_QUEUE_RATIO and sim.status != "critical":
                    sim.status = "critical"
                    events.append({"kind": "surge_critical", "corridor": sim, "ratio": ratio})
                elif ratio <= SURGE_CLEAR_RATIO:
                    events.append({"kind": "surge_resolved", "corridor": sim, "ratio": ratio})
                    sim.surge_id = None
                    sim.surge_started_tick = None
                    sim.status = "ok"
            if sim.surge_id is None:
                sim.status = "busy" if ratio > 1.5 else "ok"
        return events

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _corridor_doc(self, sim: CorridorSim) -> dict:
        return {
            "run_id": self.run_id,
            "corridor_id": sim.id,
            "name": sim.spec["name"],
            "origin": sim.spec["origin"],
            "mode": sim.spec["mode"],
            "color": sim.spec["color"],
            "tick": self.tick,
            "queued": round(sim.queued),
            "in_transit": round(sim.in_transit_total),
            "delivered": round(sim.delivered),
            "arrived_total": round(sim.arrived_total),
            "capacity_per_tick": round(sim.capacity_now),
            "base_capacity": round(sim.base_capacity),
            "boost": round(sim.boost, 2),
            "share": round(sim.share, 3),
            "flow": round(sim.last_departed),
            "utilization": round(min(sim.last_departed / max(sim.capacity_now, 1.0), 1.0), 3),
            "queue_ratio": round(sim.queue_ratio(), 2),
            "status": sim.status,
            "incident": sim.incident_note,
            "updated_at": _now(),
        }

    def _persist_tick(self) -> None:
        if self.db is None:
            return
        for sim in self.corridors.values():
            self.db[mongo.CORRIDOR_STATE].update_one(
                {"run_id": self.run_id, "corridor_id": sim.id},
                {"$set": self._corridor_doc(sim)},
                upsert=True,
            )
        delivered = sum(c.delivered for c in self.corridors.values())
        queued = sum(c.queued for c in self.corridors.values())
        in_transit = sum(c.in_transit_total for c in self.corridors.values())
        self.db[mongo.TICKS].update_one(
            {"run_id": self.run_id, "tick": self.tick},
            {
                "$set": {
                    "run_id": self.run_id,
                    "tick": self.tick,
                    "t_minus_minutes": (KICKOFF_TICK - self.tick) * TICK_MINUTES,
                    "phase": self._phase(),
                    "demand": round(demand_at(self.tick)),
                    "delivered_total": round(delivered),
                    "queued_total": round(queued),
                    "in_transit_total": round(in_transit),
                    "fans_total": TOTAL_FANS,
                    "ts": _now(),
                }
            },
            upsert=True,
        )

    def _phase(self) -> str:
        if self.tick < 25:
            return "early_arrivals"
        if self.tick < 45:
            return "building"
        if self.tick < 75:
            return "peak_crush"
        if self.tick < KICKOFF_TICK:
            return "final_approach"
        return "kickoff"

    def _record_surge_alert(self, event: dict) -> dict:
        sim: CorridorSim = event["corridor"]
        severity = "critical" if event["kind"] == "surge_critical" else "warning"
        doc = {
            "run_id": self.run_id,
            "surge_id": sim.surge_id or f"{self.run_id}-{sim.id}-resolved",
            "corridor_id": sim.id,
            "corridor_name": sim.spec["name"],
            "tick": self.tick,
            "severity": severity,
            "queue_ratio": round(event["ratio"], 2),
            "queued": round(sim.queued),
            "status": "resolved" if event["kind"] == "surge_resolved" else "active",
            "message": self._surge_message(event),
            "ts": _now(),
        }
        if self.db is None:
            return doc
        if event["kind"] == "surge_start":
            self.db[mongo.SURGE_ALERTS].insert_one(dict(doc))
        else:
            self.db[mongo.SURGE_ALERTS].update_one(
                {"run_id": self.run_id, "surge_id": doc["surge_id"]},
                {"$set": doc},
                upsert=True,
            )
        # Append a reading to surge_history if the coordinator has created it.
        if self.surge_history_created and event["kind"] != "surge_resolved":
            self.db[mongo.SURGE_HISTORY].update_one(
                {"run_id": self.run_id, "surge_id": doc["surge_id"]},
                {
                    "$setOnInsert": {
                        "run_id": self.run_id,
                        "surge_id": doc["surge_id"],
                        "corridor_id": sim.id,
                        "started_tick": sim.surge_started_tick,
                    },
                    "$push": {
                        "readings": {
                            "tick": self.tick,
                            "queued": round(sim.queued),
                            "queue_ratio": round(event["ratio"], 2),
                            "severity": severity,
                        }
                    },
                },
                upsert=True,
            )
        return doc

    def _surge_message(self, event: dict) -> str:
        sim: CorridorSim = event["corridor"]
        if event["kind"] == "surge_start":
            return f"{sim.spec['name']}: queue at {round(sim.queued):,} fans — {event['ratio']:.1f}x corridor capacity"
        if event["kind"] == "surge_critical":
            return f"{sim.spec['name']}: CRITICAL — {round(sim.queued):,} fans queued, {event['ratio']:.1f}x capacity"
        return f"{sim.spec['name']}: surge resolved, queue back to {round(sim.queued):,}"

    # ------------------------------------------------------------------
    # Agent dispatch hooks
    # ------------------------------------------------------------------

    def _fire(self, kind: str, payload: dict) -> None:
        if self.dispatcher is None:
            return
        task = asyncio.create_task(self.dispatcher(kind, payload))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    def snapshot(self) -> dict:
        return {
            "run_id": self.run_id,
            "tick": self.tick,
            "t_minus_minutes": (KICKOFF_TICK - self.tick) * TICK_MINUTES,
            "phase": self._phase(),
            "corridors": [self._corridor_doc(s) for s in self.corridors.values()],
        }

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> dict:
        logger.info("engine start run_id=%s", self.run_id)
        if self.db is not None:
            self.db[mongo.RUNS].update_one(
                {"run_id": self.run_id},
                {"$set": {"status": "simulating", "started_at": _now(), "max_ticks": MAX_TICKS}},
                upsert=True,
            )

        next_concierge_round = 6
        while self.tick < MAX_TICKS:
            self.tick += 1
            applied = self._apply_effects()
            incidents = self._apply_incidents()
            self._advance_physics()
            surge_events = self._update_surge_states()
            self._persist_tick()

            for inc in incidents:
                self._fire("incident", {"incident": inc, "snapshot": self.snapshot()})

            for event in surge_events:
                alert = self._record_surge_alert(event)
                sim: CorridorSim = event["corridor"]
                if event["kind"] == "surge_start":
                    self._fire("concierge", {"corridor_id": sim.id, "snapshot": self.snapshot(), "trigger": "surge"})
                if event["kind"] == "surge_critical" and not sim.coordinator_called:
                    sim.coordinator_called = True
                    self._fire("coordinator", {"alert": alert, "snapshot": self.snapshot()})

            if self.tick >= next_concierge_round and self.tick < KICKOFF_TICK:
                next_concierge_round = self.tick + CONCIERGE_ROUND_INTERVAL
                self._fire("concierge_round", {"snapshot": self.snapshot()})

            if applied:
                logger.info("tick %d applied effects: %s", self.tick, [a.get("action") for a in applied])

            # Stop early once everyone is in their seat.
            if self.tick > KICKOFF_TICK and all(c.queued < 1 and c.in_transit_total < 1 for c in self.corridors.values()):
                break

            await asyncio.sleep(self.pace)

        delivered = round(sum(c.delivered for c in self.corridors.values()))
        stranded = round(sum(c.queued + c.in_transit_total for c in self.corridors.values()))
        summary = {
            "delivered": delivered,
            "stranded": stranded,
            "fans_total": TOTAL_FANS,
            "final_tick": self.tick,
            "delivery_rate": round(delivered / TOTAL_FANS, 3),
        }
        if self.db is not None:
            self.db[mongo.RUNS].update_one(
                {"run_id": self.run_id},
                {"$set": {"status": "complete", "finished_at": _now(), "summary": summary}},
            )
        self._fire("post_match", {"summary": summary, "snapshot": self.snapshot()})
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        logger.info("engine done run_id=%s summary=%s", self.run_id, summary)
        return summary
