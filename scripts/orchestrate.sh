#!/usr/bin/env bash
# Laptop side of the matrix: for each variant, recycle the Event Function environments,
# wait until their DB connections are gone, then run that variant's block on the loadgen.
# Usage: AWS_PROFILE=... scripts/orchestrate.sh [variant ...]
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/loadgen_lib.sh

# event-proxy last: RDS Proxy keeps an idle pool of DB connections after its run.
for v in "${@:-event-direct web-pool event-proxy}"; do
  for variant in $v; do
    log "[$variant] recycle Event Function environments"
    $PY scripts/reset_envs.py
    sleep 60
    # Same starting point for every variant. The proxy reopens its connections on demand.
    terminate_leftovers "$variant"
    run_unit "lwf-$variant-$(date -u +%H%M%S)" "load/matrix.sh --run" "-E VARIANTS=$variant"
  done
done
