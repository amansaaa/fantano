#!/usr/bin/env bash
# copies the mac's database to cloud sql, so the live site shows the newest pipeline data.
#
# the pipeline only runs on the mac (youtube blocks cloud ips), so the local MySQL is the
# source of truth and cloud sql is just a copy of it. each push fully replaces that copy.
#
# steps:
#   1. dump the local database (the docker container from the repo's docker-compose.yml)
#   2. open a tunnel to cloud sql with cloud-sql-proxy (127.0.0.1:3307 -> fantano-db)
#   3. load the dump through the tunnel, then close it
#
# usage (from the repo root, with `docker compose up -d` running):
#   deploy/push-data.sh
#
# needs, once: brew install cloud-sql-proxy, and `gcloud auth application-default login`
# (the proxy logs in to google with those credentials, no ip allowlist needed)
#
# reads:  the local fantano database
# writes: data/dump.sql (the last dump, handy as a backup) and the fantano database on cloud sql

set -euo pipefail

INSTANCE="fantano-amansa:northamerica-northeast1:fantano-db"
# 3306 is taken by the local MySQL, so the tunnel uses the next port
PROXY_PORT=3307
DUMP_FILE="data/dump.sql"

cd "$(dirname "$0")/.."

# --- 1. dump the local database ---

echo "dumping the local database to $DUMP_FILE"
# --single-transaction    a consistent snapshot without locking the tables
# --no-tablespaces        skips a part that needs the PROCESS privilege, cloud sql has none of it
# --set-gtid-purged=OFF   cloud sql refuses dumps that try to set gtid history
# the dump starts every table with DROP TABLE + CREATE TABLE, which is why a push replaces everything
docker compose exec -T mysql sh -c \
  'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --no-tablespaces --set-gtid-purged=OFF "$MYSQL_DATABASE"' \
  > "$DUMP_FILE"

# --- 2. open the tunnel ---

read -r -s -p "cloud sql root password: " cloud_root_password
echo

echo "opening the tunnel to $INSTANCE"
cloud-sql-proxy --port "$PROXY_PORT" "$INSTANCE" > /dev/null 2>&1 &
proxy_pid=$!
# close the tunnel however the script ends (success, error, or ctrl-c)
trap 'kill "$proxy_pid" 2>/dev/null' EXIT

# wait until the tunnel accepts connections (usually a second or two)
for attempt in $(seq 1 30); do
  if nc -z 127.0.0.1 "$PROXY_PORT" 2>/dev/null; then
    break
  fi
  sleep 1
done

# --- 3. load the dump ---

echo "loading the dump into cloud sql (a minute or so)"
# the mac has no mysql client, so this borrows the one inside the local container.
# host.docker.internal is how a container reaches the mac, where the tunnel is listening
docker compose exec -T -e MYSQL_PWD="$cloud_root_password" mysql \
  mysql -h host.docker.internal -P "$PROXY_PORT" -uroot fantano \
  < "$DUMP_FILE"

echo "done: cloud sql now matches the local database"
