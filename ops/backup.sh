#!/bin/sh
set -eu
BACKUP_DIR="${BACKUP_DIR:-/var/backups/videocut}"
PROJECT_DIR="${PROJECT_DIR:-/opt/videocut}"
mkdir -p "$BACKUP_DIR"
DATE=$(date -u +%Y%m%dT%H%M%SZ)
cd "$PROJECT_DIR"
docker-compose -f infra/docker-compose.yml exec -T redis redis-cli --rdb "/data/dump-${DATE}.rdb" >/dev/null
VOLUME=$(docker volume ls -q | grep 'infra_redis_data$' | head -n 1)
docker run --rm -v "${VOLUME}:/data:ro" -v "${BACKUP_DIR}:/backup" alpine:3.21 sh -c "cp /data/dump-${DATE}.rdb /backup/redis-${DATE}.rdb"
find "$BACKUP_DIR" -type f -name 'redis-*.rdb' -mtime +7 -delete
chmod 600 "$BACKUP_DIR"/redis-*.rdb
