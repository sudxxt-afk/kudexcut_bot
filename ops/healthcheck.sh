#!/bin/sh
set -eu
PROJECT_DIR="${PROJECT_DIR:-/opt/videocut}"
cd "$PROJECT_DIR"
curl --fail --silent http://127.0.0.1:8000/health >/dev/null
docker-compose -f infra/docker-compose.yml exec -T redis redis-cli ping | grep -qx PONG
docker-compose -f infra/docker-compose.yml ps | grep -q 'infra_worker_1.*Up'
docker-compose -f infra/docker-compose.yml ps | grep -q 'infra_bot_1.*Up'
