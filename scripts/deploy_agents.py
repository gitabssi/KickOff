"""Deploy KickOff agents to Vertex AI Agent Engine.

Order matters: planner, simulator, and the four concierges deploy first (in
parallel); the coordinator deploys last because its call_agent tool needs
the others' resource names in AGENT_ENGINES_JSON.

Writes .deploy/agent_engines.json — the gateway and local cloud-mode
dispatch read the agent-name -> resource mapping from there.

Usage:
    uv run python scripts/deploy_agents.py [--project PROJECT] [--region REGION]
    uv run python scripts/deploy_agents.py --only planner
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.common import config  # noqa: E402

REQUIREMENTS = [
    "google-adk>=1.31.0",
    "google-cloud-aiplatform[agent_engines]>=1.112.0",
    "a2a-sdk<0.4.0",
    "pymongo>=4.10.0",
    "python-dotenv>=1.0.0",
    "mcp>=1.5.0",
    "httpx>=0.27.0",
]

FIRST_WAVE = ["planner", "simulator", "concierge_rail", "concierge_shuttle_a", "concierge_shuttle_b", "concierge_park_ride"]


def build_agent(name: str):
    from agents.common.dispatch import _build_agent

    return _build_agent(name)


def common_env(mcp_url: str) -> dict:
    return {
        "MONGODB_DB": config.MONGODB_DB,
        "KICKOFF_MODEL": config.MODEL,
        "KICKOFF_PLANNER_MODEL": config.PLANNER_MODEL,
        "KICKOFF_MCP_MODE": "http",
        "MCP_SERVER_URL": mcp_url,
        "KICKOFF_AGENT_MODE": "cloud",
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
    }


def deploy_one(name: str, project: str, region: str, staging_bucket: str, env: dict, existing: dict) -> tuple[str, str]:
    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=region, staging_bucket=staging_bucket)

    agent = build_agent(name)
    app = agent_engines.AdkApp(agent=agent, enable_tracing=True)

    display_name = f"kickoff-{name.replace('_', '-')}"
    prior = existing.get(name)

    print(f"  [{name}] {'updating ' + prior if prior else 'creating'}...")
    if prior:
        engine = agent_engines.update(
            resource_name=prior,
            agent_engine=app,
            requirements=REQUIREMENTS,
            extra_packages=["agents"],
            env_vars=env,
            display_name=display_name,
        )
    else:
        engine = agent_engines.create(
            agent_engine=app,
            requirements=REQUIREMENTS,
            extra_packages=["agents"],
            env_vars=env,
            display_name=display_name,
        )
    print(f"  [{name}] -> {engine.resource_name}")
    return name, engine.resource_name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=config.optional("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--region", default=config.optional("GOOGLE_CLOUD_LOCATION", "us-central1"))
    parser.add_argument("--only", help="Deploy a single agent by name")
    args = parser.parse_args()

    if not args.project:
        sys.exit("Set GOOGLE_CLOUD_PROJECT in .env or pass --project")

    deploy_dir = REPO_ROOT / ".deploy"
    deploy_dir.mkdir(exist_ok=True)

    mcp_url_file = deploy_dir / "mcp_url"
    if not mcp_url_file.exists():
        sys.exit("Run scripts/deploy_mcp.sh first (.deploy/mcp_url missing)")
    mcp_url = mcp_url_file.read_text().strip().rstrip("/") + "/mcp"

    engines_file = deploy_dir / "agent_engines.json"
    engines: dict = json.loads(engines_file.read_text()) if engines_file.exists() else {}

    staging_bucket = f"gs://{args.project}-kickoff-staging"
    os.system(f"gsutil mb -p {args.project} -l {args.region} {staging_bucket} 2>/dev/null")

    mongodb_uri = config.required("MONGODB_URI")
    base_env = common_env(mcp_url)

    def env_for(name: str) -> dict:
        env = dict(base_env)
        if name == "simulator":
            # The simulator's engine writes per-tick telemetry via the
            # driver and dispatches other agents in cloud mode.
            env["MONGODB_URI"] = mongodb_uri
            env["AGENT_ENGINES_JSON"] = json.dumps(engines)
        if name == "coordinator":
            env["AGENT_ENGINES_JSON"] = json.dumps(engines)
            env["MONGODB_URI"] = mongodb_uri  # dispatcher feed fallback
        return env

    targets = [args.only] if args.only else FIRST_WAVE

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(deploy_one, name, args.project, args.region, staging_bucket, env_for(name), engines)
            for name in targets
        ]
        for f in futures:
            name, resource = f.result()
            engines[name] = resource
            engines_file.write_text(json.dumps(engines, indent=2))

    if not args.only:
        # Second wave: coordinator gets the full engine map.
        name, resource = deploy_one("coordinator", args.project, args.region, staging_bucket, env_for("coordinator"), engines)
        engines[name] = resource
        engines_file.write_text(json.dumps(engines, indent=2))

    print("\nDeployed engines:")
    print(json.dumps(engines, indent=2))
    print(f"\nMap written to {engines_file}")


if __name__ == "__main__":
    main()
