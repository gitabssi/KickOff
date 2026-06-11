#!/usr/bin/env bash
# Deploy the KickOff gateway (frontend + API) to Cloud Run.
#
# Usage: bash scripts/deploy_gateway.sh [PROJECT_ID] [REGION] [AGENT_MODE]
#   AGENT_MODE: local (default — agents in-process, simplest, fully working)
#               cloud (agents on Vertex AI Agent Engine; run deploy_agents.py first)

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-us-central1}"
AGENT_MODE="${3:-local}"
SERVICE="kickoff"

MONGODB_URI=$(grep '^MONGODB_URI=' .env | cut -d= -f2-)
[ -n "$MONGODB_URI" ] || { echo "MONGODB_URI missing from .env"; exit 1; }

ENV_VARS="MONGODB_URI=$MONGODB_URI"
ENV_VARS+=",MONGODB_DB=kickoff"
ENV_VARS+=",GOOGLE_CLOUD_PROJECT=$PROJECT_ID"
ENV_VARS+=",GOOGLE_CLOUD_LOCATION=$REGION"
ENV_VARS+=",GOOGLE_GENAI_USE_VERTEXAI=TRUE"
ENV_VARS+=",KICKOFF_AGENT_MODE=$AGENT_MODE"

if [ "$AGENT_MODE" = "cloud" ]; then
  [ -f .deploy/agent_engines.json ] || { echo "Run deploy_agents.py first"; exit 1; }
  # Engine map is JSON with commas — pass via env file instead of --set-env-vars.
  ENGINES_JSON=$(cat .deploy/agent_engines.json | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)))')
  printf 'AGENT_ENGINES_JSON: %s\n' "$ENGINES_JSON" > /tmp/kickoff-env.yaml
else
  : > /tmp/kickoff-env.yaml
fi
if [ "$AGENT_MODE" = "local" ] && [ -f .deploy/mcp_url ]; then
  ENV_VARS+=",KICKOFF_MCP_MODE=http,MCP_SERVER_URL=$(cat .deploy/mcp_url)/mcp"
fi

echo "Deploying $SERVICE ($AGENT_MODE agent mode) to $PROJECT_ID/$REGION..."

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 1Gi \
  --cpu 2 \
  --timeout 3600 \
  --set-env-vars "$ENV_VARS" \
  $( [ -s /tmp/kickoff-env.yaml ] && echo "--env-vars-file /tmp/kickoff-env.yaml" )

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')
echo ""
echo "KickOff live at: $URL"
