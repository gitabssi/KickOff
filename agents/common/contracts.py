"""Shared prompt fragments — the JSON contracts agents must speak.

The engine applies agent decisions mechanically, so the decision shape is a
hard contract. It lives here once and is embedded into every instruction.
"""

DECISION_SCHEMA = """\
{
  "agent": "<your agent name>",
  "corridor_id": "rail | shuttle_a | shuttle_b | park_ride",
  "tick": <current tick number>,
  "action": "boost_capacity | divert | hold | advise",
  "magnitude": <0.05-0.5 for boost_capacity, 0.02-0.2 for divert, 0 otherwise>,
  "divert_to": "<target corridor_id, only for divert, else null>",
  "headline": "<max 60 chars, punchy, present tense>",
  "reasoning": "<1-2 sentences explaining WHY, citing the numbers you read>"
}"""

ACTIONS_EXPLAINED = """\
Available actions and their real-world meaning:
- boost_capacity: add service (extra trains, more shuttle departures).
  magnitude 0.3 = +30% capacity on this corridor. Use when YOUR queue is the problem.
- divert: redirect arriving fans toward another corridor (signage, app pushes,
  staff redirecting at origin). magnitude 0.1 = move 10% of total fan share.
  Use when your corridor is degraded and another has headroom.
- hold: no change; conditions are acceptable. Always valid when queue_ratio < 1.5.
- advise: no mechanical change, but broadcast guidance to fans (e.g. "allow
  extra 20 minutes"). Use for awareness during transit delays.
"""

MONGO_RULES = """\
MongoDB rules (you are connected to the live matchday database via MCP tools):
- database is "kickoff" — pass database="kickoff" on every MCP tool call.
- Read live state with `find` (filter by run_id!), never invent numbers.
- Record every decision by inserting your decision JSON document into the
  `agent_decisions` collection with `insert-many` BEFORE you return.
- Keep tool calls minimal: one or two reads, one write.
"""
