#!/usr/bin/env bash
# Prints (and with --run executes) the load matrix: 3 variants x 2 scenarios x 4 levels.
# Variants run one after the other, never in parallel. Needs the URLs in .env on the loadgen.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

VARIANTS=(event-direct event-proxy web-pool)
DELAYS=(0 100)
LEVELS=(10 50 200 500)
DURATION=${DURATION:-3m}
PAUSE=${PAUSE:-60}

url_for() {
  case "$1" in
    event-direct) echo "$URL_EVENT_DIRECT" ;;
    event-proxy)  echo "$URL_EVENT_PROXY" ;;
    web-pool)     echo "$URL_WEB_POOL" ;;
  esac
}

runs=0
for d in "${DELAYS[@]}"; do for v in "${VARIANTS[@]}"; do for l in "${LEVELS[@]}"; do
  runs=$((runs + 1))
  printf '%2d  delay=%-3s  %-12s  vus=%s\n' "$runs" "$d" "$v" "$l"
done; done; done
minutes=${DURATION%m}
total=$((runs * minutes + (runs - 1) * PAUSE / 60))
echo "runs: $runs x $DURATION, pause ${PAUSE}s -> about ${total} min"

[[ "${1:-}" == "--run" ]] || exit 0

for d in "${DELAYS[@]}"; do for v in "${VARIANTS[@]}"; do for l in "${LEVELS[@]}"; do
  scripts/run_one.sh "$v" "$(url_for "$v")" "$l" "$d" "$DURATION"
  sleep "$PAUSE"
done; done; done
