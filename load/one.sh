#!/usr/bin/env bash
# One run by variant name, URL taken from .env. Used by scripts/extras.sh through SSM.
# Usage: load/one.sh <variant> <vus> <delay_ms> <duration> <mode> <label>
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

case "$1" in
  event-direct) url=$URL_EVENT_DIRECT ;;
  event-proxy)  url=$URL_EVENT_PROXY ;;
  web-pool)     url=$URL_WEB_POOL ;;
esac
scripts/run_one.sh "$1" "$url" "$2" "$3" "$4" "$5" "$6"
