.PHONY: help dev-up dev-down dev-logs api-dev ui-dev test test-backend test-ui test-golden evals seed-knowledge opa-check compose-check fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

dev-up: ## Start full stack (postgres, redis, opa, api, ui)
	docker compose up --build -d
	@echo "API: http://localhost:8000  UI: http://localhost:8080  OPA: http://localhost:8181"

dev-up-monitoring: ## Start full stack + prometheus
	docker compose --profile monitoring up --build -d

dev-down: ## Stop full stack
	docker compose down

dev-logs: ## Tail stack logs
	docker compose logs -f

api-dev: ## Run API locally (SQLite + local policy evaluator, no docker needed)
	cd backend && uvicorn ci_agent.api.main:app --host 0.0.0.0 --port 8000 --reload

ui-dev: ## Run UI dev server (proxies /api to localhost:8000)
	cd ui && npm install && npm run dev -- --host 0.0.0.0 --port 5173

test: test-backend test-ui ## Run backend + UI tests

test-backend: ## Run backend test suite
	cd backend && python -m pytest -q

test-ui: ## Type-check + build UI
	cd ui && npm install && npm run build

test-golden: ## Run golden determinism tests only
	cd backend && python -m pytest tests/golden -q

evals: ## Run agent evaluation dataset
	cd backend && python -m pytest tests/evals -q

seed-knowledge: ## Show bundled knowledge seed stats
	cd backend && python -m ci_agent.knowledge.seeds --stats

opa-check: ## Validate Rego bundle (needs `opa` binary; CI installs it)
	opa check ./deploy/opa/store

compose-check: ## Validate docker-compose.yml syntax without docker
	python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('compose OK')"

fmt: ## Format backend code (ruff if available)
	cd backend && (ruff check --fix . ; ruff format .) || echo "ruff not installed, skipping"

clean: ## Remove runtime data (keeps repo files)
	rm -rf data .agent-work backend/.pytest_cache ui/dist ui/node_modules
