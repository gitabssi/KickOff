# KickOff Agent — 3-Minute Demo Video Script

**Format:** screen recording of the hosted URL + voiceover. Times are cumulative.
**Before recording:** open the hosted URL, open MongoDB Atlas → Database → Collections in a second tab, zoom browser to 100%, hide bookmarks bar.

---

## [0:00 – 0:20] The hook

*(On screen: the idle 3D map — stadium glowing, four dark corridors, the big green LAUNCH button.)*

> "This is MetLife Stadium, New Jersey. In 2026 it hosts the World Cup final: eighty-two and a half thousand fans — and **no parking**. Every single fan arrives through four transport corridors. One rail line, two shuttle networks, one park-and-ride.
>
> This is KickOff Agent: five AI agents running matchday operations on Google's Agent Development Kit, Gemini 3, and MongoDB Atlas. Let's give them a matchday."

## [0:20 – 0:40] One button

*(Click **LAUNCH SIMULATION**. The planner banner appears; the plan card lands in the feed.)*

> "One click. The Coordinator agent calls the Planner over the A2A protocol. The Planner reads the baseline plan from MongoDB through the **MongoDB MCP server**, designs today's corridor split, and commits it to Atlas — that green banner is the actual database write coming back over a change stream.
>
> Now watch the bottom bar: every operation you'll see for the next two minutes is a live write to MongoDB."

## [0:40 – 1:10] The simulation breathes

*(Fans start flowing: particles along corridors, capacity bars animating, clock counting down from T−180.)*

> "The Simulator advances matchday in two-minute ticks. Each tick updates four corridor documents in Atlas; the change stream pushes them straight into this view. Particle density is corridor flow. The beams at the stations are queues building.
>
> Every few ticks, four Fan Concierge agents — one per corridor, each with its own personality — read their live state from MongoDB and make one operational decision each. There they are in the feed, with their reasoning."

## [1:10 – 1:50] Disaster and escalation ⭐ the money shot

*(Around T−124 the incident banner hits: SIGNAL FAILURE AT SECAUCUS JUNCTION. Rail corridor turns amber, then red. Surge alert. Then the critical alert + the green NEW COLLECTION banner.)*

> "And here's the matchday nightmare: signal failure on the rail line — the corridor carrying nearly half of all fans, cut to 45% capacity at peak. Watch the queue.
>
> Surge alert — the rail concierge boosts service on its own authority. Not enough. The queue passes six times capacity: **critical**. Now the Coordinator takes over: it reads all four corridors from Atlas, diverts arriving fans toward corridors with headroom, and boosts them.
>
> *(point at the green banner)* And right there — mid-simulation — the Coordinator just **created a brand-new collection**, `surge_history`, through the MCP server. Schema evolution on a live system, zero downtime, zero migration. That's why this runs on MongoDB."

*(Flip briefly to the Atlas tab, refresh Collections, show `surge_history` exists with documents. Flip back.)*

## [1:50 – 2:30] Recovery

*(Corridors shift back toward their colors; surge resolves; second incident at the Lincoln Tunnel plays out smaller; delivered counter climbs.)*

> "The rebalance lands: green badges show boosted service, the rail queue drains, the surge resolves — logged in `surge_history` with per-tick readings.
>
> A second incident hits the Lincoln Tunnel; this time the concierges contain it without escalation. The agents disagree, escalate, and recover — exactly like a real operations room, except every decision and its reasoning is a queryable document in Atlas."

## [2:30 – 3:00] Kickoff and the close

*(T−0: confetti, KICKOFF banner, FULL TIME summary banner with delivery percentage.)*

> "Kickoff. Without agents, this network strands ten thousand fans outside. With them: over ninety-nine percent in their seats.
>
> KickOff Agent — five Gemini 3 agents on Google ADK and Vertex AI Agent Engine, coordinating through A2A, with **MongoDB Atlas as the single source of truth**: agents read and write through MCP, the UI is nothing but Atlas change streams, and the schema evolved live while you watched.
>
> The repo is open source. Press the button yourself."

*(End card: repo URL + hosted URL.)*

---

## Fallback notes

- If LLM quota dies mid-recording, relaunch with `KICKOFF_AUTOPILOT=1` — identical visuals, deterministic decisions.
- A full run takes ~2:10 from launch click to FULL TIME; the script's timing leaves ~20s of slack.
- If the surge resolves before you finish the schema-evolution line, the `surge_history` counter in the bottom bar keeps incrementing — point there instead.
