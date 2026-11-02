#!/usr/bin/env bash
# Laptop side of the matrix: for each variant, recycle the Event Function environments,
# wait until their DB connections are gone, then run that variant's block on the loadgen.
# Usage: AWS_PROFILE=... scripts/orchestrate.sh [variant ...]
set -euo pipefail
cd "$(dirname "$0")/.."
export AWS_REGION=${AWS_REGION:-eu-west-1}
PY=${PY:-.venv/bin/python}

iid=$(aws cloudformation describe-stacks --stack-name LwfNetwork \
  --query "Stacks[0].Outputs[?OutputKey=='LoadgenInstanceId'].OutputValue" --output text)

on_loadgen() {
  local params cid st
  params=$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]],"executionTimeout":["600"]}))' "$1")
  cid=$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
    --parameters "$params" --query Command.CommandId --output text)
  while true; do
    st=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query Status --output text 2>/dev/null || echo Pending)
    case $st in Pending|InProgress|Delayed) sleep 5 ;; *) break ;; esac
  done
  aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query StandardOutputContent --output text
}

psql_loadgen() {
  on_loadgen "cd /root/lab && . ./.env && psql \"\$DB_URL\" -Atc \"$1\""
}

# event-proxy last: RDS Proxy keeps an idle pool of DB connections after its run.
for v in "${@:-event-direct web-pool event-proxy}"; do
  for variant in $v; do
    echo "$(date -u +%H:%M:%S) [$variant] recycle Event Function environments"
    $PY scripts/reset_envs.py
    sleep 60
    # Same starting point for every variant: close what is left of the app user's connections
    # (old Event environments, RDS Proxy's idle pool). The proxy reopens them on demand.
    killed=$(psql_loadgen "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE backend_type = 'client backend' AND usename = 'labadmin' AND pid <> pg_backend_pid()" | tr -dc '0-9')
    sleep 5
    left=$(psql_loadgen "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()" | tr -dc '0-9')
    echo "$(date -u +%H:%M:%S) [$variant] terminated $killed leftover connections, $left client connections remain"
    unit="lwf-$variant-$(date -u +%H%M%S)"
    on_loadgen "cd /root/lab && systemd-run --unit=$unit -p WorkingDirectory=/root/lab -E VARIANTS=$variant bash -c 'load/matrix.sh --run >> results/raw/matrix.log 2>&1'"
    echo "$(date -u +%H:%M:%S) [$variant] started unit $unit"
    while [[ "$(on_loadgen "systemctl is-active $unit" | tr -d '[:space:]')" == active ]]; do sleep 120; done
    echo "$(date -u +%H:%M:%S) [$variant] finished: $(on_loadgen "systemctl is-active $unit")"
  done
done
