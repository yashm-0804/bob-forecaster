# Deploying the console

The deployed service is the operator console and its API, serving
**precomputed runs**. Nothing at request time touches Earth Engine, AWS or
OpenStreetMap, so the image is small and has no credentials in it.

## Before you deploy

1. Regenerate the runs you want to show. They are baked into the image.
   ```bash
   python -m agent.watch --replay MONTHA 2025 --region andhra
   python -m agent.watch --replay FANI 2019 --region odisha
   python -m telemetry.simulate MONTHA 2025 --region andhra
   ./check.sh
   ```
2. Install the Google Cloud CLI and sign in: `gcloud auth login`, then
   `gcloud config set project <your-project-id>`.

## Deploy

Make two access codes first, one for officers in the console and one for
field gateways that post telemetry, and keep them in Secret Manager so they
never appear in the service's configuration or your shell history:

```bash
gcloud services enable secretmanager.googleapis.com
python3 -c "import secrets; print(secrets.token_urlsafe(24), end='')" \
  | gcloud secrets create bob-operator-token --data-file=-
python3 -c "import secrets; print(secrets.token_urlsafe(24), end='')" \
  | gcloud secrets create bob-ingest-token --data-file=-

# Let the service's identity read them (Cloud Run's default: the Compute
# Engine default service account).
SA="$(gcloud projects describe "$(gcloud config get-value project)" \
      --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
for s in bob-operator-token bob-ingest-token; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
done

# The audit trail, in BigQuery: approvals outlive the instance. Once, from a
# machine signed in to the project (see "Approvals in BigQuery" below):
#   python scripts/bigquery_setup.py "$(gcloud config get-value project)"
PROJECT="$(gcloud config get-value project)"
bq add-iam-policy-binding --member="serviceAccount:$SA" \
  --role=roles/bigquery.dataEditor "$PROJECT:bob_forecaster"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA" --role=roles/bigquery.jobUser

gcloud run deploy project-cyclops \
  --source . \
  --region asia-south1 \
  --memory 512Mi \
  --max-instances 1 \
  --allow-unauthenticated \
  --set-env-vars "BOB_AUDIT_STORE=bigquery,BOB_BQ_AUDIT_TABLE=$PROJECT.bob_forecaster.audit_events" \
  --set-secrets "BOB_OPERATOR_TOKEN=bob-operator-token:latest,BOB_INGEST_TOKEN=bob-ingest-token:latest"
```

To read the operator code when you need to type it into the console:
`gcloud secrets versions access latest --secret=bob-operator-token`.
Secret Manager's free tier covers a handful of secrets and ten thousand reads
a month, far more than this uses.

Cloud Build builds the `Dockerfile` and Cloud Run serves it; the command prints
the URL. `asia-south1` is Mumbai. `.gcloudignore` keeps `.env` and caches out
of the upload.

Check the codes took effect: `curl <url>/api/health` should report
`"writes": {"operator": "token", "telemetry": "token"}`. If it says
`"disabled"`, the deployment is refusing every write because a code is
missing -- it fails closed rather than open.

## What to know first

- **It costs money on your account.** Cloud Run and Cloud Build have free
  tiers and a lightly used demo usually stays inside them, but it is billed to
  your project. Check the billing page after the first day.
- **Approvals persist in BigQuery; telemetry does not.** With the settings
  above, every approval, withdrawal and dispatch attempt is appended to
  `bob_forecaster.audit_events` and read back when the server starts, so a
  recycled instance keeps them (`/api/health` reports `"bigquery": true`).
  Without them the audit log is a file in `/tmp`, lost with the instance
  (`"ephemeral": true`). Telemetry is still a file in `/tmp` either way.
  `--max-instances 1` matters for both: the server is the trail's only
  writer, and checking an approval and recording a dispatch are one step
  under its lock, which holds only within one instance.
- **Anyone with the URL can read; only officers can act.** With sign-in
  configured (next section), approving, withdrawing, dispatching and reading
  the audit log need a Google sign-in from an address on `BOB_OPERATORS`, and
  each is recorded against that verified account. Without it they need the
  shared operator code, and the name on an approval is whatever the officer
  types. Posting telemetry needs the ingest code either way: gateways are
  machines, not people.
- **Writes are rate limited**, counted only after the access code checks
  out: 30 approvals, revocations or dispatches and 1,200 telemetry posts a
  minute per code (`BOB_OPERATOR_WRITES_PER_MIN`,
  `BOB_TELEMETRY_WRITES_PER_MIN`); reads that need the code, such as the
  audit log, do not count. Wrong codes are limited separately per address
  (`BOB_FAILED_AUTH_PER_MIN`). That bounds the load of wrong attempts, not the
  odds of a guess: the right code is always let through, so that no one can
  lock officers out by guessing wrong. **What defeats guessing is the code's
  length**: the generator above makes 32 characters (192 bits), and the
  server refuses to run with a code shorter than 16 characters, or with
  characters outside ASCII (which no request can send). `/api/health` names
  the setting; the server log says what is wrong with it. For a real
  defence against floods, put Cloud Armor in front. The image runs uvicorn
  with `--no-proxy-headers`, so the address the limits count is always the
  connection's, never an `X-Forwarded-For` header, which any caller can
  write (tested in `tests/test_proxy_headers.py`). Behind Cloud Run's front
  end that address is the proxy's, so the wrong-code limit is in effect one
  limit for the whole instance: stricter, not looser. Not verified on a
  deployment.
- **It answers only to its own names.** Requests whose `Host` is not
  `localhost`, `127.0.0.1`, `[::1]` or, on Cloud Run, a `*.run.app` name get
  400. This is what stops a page on another domain from reaching a console
  through DNS rebinding. Behind a custom domain, set `BOB_ALLOWED_HOSTS`
  (comma-separated; `*.example.org` for subdomains), which replaces the
  default list. On Cloud Run every response also carries
  `Strict-Transport-Security`. The check is aimed at browsers: a client that
  is not a browser can send any `Host` it likes, and meets the access codes
  instead.
- **The image refuses writes without codes, wherever it runs.** It sets
  `BOB_REQUIRE_TOKENS=1`, because it listens on every interface; only a
  checkout run with `run.sh`, which listens on this machine alone, is open
  without codes.
- **The API docs are off.** `/docs` and `/redoc` load their interface from a
  CDN at an unpinned version, so on Cloud Run they and the schema they read
  (`/openapi.json`) answer 404 unless `BOB_API_DOCS=1`. Locally they are on,
  under a content policy of their own.
- **A damaged run file costs only that run.** Run files are checked when
  read. One that cannot be read or is not shaped like a run is not offered
  to the console, answers 503 if asked for, and is listed in `/api/health`;
  approvals on the other runs carry on.
- **A node registry is a file.** `BOB_NODE_REGISTRY` names a file holding a
  JSON list of node ids; bake it into the image or mount it. If it cannot
  be read, telemetry is refused (503) rather than opened to every node, and
  `/api/health` reports `"ok": false` with the reason.
- **The map needs WebGL and the CARTO basemap.** MapLibre itself is served
  from the image (`web/vendor`), so no third-party script runs in the page;
  the basemap tiles come from CARTO. Without WebGL or the basemap the console
  draws its own offline map from the run data.

## Officers sign in with Google

Firebase Authentication, free (the Spark plan needs no billing):

1. In the Firebase console, add Firebase to the Google Cloud project, enable
   **Authentication → Sign-in method → Google**, and register a web app.
2. Give the server its configuration, and the officers allowed to act:
   ```bash
   BOB_FIREBASE_PROJECT=<project id>          # firebaseConfig.projectId
   BOB_FIREBASE_API_KEY=<firebaseConfig.apiKey>
   BOB_FIREBASE_APP_ID=<firebaseConfig.appId>
   BOB_OPERATORS=k.ramesh@osdma.gov.in,@seoc.example.org   # addresses, or @domain
   ```
   On Cloud Run, add them to `--set-env-vars`. The web configuration is
   public by design; Firebase sends it to every browser. Without
   `BOB_OPERATORS` no one may act, and `/api/health` says so: otherwise any
   Google account could approve.
3. Add the deployment's address (`<service>-<hash>.a.run.app`) under
   **Authentication → Settings → Authorized domains**. `localhost` is there
   already.

The server checks each request's token itself (`api/identity.py`): signed by
Google for this project, unexpired, a Google sign-in, a verified address on
the list. The console loads Firebase from this server (`web/vendor/firebase`);
its content policy then also allows Google's sign-in helper
(`apis.google.com`) and the project's sign-in frame, and only when sign-in is
configured. Tested: the token rules in `tests/test_identity.py`, with a key
made for the test; the console's side in `tests/js/console.test.mjs`; and in
Chrome, against the real Firebase project, that the library loads under the
policy and the Google sign-in window opens. Completing a sign-in needs a
person at the Google window, so no automated test does it.

## Approvals in BigQuery

The audit trail lives in one BigQuery table, and stays within BigQuery's free
tier, with no billing account:

- **Writes are load jobs**, which are free in every tier. The sandbox (a
  project without billing) refuses SQL `INSERT` and streaming. Measured from
  a laptop in India to `asia-south1`: five writes took 2.4 to 2.9 seconds
  each, and the very first load job 8.6 seconds. An approval takes that
  long, and the console says "Recording…" meanwhile. It is reported as recorded only once
  BigQuery has it; if BigQuery refuses, the API answers 503 and nothing is
  recorded.
- **Reads cost nothing.** The server reads the whole trail once when it
  starts, with `tabledata.list`, which runs no query (0.7 seconds for a
  restart in the same test), and then answers from memory. `/api/health`
  checks that the table is still there (0.1 seconds).
- **In the sandbox every table expires within 60 days,** and BigQuery refuses
  a later expiry ("Table expiration time must be less than 60 days while in
  sandbox mode"). The server moves the expiry forward when it starts, and
  after writes at most once a day. A deployment that neither starts nor
  records anything for 60 days loses the table. Enabling billing and running
  `python scripts/bigquery_setup.py PROJECT --no-expiry` removes the expiry.
- **Limits.** BigQuery allows 1,500 load jobs per table per day, so 1,500
  audit events a day; past that, writes answer 503 until the quota refills.
- **Credentials.** On Cloud Run, the service account, given the two roles in
  the deploy commands above. On a laptop, the Earth Engine sign-in works if
  it carries the `cloud-platform` scope, as `earthengine authenticate` grants
  by default; or use `gcloud auth application-default login`.
- **Tested** against the real service: `BOB_NETWORK_TESTS=1
  BOB_BQ_TEST_DATASET=PROJECT.bob_forecaster pytest -k real_bigquery` makes a
  table, approves, dispatches, withdraws, reads the trail back as a restarted
  server would, and deletes the table. The rest of `tests/test_audit_bigquery.py`
  runs the SQLite log's rules against both stores, with a stand-in for
  BigQuery's REST API.

## Verified locally

Docker is not installed on the development machine, so the image itself has
not been built here. `.github/workflows/ci.yml` defines a job that builds and
smoke-tests it, but the repository has no remote yet, so that job has never
run. Its checks are `scripts/smoke_test.sh`: one container started with
throwaway codes must be healthy with writes protected by code, and one
started without codes must fail closed. `tests/test_ci_smoke.py` runs the
same script against a server started with the Dockerfile's settings and
flags and the settings `ci.yml` gives each container. That test found the
job's first version could never pass: it expected a healthy server from an
image started without codes.

Locally, the image's contents were reproduced instead: a clean Python
3.12 environment installed only from `requirements-serve.lock`, running only
the files the `Dockerfile` copies, with its environment:

| Configuration | `/api/health` writes | Approve without code | Approve with code |
|---|---|---|---|
| The image (`BOB_REQUIRE_TOKENS=1`), no codes | disabled | 503 | 503 |
| The image on Cloud Run (`K_SERVICE` set), no codes | disabled | 503 | 503 |
| The image, both codes set (32 characters) | token | 401 | 200 |
| The image, a code shorter than 16 characters | disabled | 503 | 503 |

The console page, the runs and the telemetry report answered 200 in every
configuration. A checkout on a laptop, started with `run.sh` and no codes, is
open (200 without a code), and says so in `/api/health`.
