PYTHON ?= python3
RUNNER := $(PYTHON) -m tools.test_runner

.PHONY: test test-code test-docker lint type security bootstrap docker-up docker-down docker-ps docker-logs docker-restart env-sync deploy-local smoke policy-validate control-plane-validate alert-catalog seed db-migrate db-reset build-frontend

bootstrap:
	$(RUNNER) --bootstrap --code

test:
	$(RUNNER) --all

test-code:
	$(RUNNER) --code

test-docker:
	$(RUNNER) --docker

lint:
	$(RUNNER) --lint

type:
	$(RUNNER) --type

security:
	$(RUNNER) --security

policy-validate:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/policy_validate.py --path config/policy.yaml; \
	else \
		$(PYTHON) scripts/policy_validate.py --path config/policy.yaml; \
	fi

control-plane-validate:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/control_plane.py --path config/control_plane.json validate; \
	else \
		$(PYTHON) scripts/control_plane.py --path config/control_plane.json validate; \
	fi

docker-up:
	bash scripts/stack.sh up

docker-down:
	bash scripts/stack.sh down

docker-restart:
	bash scripts/stack.sh restart

docker-ps:
	bash scripts/stack.sh ps

docker-logs:
	bash scripts/stack.sh logs

env-sync:
	bash scripts/sync_env.sh

deploy-local:
	bash scripts/deploy_local.sh

smoke:
	bash scripts/smoke.sh

alert-catalog:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/build_alert_catalogs.py; \
	else \
		$(PYTHON) scripts/build_alert_catalogs.py; \
	fi

db-migrate:
	@if [ -x .venv/bin/alembic ]; then \
		.venv/bin/alembic upgrade head; \
	else \
		alembic upgrade head; \
	fi

seed:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/seed_data.py; \
	else \
		$(PYTHON) scripts/seed_data.py; \
	fi

db-reset:
	@if [ -x .venv/bin/python ]; then \
		.venv/bin/python scripts/seed_data.py --reset; \
	else \
		$(PYTHON) scripts/seed_data.py --reset; \
	fi

build-frontend:
	cd frontend && npm install && npm run build
