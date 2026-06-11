"""Wires engine events to agent reasoning.

The engine fires events (concierge rounds, surge escalations, incidents,
post-match) without waiting; this module turns each into an agent
invocation, parses the returned decision JSON, and queues the mechanical
effect back onto the engine for the next tick.

KICKOFF_AUTOPILOT=1 swaps every LLM invocation for a deterministic policy —
the Race Condition `runner_autopilot` pattern. Same decisions docs, same
feed, zero model calls. Use it for UI development and as a quota fallback.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from agents.common import config, mongo
from agents.common.corridors import CORRIDOR_IDS
from agents.common.dispatch import dispatch, extract_json

logger = logging.getLogger(__name__)

# At most two concurrent LLM invocations keeps us friendly with both Vertex
# rate limits and the M0 Atlas connection budget.
_semaphore = asyncio.Semaphore(2)


class AgentDispatcher:
    def __init__(self, engine):
        self.engine = engine
        self.db = mongo.db()

    async def __call__(self, kind: str, payload: dict) -> None:
        try:
            if kind == "concierge_round":
                await self._concierge_round(payload)
            elif kind == "concierge":
                await self._concierge_one(payload["corridor_id"], payload["snapshot"], payload.get("trigger", "round"))
            elif kind == "coordinator":
                await self._coordinator_escalation(payload)
            elif kind == "incident":
                self._record_incident(payload)
            elif kind == "post_match":
                await self._post_match(payload)
        except Exception:
            logger.exception("dispatcher %s failed", kind)

    # ------------------------------------------------------------------

    def _insert_decision(self, doc: dict) -> None:
        doc.setdefault("run_id", self.engine.run_id)
        doc.setdefault("ts", datetime.now(timezone.utc))
        self.db[mongo.AGENT_DECISIONS].insert_one(doc)

    def _feed_fallback(self, agent: str, decision: dict) -> None:
        """Ensure the decision reaches the feed even if the agent's MCP
        insert failed. The MCP write is the normal path; this is insurance."""
        tick = int(decision.get("tick", self.engine.tick))
        exists = self.db[mongo.AGENT_DECISIONS].count_documents(
            {"run_id": self.engine.run_id, "agent": agent, "tick": {"$gte": tick - 3, "$lte": tick + 3}},
            limit=1,
        )
        if not exists:
            decision = dict(decision)
            decision["agent"] = agent
            decision["via"] = "return_value"
            self._insert_decision(decision)

    def _apply_decision(self, agent: str, decision: dict | None) -> None:
        if not decision:
            logger.warning("%s returned no parseable decision", agent)
            return
        decision.setdefault("agent", agent)
        decision.setdefault("tick", self.engine.tick)
        self.engine.queue_effect(decision)
        self._feed_fallback(agent, decision)

    # ------------------------------------------------------------------

    async def _concierge_round(self, payload: dict) -> None:
        tasks = []
        for i, cid in enumerate(CORRIDOR_IDS):
            tasks.append(self._concierge_one(cid, payload["snapshot"], "round", delay=i * 1.2))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _concierge_one(self, corridor_id: str, snapshot: dict, trigger: str, delay: float = 0.0) -> None:
        if delay:
            await asyncio.sleep(delay)
        agent = f"concierge_{corridor_id}"
        if config.AUTOPILOT:
            self._apply_decision(agent, self._autopilot_concierge(corridor_id, snapshot, trigger))
            return
        message = json.dumps({"trigger": trigger, **snapshot}, default=str)
        async with _semaphore:
            text = await dispatch(agent, message)
        self._apply_decision(agent, extract_json(text))

    async def _coordinator_escalation(self, payload: dict) -> None:
        if config.AUTOPILOT:
            decision = self._autopilot_coordinator(payload)
        else:
            message = json.dumps({"action": "surge_escalation", **payload}, default=str)
            async with _semaphore:
                text = await dispatch("coordinator", message)
            decision = extract_json(text)
        if decision:
            for directive in decision.get("directives", []):
                directive.setdefault("tick", self.engine.tick)
                self.engine.queue_effect(directive)
            self._feed_fallback("coordinator", decision)
        # The coordinator creates surge_history through MCP on first
        # escalation; flip the engine flag once it exists so per-tick
        # readings start appending.
        if mongo.SURGE_HISTORY in self.db.list_collection_names():
            self.engine.surge_history_created = True

    async def _post_match(self, payload: dict) -> None:
        if config.AUTOPILOT:
            s = payload["summary"]
            self._insert_decision(
                {
                    "agent": "coordinator",
                    "corridor_id": "rail",
                    "tick": self.engine.tick,
                    "action": "advise",
                    "headline": "Match report",
                    "reasoning": f"Delivered {s['delivered']:,} of {s['fans_total']:,} fans "
                    f"({s['delivery_rate'] * 100:.1f}%) across 4 corridors.",
                    "report": "Autopilot run — no LLM narrative.",
                }
            )
            return
        message = json.dumps({"action": "post_match", "run_id": self.engine.run_id, **payload}, default=str)
        async with _semaphore:
            text = await dispatch("coordinator", message)
        decision = extract_json(text)
        if decision:
            self._feed_fallback("coordinator", decision)

    def _record_incident(self, payload: dict) -> None:
        inc = payload["incident"]
        self._insert_decision(
            {
                "agent": "simulator",
                "corridor_id": inc["corridor_id"],
                "tick": self.engine.tick,
                "action": "incident",
                "headline": inc["headline"],
                "reasoning": inc["detail"],
                "kind": inc["kind"],
            }
        )

    # ------------------------------------------------------------------
    # Autopilot policies (deterministic, zero LLM)
    # ------------------------------------------------------------------

    def _autopilot_concierge(self, corridor_id: str, snapshot: dict, trigger: str) -> dict:
        me = next(c for c in snapshot["corridors"] if c["corridor_id"] == corridor_id)
        ratio = me["queue_ratio"]
        if ratio >= 3.0 and me["boost"] < 1.5:
            action, magnitude, divert_to = "boost_capacity", 0.3, None
            headline = f"Adding service on {me['name']}"
            reasoning = f"Queue at {me['queued']:,} fans, {ratio}x capacity — boosting throughput 30%."
        elif ratio >= 3.0:
            others = [c for c in snapshot["corridors"] if c["corridor_id"] != corridor_id and c["queue_ratio"] < 1.5]
            if others:
                target = max(others, key=lambda c: c["capacity_per_tick"])
                action, magnitude, divert_to = "divert", 0.08, target["corridor_id"]
                headline = f"Diverting fans to {target['name']}"
                reasoning = f"Already boosted to {me['boost']}x; sending 8% of arrivals to {target['name']}."
            else:
                action, magnitude, divert_to = "advise", 0, None
                headline = "Network saturated — advising patience"
                reasoning = "All corridors loaded; broadcasting delay guidance to fans."
        elif ratio >= 1.5:
            action, magnitude, divert_to = "boost_capacity", 0.15, None
            headline = f"Pre-emptive boost on {me['name']}"
            reasoning = f"Queue ratio {ratio}x and climbing — adding 15% service early."
        else:
            action, magnitude, divert_to = "hold", 0, None
            headline = f"{me['name']} flowing normally"
            reasoning = f"Queue ratio {ratio}x — no intervention needed."
        return {
            "agent": f"concierge_{corridor_id}",
            "corridor_id": corridor_id,
            "tick": snapshot["tick"],
            "action": action,
            "magnitude": magnitude,
            "divert_to": divert_to,
            "headline": headline,
            "reasoning": reasoning,
        }

    def _autopilot_coordinator(self, payload: dict) -> dict:
        alert = payload["alert"]
        snapshot = payload["snapshot"]
        cid = alert["corridor_id"]
        healthy = [c for c in snapshot["corridors"] if c["corridor_id"] != cid and c["queue_ratio"] < 2.0]
        directives = []
        if healthy:
            target = max(healthy, key=lambda c: c["capacity_per_tick"])
            directives.append({"corridor_id": cid, "action": "divert", "magnitude": 0.1, "divert_to": target["corridor_id"]})
            for h in healthy[:2]:
                directives.append({"corridor_id": h["corridor_id"], "action": "boost_capacity", "magnitude": 0.25})
        # Mirror the coordinator's schema-evolution move: create
        # surge_history on first escalation (driver instead of MCP here —
        # autopilot makes no MCP calls by design).
        if mongo.SURGE_HISTORY not in self.db.list_collection_names():
            self.db.create_collection(mongo.SURGE_HISTORY)
            self.db[mongo.SURGE_HISTORY].create_index([("run_id", 1), ("surge_id", 1)])
        self.db[mongo.SURGE_HISTORY].update_one(
            {"run_id": self.engine.run_id, "surge_id": alert["surge_id"]},
            {
                "$set": {
                    "corridor_id": cid,
                    "started_tick": alert["tick"],
                    "coordinator_assessment": f"{alert['corridor_name']} critical at {alert['queue_ratio']}x capacity; "
                    f"rebalancing {len(directives)} corridors.",
                    "directives_issued": len(directives),
                }
            },
            upsert=True,
        )
        return {
            "agent": "coordinator",
            "corridor_id": cid,
            "tick": snapshot["tick"],
            "action": "advise",
            "magnitude": 0,
            "divert_to": None,
            "headline": f"Rebalancing network around {alert['corridor_name']}",
            "reasoning": f"{alert['corridor_name']} is critical ({alert['queue_ratio']}x). "
            f"Diverting 10% of arrivals and boosting {len(directives) - 1} healthy corridors.",
            "directives": directives,
        }
