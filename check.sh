#!/usr/bin/env bash
# Everything that must pass before a commit: lint, types, tests with a
# coverage floor, and a dependency audit. CI runs this script itself, so the
# two cannot drift apart.
#
#   ./check.sh                                  the checkout's .venv
#   BOB_PYTHON_BIN=/path/to/venv/bin ./check.sh another environment (CI)
set -euo pipefail
cd "$(dirname "$0")"
BIN="${BOB_PYTHON_BIN:-.venv/bin}"
PY="$BIN/python"
export SSL_CERT_FILE="$($PY -m certifi)"

echo "== lint";  "$BIN/ruff" check .
echo "== types"; "$BIN/pyright" --pythonpath "$PY"
# The console's JavaScript. Needs Node: optional on a laptop, required in CI.
if ! command -v npx >/dev/null && [ -n "${CI:-}" ]; then
  echo "Node is required in CI"; exit 1
fi
if command -v npx >/dev/null; then
  echo "== js lint"; npx --yes eslint@10.11.0 web/app.js web/map-loader.mjs web/auth-loader.mjs tests/js tests/e2e scripts/screenshots.mjs
  echo "== js types"; npx --yes -p typescript@5.9.3 tsc --noEmit --allowJs --checkJs --strict --target es2022 --lib es2022,dom --skipLibCheck web/app.js tests/js/app-globals.d.ts
  echo "== js tests with coverage"
  npx --yes c8@12.0.0 --temp-directory .cache/c8 --report-dir .cache/c8/report --check-coverage --lines 94 --branches 80 --functions 90 --include web/app.js --reporter=text-summary \
    node tests/js/console.test.mjs
else
  echo "== js lint: skipped, Node is not installed"
fi
echo "== tests"; $PY -m pytest tests/ -q --cov --cov-report=term:skip-covered --cov-fail-under=92
echo "== security"
# Static analysis: Bandit's rules, as ruff implements them, on application code
# alone -- the lint step above already enforces them; this reports them apart.
echo "-- code (Bandit rules)"; "$BIN/ruff" check --select S --exclude tests .
# Credentials: every tracked file, every commit in history, and the values in
# the local .env if there is one; .env must be ignored everywhere.
echo "-- secrets"; $PY scripts/secret_scan.py
# The JavaScript libraries: vendored files as their manifests say, no known
# advisories (OSV), and nothing loaded by the console from another origin.
echo "-- javascript libraries"; $PY scripts/js_audit.py
# Known vulnerabilities in the locked dependencies. A cache of its own: the
# shared user cache is also written by other pip-audit versions, which leaves
# entries this one cannot read.
echo "-- dependencies"; "$BIN/pip-audit" --cache-dir .cache/pip-audit -r requirements.txt -r requirements-serve.txt
