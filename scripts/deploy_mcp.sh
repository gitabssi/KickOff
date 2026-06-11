#!/usr/bin/env bash
# Deploy the MongoDB MCP server to Cloud Run.
#
# Usage: bash scripts/deploy_mcp.sh [PROJECT_ID] [REGION]
# Reads MONGODB_URI from .env.
#
# NOTE (demo tradeoff): the service is deployed with --allow-unauthenticated
# so Agent Engine instances can reach it without token plumbing. The Atlas
# connection string never leaves the server, but anyone with the URL can
# issue MCP calls against the demo database. For production, switch to
# --no-allow-unauthenticated and attach ID tokens in agents/common/mcp.py.

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-us-central1}"
SERVICE="kickoff-mcp"

MONGODB_URI=$(grep '^MONGODB_URI=' .env | cut -d= -f2-)
[ -n "$MONGODB_URI" ] || { echo "MONGODB_URI missing from .env"; exit 1; }

echo "Deploying $SERVICE to $PROJECT_ID/$REGION..."

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source deploy/mcp \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --set-env-vars "MDB_MCP_CONNECTION_STRING=$MONGODB_URI,MDB_MCP_TELEMETRY=disabled"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')
mkdir -p .deploy
echo "$URL" > .deploy/mcp_url
echo "MCP server live at: $URL/mcp"
echo "Saved to .deploy/mcp_url"
