#!/usr/bin/env bash
cd "$(dirname "$0")"
docker exec -i -e PGPASSWORD=app_password thm-scratch-pg psql -h 127.0.0.1 -U app -d app_db -At -c "$1"
