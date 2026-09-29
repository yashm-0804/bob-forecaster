#!/usr/bin/env bash
# Start the cyclone impact console.
#
# Wraps the two things that otherwise bite on a fresh macOS checkout: the
# missing root certificates on python.org Python builds, and generating a
# replay before the console has anything to show.
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
PORT="${PORT:-8077}"
STORM="${STORM:-MONTHA}"
LEAD="${LEAD:-48}"

[ -x "$PY" ] || { echo "No venv. Run: python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-dev.lock"; exit 1; }

# Local secrets (GEMINI_API_KEY), if present. The file is git-ignored.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

# python.org builds ship without CA certs, so every https fetch fails until this is set.
export SSL_CERT_FILE="$($PY -m certifi)"

RUN_FILE="data/runs/$(echo "$STORM" | tr '[:upper:]' '[:lower:]')_${LEAD}h.json"
if [ ! -f "$RUN_FILE" ]; then
  echo "Generating $STORM replay at T-${LEAD}h (first run downloads IMD track + OSM assets, then caches)..."
  $PY -c "import pipeline; pipeline.export(pipeline.run('$STORM', lead_hours=$LEAD))"
fi

echo
echo "  Console:  http://localhost:$PORT"
echo "  API docs: http://localhost:$PORT/docs"
echo
# --no-proxy-headers: X-Forwarded-For is whatever a caller writes; trusting it
# would let one caller pose as many to the wrong-code limit.
exec $PY -m uvicorn api.main:app --port "$PORT" --no-proxy-headers
