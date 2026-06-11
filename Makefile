# KickOff Agent — task runner
# Combines agent-starter-pack targets (install, playground, deploy, test,
# lint, eval) with the KickOff demo pipeline (seed, dev, build, deploy-*).

# ==============================================================================
# Installation & Setup
# ==============================================================================

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $$HOME/.local/bin/env; }
	uv sync

init: install        ## Install Python + frontend dependencies
	cd web && npm install

seed:                ## Create MongoDB collections, indexes, and baseline plan
	uv run python scripts/seed_db.py

# ==============================================================================
# Local development
# ==============================================================================

dev:                 ## Run gateway locally (serves built frontend + API)
	uv run uvicorn gateway.main:app --reload --port 8080

web:                 ## Frontend dev server with hot reload (proxies API to :8080)
	cd web && npm run dev

build:               ## Build frontend into gateway/static
	cd web && npm run build

# Launch local dev playground (agent-starter-pack)
playground:
	@echo "==============================================================================="
	@echo "| 🚀 Starting your agent playground...                                        |"
	@echo "| 🔍 Select the 'agents' folder to chat with the KickOff coordinator.        |"
	@echo "==============================================================================="
	uv run adk web . --port 8501 --reload_agents

# ==============================================================================
# Deployment
# ==============================================================================

# agent-starter-pack single-agent deploy (coordinator as root agent).
# Usage: make deploy [AGENT_IDENTITY=true] [SECRETS="KEY=SECRET_ID,..."]
deploy:
	(uv export --no-hashes --no-header --no-dev --no-emit-project --no-annotate > agents/app_utils/.requirements.txt 2>/dev/null || \
	uv export --no-hashes --no-header --no-dev --no-emit-project > agents/app_utils/.requirements.txt) && \
	uv run -m agents.app_utils.deploy \
		--source-packages=./agents \
		--entrypoint-module=agents.agent_engine_app \
		--entrypoint-object=agent_engine \
		--requirements-file=agents/app_utils/.requirements.txt \
		$(if $(AGENT_IDENTITY),--agent-identity) \
		$(if $(filter command line,$(origin SECRETS)),--set-secrets="$(SECRETS)")

backend: deploy

deploy-mcp:          ## MongoDB MCP server -> Cloud Run
	bash scripts/deploy_mcp.sh

deploy-agents:       ## Full agent fleet -> Vertex AI Agent Engine
	uv run python scripts/deploy_agents.py

deploy-gateway:      ## Frontend + gateway -> Cloud Run
	bash scripts/deploy_gateway.sh

deploy-all: deploy-mcp deploy-agents deploy-gateway  ## Full cloud deploy

# ==============================================================================
# Testing & Code Quality
# ==============================================================================

test:
	uv sync --dev
	uv run pytest tests/unit && uv run pytest tests/integration

lint:
	uv sync --dev --extra lint
	uv run codespell
	uv run ruff check . --diff

# ==============================================================================
# Agent Evaluation (agent-starter-pack)
# ==============================================================================

eval:
	uv sync --dev --extra eval
	uv run adk eval ./agents $${EVALSET:-tests/eval/evalsets/basic.evalset.json} \
		$(if $(EVAL_CONFIG),--config_file_path=$(EVAL_CONFIG),$(if $(wildcard tests/eval/eval_config.json),--config_file_path=tests/eval/eval_config.json,))

# Register the deployed agent to Gemini Enterprise
register-gemini-enterprise:
	@uvx agent-starter-pack@0.41.3 register-gemini-enterprise

help:
	@grep -E '^[a-zA-Z_-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'
