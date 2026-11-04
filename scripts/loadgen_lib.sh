# Laptop helpers shared by orchestrate.sh and extras.sh: run commands on the loadgen through SSM.
# Every AWS call retries: a sleeping laptop or a short network drop must not end a long run.
# shellcheck shell=bash

export AWS_REGION=${AWS_REGION:-eu-west-1}
PY=${PY:-.venv/bin/python}

iid=$(aws cloudformation describe-stacks --stack-name LwfNetwork \
  --query "Stacks[0].Outputs[?OutputKey=='LoadgenInstanceId'].OutputValue" --output text)

log() { echo "$(date -u +%H:%M:%S) $*"; }

on_loadgen() {
  local params cid st
  params=$(python3 -c 'import json,sys; print(json.dumps({"commands":[sys.argv[1]],"executionTimeout":["600"]}))' "$1")
  until cid=$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
    --parameters "$params" --query Command.CommandId --output text); do sleep 30; done
  while true; do
    st=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query Status --output text 2>/dev/null || echo Pending)
    case $st in Pending|InProgress|Delayed) sleep 5 ;; *) break ;; esac
  done
  aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query StandardOutputContent --output text
}

psql_loadgen() {
  on_loadgen "cd /root/lab && . ./.env && psql \"\$DB_URL\" -Atc \"$1\""
}

# Close what is left of the app user's connections (old Event environments, RDS Proxy's idle pool).
terminate_leftovers() {
  local killed left
  killed=$(psql_loadgen "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE backend_type = 'client backend' AND usename = 'labadmin' AND pid <> pg_backend_pid()" | tr -dc '0-9')
  sleep 5
  left=$(psql_loadgen "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()" | tr -dc '0-9')
  log "[$1] terminated $killed leftover connections, $left client connections remain"
}

# Runs a command in /root/lab as a systemd unit (SSM would kill a background process) and waits for it.
run_unit() {
  local unit=$1 cmd=$2 state
  on_loadgen "cd /root/lab && systemd-run --unit=$unit -p WorkingDirectory=/root/lab ${3:-} bash -c '$cmd >> results/raw/matrix.log 2>&1'" >/dev/null
  log "[$unit] started"
  while true; do
    state=$(on_loadgen "systemctl is-active $unit" 2>/dev/null | tr -d '[:space:]') || state=unknown
    [[ "$state" == active || "$state" == unknown ]] || break
    sleep 60
  done
  log "[$unit] finished: $state"
}
