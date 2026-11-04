#!/usr/bin/env bash
# One load run: pg_stat_activity sampler + k6, results in results/raw/<run>/.
# Usage: scripts/run_one.sh <variant> <url> <vus> <delay_ms> <duration> [mode] [label]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

variant=$1 url=$2 vus=$3 delay=$4 duration=$5 mode=${6:-constant} label=${7:-}
run="$(date -u +%Y%m%dT%H%M%SZ)_${variant}_d${delay}_v${vus}${label:+_$label}"
out="results/raw/$run"
mkdir -p "$out"

start=$(date -u +%Y-%m-%dT%H:%M:%SZ)
scripts/sample_pg.sh "$out/pg_activity.csv" &
sampler=$!
trap 'kill $sampler 2>/dev/null || true' EXIT

TARGET_URL="$url" VARIANT="$variant" VUS="$vus" DURATION="$duration" DELAY_MS="$delay" MODE="$mode" \
  k6 run --quiet --summary-export "$out/k6.json" load/run.js > "$out/k6.summary.txt" 2> "$out/k6.log" || true

kill $sampler 2>/dev/null || true
end=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# No 200 responses means no envId lines: grep must not stop the matrix under pipefail.
envs=$({ grep -o 'ENV [0-9a-f-]*' "$out/k6.log" || true; } | sort -u | wc -l | tr -d ' ')
cat > "$out/run.json" <<EOF
{"run": "$run", "variant": "$variant", "vus": $vus, "delay_ms": $delay, "duration": "$duration",
 "mode": "$mode", "label": "$label", "start": "$start", "end": "$end", "distinct_env_ids": $envs}
EOF
echo "$run done ($start -> $end), distinct envIds: $envs"

# Copy each run to S3 as soon as it ends: the loadgen disk is not the only copy.
if [[ -n "${RESULTS_BUCKET:-}" ]]; then
  aws s3 cp --recursive --quiet "$out" "s3://$RESULTS_BUCKET/results/raw/$run/" || echo "$run: upload to S3 failed"
  [[ -f results/raw/matrix.log ]] && aws s3 cp --quiet results/raw/matrix.log "s3://$RESULTS_BUCKET/results/raw/matrix.log" || true
fi
