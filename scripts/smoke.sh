#!/usr/bin/env bash
# The three variants must return the same JSON for the same id (apart from variant and envId).
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

for id in 1 4242 999999; do
  for v in event-direct event-proxy web-pool; do
    case $v in
      event-direct) url=$URL_EVENT_DIRECT ;;
      event-proxy)  url=$URL_EVENT_PROXY ;;
      web-pool)     url=$URL_WEB_POOL ;;
    esac
    code=$(curl -sS -o "$tmp/$v.raw" -w '%{http_code}' -H "x-lab-token: $LAB_TOKEN" "${url%/}/customer/$id")
    [[ $code == 200 ]] || { echo "FAIL $v id=$id http=$code"; fail=1; continue; }
    jq -S 'del(.variant, .envId)' "$tmp/$v.raw" > "$tmp/$v.json"
  done
  for v in event-proxy web-pool; do
    if diff -q "$tmp/event-direct.json" "$tmp/$v.json" > /dev/null; then
      echo "OK   id=$id event-direct == $v"
    else
      echo "DIFF id=$id event-direct != $v"; diff "$tmp/event-direct.json" "$tmp/$v.json" || true; fail=1
    fi
  done
done

exit $fail
