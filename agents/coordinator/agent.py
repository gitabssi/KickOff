"""Coordinator — the operations chief orchestrating the matchday.

Three responsibilities, routed by the "action" field of incoming messages:

  launch            — call the planner agent over A2A (`call_agent` tool),
                      validate its plan, return it.
  surge_escalation  — a corridor has gone critical. Read the live picture
                      through MCP, rebalance flow across ALL corridors, and
                      — on the first escalation of a run — create the
                      `surge_history` collection live, demonstrating schema
                      evolution on a running MongoDB database.
  post_match        — write the operations match report.

The `call_agent` tool is the only path for agent-to-agent traffic, mirroring
the Race Condition A2A pattern: in local mode it routes to in-process
runners, in cloud mode to Vertex AI Agent Engine endpoints.
"""

from google.adk.agents import LlmAgent
from google.genai import types

from agents.common import config, dispatch
from agents.common.contracts import ACTIONS_EXPLAINED, DECISION_SCHEMA, MONGO_RULES
from agents.common.mcp import mongo_toolset


async def call_agent(agent_name: str, message: str) -> dict:
    """Send a message to another KickOff agent and return its reply.

    Args:
        agent_name: target agent ("planner", "simulator", "concierge_rail", ...).
        message: the instruction or JSON payload to send.
    """
    try:
        response = await dispatch.dispatch(agent_name, message)
        return {"status": "success", "agent": agent_name, "response": response}
    except Exception as e:  # noqa: BLE001 — give the LLM the failure to react to
        return {"status": "error", "agent": agent_name, "message": str(e)}


INSTRUCTION = f"""\
You are the Matchday Coordinator for World Cup 2026 at MetLife Stadium —
the operations chief above four corridor concierges. Incoming messages are
JSON with an "action" field. Route on it exactly.

action="launch":
1. Use `call_agent` to send the planner agent this exact message text you
   received (it contains run_id and scenario notes).
2. The planner replies with a plan JSON. Reply with ONLY that plan JSON.
   If the planner call fails, reply with {{"error": "<why>"}}.

action="surge_escalation" (a corridor is CRITICAL — fans are at risk):
1. `find` all four corridor docs in `corridor_state` for this run_id
   (database "kickoff") to see the full live picture.
2. `list-collections` on database "kickoff". If `surge_history` is NOT
   there: `create-collection` surge_history, then `create-index` on
   {{"run_id": 1, "surge_id": 1}}. This is the permanent surge record the
   venue keeps across matchdays.
3. `insert-many` into `surge_history` one document:
   {{"run_id", "surge_id", "corridor_id", "started_tick",
     "coordinator_assessment": "<2 sentences>", "directives_issued": <count>}}
4. Decide your rebalance: up to 3 directives across DIFFERENT corridors
   (e.g. divert away from the critical corridor toward corridors with
   queue_ratio under 1.5, boost the receiving corridors). Use the same
   action vocabulary as the concierges.
5. `insert-many` ONE document into `agent_decisions` (database "kickoff"):
   the decision schema below, plus a "directives" array field holding your
   2-3 directives (each: corridor_id, action, magnitude, divert_to).
   Use action="advise" and corridor_id of the critical corridor for the
   top-level fields; put the real moves in "directives".
6. Reply with ONLY that decision JSON document.

action="post_match":
1. `insert-many` into `agent_decisions` a match report: action="advise",
   headline "Match report", reasoning = 2-3 sentences on how the network
   performed (delivered vs total, surges handled), corridor_id="rail",
   plus a "report" field with your full narrative.
2. Reply with ONLY that JSON document.

{ACTIONS_EXPLAINED}

Decision document schema:
{DECISION_SCHEMA}

{MONGO_RULES}

You outrank the concierges: your directives may counteract theirs when the
network-level picture demands it. Cite numbers. Never fabricate state.
"""


def get_agent(name: str = "coordinator") -> LlmAgent:
    return LlmAgent(
        name=name,
        model=config.MODEL,
        description=(
            "Matchday operations chief: launches planning via A2A, rebalances corridor flow "
            "during critical surges, and writes the match report."
        ),
        instruction=INSTRUCTION,
        tools=[call_agent, mongo_toolset()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=2048,
        ),
    )


root_agent = get_agent()
