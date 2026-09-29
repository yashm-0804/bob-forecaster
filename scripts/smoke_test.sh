#!/usr/bin/env bash
# What CI checks against the running image, kept here so that
# tests/test_ci_smoke.py can run the same checks against a server started
# the way the image starts it. CI's own copy of the checks once expected a
# healthy server from an image started without access codes, which the image
# refuses by design; nothing ran it, so nothing noticed.
#
#   scripts/smoke_test.sh http://localhost:8080 configured   # started with both codes
#   scripts/smoke_test.sh http://localhost:8081 no-codes     # started with none
set -euo pipefail
URL=$1
MODE=$2

for _ in $(seq 1 30); do curl -fs "$URL/api/health" > /dev/null && break; sleep 1; done
health=$(curl -fs "$URL/api/health")
case "$MODE" in
  configured)
    grep -q '"ok":true' <<< "$health"
    grep -q '"operator":"token"' <<< "$health"
    grep -q '"telemetry":"token"' <<< "$health"
    ;;
  no-codes)
    # Fails closed, and says so: unhealthy, writes disabled, a write refused.
    grep -q '"ok":false' <<< "$health"
    grep -q '"operator":"disabled"' <<< "$health"
    status=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
      -d '{"operator":"CI Smoke"}' "$URL/api/advisory/any/approve")
    test "$status" = 503
    ;;
  *)
    echo "usage: $0 <url> configured|no-codes" >&2
    exit 2
    ;;
esac
curl -fs "$URL/api/run/montha/48" > /dev/null
# Read whole, then searched: grep -q stops at the first match, and curl,
# still writing, would fail (exit 23) under pipefail.
page=$(curl -fs "$URL/")
grep -q '<title>' <<< "$page"
curl -fs "$URL/static/app.js" > /dev/null
echo "smoke test passed ($MODE)"
