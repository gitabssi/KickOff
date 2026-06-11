"""The four transport corridors serving MetLife Stadium on matchday.

MetLife has no meaningful fan parking for World Cup 2026, so all 82,500
attendees arrive through four corridors. Capacities are stylized but
proportioned from real matchday transport plans (NJ Transit rail carries
roughly half the load; the rest split across express buses and park & ride).

One simulation tick = 2 minutes of matchday time. The simulation window is
T-180 minutes through kickoff (90 ticks), plus a short post-window so late
surges can drain.
"""

TOTAL_FANS = 82_500
TICK_MINUTES = 2
KICKOFF_TICK = 90  # T-0 at tick 90 (180 simulated minutes)
MAX_TICKS = 100  # 20 extra simulated minutes to drain queues

# Surge thresholds (queue as a multiple of per-tick capacity)
SURGE_QUEUE_RATIO = 3.0  # queue > 3x tick capacity -> surge
CRITICAL_QUEUE_RATIO = 6.0  # queue > 6x tick capacity -> critical surge
SURGE_CLEAR_RATIO = 1.5  # queue back under 1.5x -> resolved

CORRIDORS = [
    {
        "corridor_id": "rail",
        "name": "NJ Transit Rail",
        "origin": "Secaucus Junction",
        "mode": "rail",
        "description": "Meadowlands Rail Line shuttle from Secaucus Junction",
        "capacity_per_tick": 480,  # ~14,400 fans/hour with surge service
        "preference_share": 0.45,
        "transit_ticks": 5,  # ~10 minutes ride
        "color": "#fbbf24",
    },
    {
        "corridor_id": "shuttle_a",
        "name": "Shuttle A · Port Authority",
        "origin": "Port Authority Bus Terminal",
        "mode": "bus",
        "description": "Express coach shuttle from Port Authority, NYC",
        "capacity_per_tick": 200,  # ~6,000 fans/hour
        "preference_share": 0.25,
        "transit_ticks": 9,  # ~18 minutes through the Lincoln Tunnel
        "color": "#38bdf8",
    },
    {
        "corridor_id": "shuttle_b",
        "name": "Shuttle B · Grand Central",
        "origin": "Grand Central Terminal",
        "mode": "bus",
        "description": "Express coach shuttle from Grand Central, NYC",
        "capacity_per_tick": 160,  # ~4,800 fans/hour
        "preference_share": 0.18,
        "transit_ticks": 11,  # ~22 minutes crosstown + tunnel
        "color": "#a78bfa",
    },
    {
        "corridor_id": "park_ride",
        "name": "Park & Ride · Hackensack",
        "origin": "Hackensack Lot H",
        "mode": "shuttle",
        "description": "Park & Ride shuttle loop from Hackensack",
        "capacity_per_tick": 120,  # ~3,600 fans/hour
        "preference_share": 0.12,
        "transit_ticks": 6,  # ~12 minutes local roads
        "color": "#34d399",
    },
]

CORRIDOR_IDS = [c["corridor_id"] for c in CORRIDORS]
CORRIDOR_BY_ID = {c["corridor_id"]: c for c in CORRIDORS}

# Scripted matchday incidents the simulator injects to force the agents to
# react. Each temporarily multiplies a corridor's capacity.
INCIDENTS = [
    {
        "tick": 28,
        "corridor_id": "rail",
        "kind": "signal_failure",
        "headline": "Signal failure at Secaucus Junction",
        "detail": "NJ Transit reports a signal fault on the Meadowlands spur. Rail throughput cut to 45% while single-tracking.",
        "capacity_factor": 0.45,
        "duration_ticks": 18,
    },
    {
        "tick": 55,
        "corridor_id": "shuttle_a",
        "kind": "tunnel_congestion",
        "headline": "Lincoln Tunnel congestion",
        "detail": "Heavy inbound traffic at the Lincoln Tunnel. Shuttle A round-trip times up 40%.",
        "capacity_factor": 0.6,
        "duration_ticks": 12,
    },
]
