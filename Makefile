# KickOff Agent — task runner

.PHONY: init seed dev web build test lint deploy-agents deploy-gateway deploy-mcp deploy

init:            ## Install Python + frontend dependencies
	uv sync
	cd web && npm install

seed:            ## Create MongoDB collections, indexes, and baseline plan
	uv run python scripts/seed_db.py

dev:             ## Run gateway locally (serves built frontend + API)
	uv run uvicorn gateway.main:app --reload --port 8080

web:             ## Frontend dev server with hot reload (proxies API to :8080)
	cd web && npm run dev

build:           ## Build frontend into gateway/static
	cd web && npm run build

test:            ## Run Python tests
	uv run pytest -q

lint:            ## Lint Python
	uv run ruff check agents gateway scripts

deploy-agents:   ## Deploy agents to Vertex AI Agent Engine
	uv run python scripts/deploy_agents.py

deploy-mcp:      ## Deploy MongoDB MCP server to Cloud Run
	bash scripts/deploy_mcp.sh

deploy-gateway:  ## Build frontend and deploy gateway to Cloud Run
	bash scripts/deploy_gateway.sh

deploy: deploy-mcp deploy-agents deploy-gateway  ## Full cloud deploy

help:
	@grep -E '^[a-zA-Z_-]+:.*## ' Makefile | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'
