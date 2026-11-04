#!/usr/bin/env bash
# Laptop side of the extra tests (plan section 5), all scenario B (delay 100 ms):
#   1. cold spike: 15 min without traffic, then 0 -> 500 VUs in 30 s and 2 min at 500, every variant
#   2. pool size: web-pool at 200 VUs with POOL_MAX 5, 10, 20 (each one is a new revision)
#   3. maxEnvironments as a DB guard: web-pool at 500 VUs, cap 20 then cap 2
# The LwfApp redeploys run from here; the load runs on the loadgen.
# Usage: AWS_PROFILE=... scripts/extras.sh [cold] [pool] [maxenv]
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/loadgen_lib.sh

CDK="npx --yes aws-cdk@2.1147.0"
PAUSE=60

deploy_app() {
  log "[deploy] LwfApp $*"
  local out
  out=$(cd infra && $CDK deploy LwfApp --exclusively --require-approval never "$@" 2>&1) || true
  grep -E "✅|❌|Deployment time|Error" <<< "$out" || true
  # A failed deploy would make the next runs measure the wrong configuration: stop here.
  grep -q "✅" <<< "$out"
}

one() {
  run_unit "lwf-$1-$6-$(date -u +%H%M%S)" "load/one.sh $*"
}

steps=${*:-cold pool maxenv}

if [[ $steps == *cold* ]]; then
  log "[cold] recycle Event Function environments, then 15 min without traffic"
  $PY scripts/reset_envs.py
  sleep 900
  for v in web-pool event-direct event-proxy; do
    terminate_leftovers "cold-$v"
    one "$v" 500 100 2m30s spike coldspike
    sleep "$PAUSE"
  done
fi

if [[ $steps == *pool* ]]; then
  for n in 5 10 20; do
    deploy_app -c pool_max="$n"
    terminate_leftovers "pool$n"
    one web-pool 200 100 2m constant "warmup-pool$n"
    sleep "$PAUSE"
    one web-pool 200 100 3m constant "pool$n"
    sleep "$PAUSE"
  done
fi

if [[ $steps == *maxenv* ]]; then
  # Back to the default revision (POOL_MAX 10). maxEnvironments is an endpoint setting: no new revision.
  deploy_app
  terminate_leftovers maxenv20
  one web-pool 200 100 2m constant warmup-maxenv
  sleep "$PAUSE"
  one web-pool 500 100 3m constant maxenv20
  sleep "$PAUSE"
  deploy_app -c max_environments=2
  terminate_leftovers maxenv2
  one web-pool 500 100 3m constant maxenv2
  deploy_app
fi
log "[extras] done"
