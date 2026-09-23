COMPOSE ?= docker compose -f infra/docker-compose.yml

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up

down:
	$(COMPOSE) down

test:
	$(COMPOSE) run --rm api pytest -q /app/tests
	$(COMPOSE) run --rm bot pytest -q /app/tests
	$(COMPOSE) run --rm worker pytest -q /app/tests
	$(COMPOSE) build miniapp

compile:
	$(COMPOSE) run --rm api python -m compileall app tests
	$(COMPOSE) run --rm bot python -m compileall app tests
	$(COMPOSE) run --rm worker python -m compileall app tests
