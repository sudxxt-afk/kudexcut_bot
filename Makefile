COMPOSE ?= docker compose -f infra/docker-compose.yml

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up

down:
	$(COMPOSE) down

test:
	$(COMPOSE) run --rm api pytest -q backend/tests
	$(COMPOSE) run --rm bot pytest -q bot/tests
	$(COMPOSE) run --rm miniapp npm run build

compile:
	$(COMPOSE) run --rm api python -m compileall app tests
	$(COMPOSE) run --rm bot python -m compileall app tests
