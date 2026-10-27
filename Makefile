# SBC Plan Comparison v2. Run `make help` for targets.
BACKEND := backend
FRONTEND := frontend
UV := cd $(BACKEND) && uv run

.PHONY: help setup backend-setup frontend-setup dev backend-dev frontend-dev test backend-test frontend-test \
        lint backend-lint frontend-lint score layout-cache ingest-catalog load-premiums gen-api check-api-types e2e

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

setup: backend-setup frontend-setup ## install backend and frontend dependencies

backend-setup: ## uv sync the backend
	cd $(BACKEND) && uv sync

frontend-setup: ## npm install the frontend
	cd $(FRONTEND) && npm install

dev: ## run backend (:8000) and frontend (:5173) together
	$(MAKE) -j2 backend-dev frontend-dev

backend-dev: ## FastAPI with reload on :8000
	$(UV) uvicorn sbcx.main:app --reload --port 8000

frontend-dev: ## Vite dev server on :5173
	cd $(FRONTEND) && npm run dev

test: backend-test frontend-test ## all automated tests

backend-test: ## backend unit, property and integration tests (fake LLM)
	$(UV) pytest -q

frontend-test: ## frontend unit tests
	cd $(FRONTEND) && npm test -- --run

lint: backend-lint frontend-lint ## all linters and type checks

backend-lint: ## ruff + mypy
	$(UV) ruff check sbcx tests && $(UV) ruff format --check sbcx tests && $(UV) mypy sbcx

frontend-lint: ## eslint + tsc
	cd $(FRONTEND) && npm run lint && npm run typecheck

layout-cache: ## warm the PDF layout cache for the local corpus
	$(UV) sbcx layout --all

score: ## score the parser on gold and v1.4 reviewed with eval/score.py
	$(UV) sbcx score --set gold && $(UV) sbcx score --set v14

ingest-catalog: ## extract the local SBC corpus into the plan catalog
	$(UV) sbcx ingest-catalog

load-premiums: ## download and load the CMS Rate PUF premiums
	$(UV) sbcx load-premiums

gen-api: ## regenerate frontend API types from the backend OpenAPI spec
	$(UV) sbcx openapi > ../$(FRONTEND)/openapi.json && cd ../$(FRONTEND) && npm run gen:api

check-api-types: gen-api ## fail if generated API types are out of date
	git diff --exit-code -- $(FRONTEND)/src/api/schema.d.ts $(FRONTEND)/openapi.json

e2e: ## Playwright end-to-end tests (fake LLM)
	cd $(FRONTEND) && npm run e2e
