#!/usr/bin/env bash
# Every 5 s, counts lab connections in pg_stat_activity (direct to the writer).
# Connections opened by RDS Proxy may not carry the client's application_name:
# they are grouped by usename and client_addr as well.
# Usage: scripts/sample_pg.sh <out.csv>   (DB_URL from .env, points at the writer, not the proxy)
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

out=$1
echo "ts,application_name,usename,client_addr,state,count" > "$out"
while true; do
  psql "$DB_URL" -AtqF, -c "
    SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
           coalesce(application_name, ''), usename, coalesce(host(client_addr), ''),
           coalesce(state, ''), count(*)
    FROM pg_stat_activity
    WHERE backend_type = 'client backend'
      AND pid <> pg_backend_pid()
      AND (application_name LIKE 'lab-%' OR usename = 'rdsproxyadmin' OR usename = 'labadmin')
    GROUP BY 2, 3, 4, 5
    ORDER BY 2, 3, 4, 5" >> "$out" 2>/dev/null
  sleep 5
done
