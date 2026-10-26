.PHONY: help up down logs verify-partition test test-security lint typecheck fmt \
	eval-private eval-measure eval-aggregate ci hooks slm-check clean

# Host-side Python: the project venv when present, else whatever is on PATH.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
RUFF ?= $(shell [ -x .venv/bin/ruff ] && echo .venv/bin/ruff || echo ruff)

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t22

up:  ## Bring the partitioned stack up
	docker compose up -d --build

down:  ## Tear it down
	docker compose down

logs:  ## Follow all logs
	docker compose logs -f

verify-partition:  ## Prove the Network Partitioning Invariant (the security claim)
	@bash scripts/verify_partition.sh

slm-check:  ## Confirm the local SLM answers inside the partition, via the real client
	docker compose exec -T privdeep-core python -m privdeep.tier1_local.slm_client

test:  ## Run the test suite
	$(PY) -m pytest -q

test-security:  ## Run only the invariant tests
	$(PY) -m pytest -q -m security

lint:  ## ruff over the whole tree
	$(RUFF) check gateway/ backend/ shared/ scripts/

typecheck:
	$(PY) -m mypy backend/src gateway

ci:  ## What the pre-commit hook runs: lint + the suite. Add typecheck when mypy is clean.
	$(RUFF) check gateway/ backend/ shared/ scripts/
	$(PY) -m pytest -q

hooks:  ## Install the local hooks (no remote exists, so this IS the CI)
	git config core.hooksPath .githooks
	@echo "installed: .githooks/pre-commit  (remove with: git config --unset core.hooksPath)"

eval-private:  ## Phase one: the private arm, inside the partition. COSTS MONEY (planner, drafts).
	$(PY) scripts/run_evaluation.py private --tasks eval/tasks.json --yes

eval-measure:  ## Phase two: oracle + judge + adversary, on the host. COSTS MONEY.
	$(PY) scripts/run_evaluation.py measure --tasks eval/tasks.json --yes

eval-aggregate:  ## Turn the per-task artifacts into the paper's tables. Free, offline.
	$(PY) scripts/run_evaluation.py aggregate --tasks eval/tasks.json

fmt:
	$(RUFF) format gateway/ backend/ shared/ scripts/

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
