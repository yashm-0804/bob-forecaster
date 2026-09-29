# How it fits together

Two paths matter. A **forecast cycle** turns a storm into scored assets and
drafted advisories, written as one JSON file per cycle. A **console session**
reads those files and lets an officer approve and dispatch. They meet only at
the files in `data/runs` and the audit log.

## A forecast cycle

`python -m agent.watch --replay MONTHA 2025 --region andhra` calls
`agent.watch.run_cycle` once for each IMD lead time (T−72, 48, 24 and 12 h).
Each call runs `pipeline.run`:

| Step | Code | In | Out |
|---|---|---|---|
| Storm | `ingest/tracks.py` | IMD best track (imdtrack) | `Storm`: positions, winds, pressure, landfall index |
| Grid and terrain | `hazard/holland.make_grid`, `hazard/terrain.py` | Bounding box; Copernicus DEM via Earth Engine or AWS, cached | 0.02° grid; elevation and distance to coast |
| Ensemble | `pipeline._ensemble`: `ingest/weatherlab.py` or `ingest/ensemble.perturb` | WeatherNext 3 forecast issued before landfall, else the best track perturbed by IMD's error | Member tracks, plus a provenance record |
| Wind | `hazard/holland.swath` | Each member | Peak gust per cell, per member |
| Surge | `hazard/surge_screen.surge_field_m` | Each member's landfall and the terrain | Storm-tide depth per cell (a screen, not a simulation) |
| Rain | `pipeline._rainfall`: `ingest/gfs.py` or `hazard/rainfall.accumulation_mm` | GFS 72 h forecast (2021 on), else R-CLIPER | Rain per cell, per member; ponded depth |
| Exposure | `exposure/osm.py` | OpenStreetMap through Overpass, cached per class | Substations, hospitals, shelters, roads, masts |
| Impact | `impact/rollup.score_all`, `impact/fragility.py`, `impact/consequence.py` | Hazard members and assets | Per asset: failure probability (mean and spread), driver, criticality, expected consequence, severity band |
| Advisories | `advisory/cap.draft`, then `advisory/gemini.enhance_all`, then `Advisory.sealed` | Red and orange assets by department | CAP 1.2 advisories. Gemini may reword and translate; `advisory/numbers.py` rejects text with a number, unit, scale or number word no computed fact accounts for, within the limits the README lists. The identifier carries a fingerprint of the final text |
| Triggers | `impact/triggers.py` | Wind and rain members, observed indices | Payout probabilities per zone, basis risk |
| Checks | `verify/ensemble_skill.py`, `pipeline._observe` with `verify/satellite.py` and `verify/observed_skill.py` | The best track; GPM IMERG, Sentinel-1 and VIIRS through Earth Engine, when reachable | Track skill; rain, flood and outage scores, or a reason they could not run |
| Export | `pipeline.export` | Everything above | `data/runs/<storm>_<lead>h.json`: summary, layers, the top 400 assets, every red asset's id, advisories with CAP XML |

`agent.watch.diff_cycles` then compares the new file with the previous
cycle's and stores the result under `changes`: assets newly red, advisories
escalated or withdrawn. A cycle on placeholder terrain is refused
(`DegradedCycle`) rather than published.

Most external sources degrade with a reason instead of an exception:
Weather Lab falls back to the perturbed ensemble, GFS to R-CLIPER, Earth
Engine terrain to AWS, and a missing satellite pass costs only its own check.
The provenance of each is recorded in the run's summary. Exposure has no
fallback: with neither Overpass nor a cached pull of an asset class,
`exposure/osm.py` raises and the cycle fails. `agent.watch` records any
failed cycle with its reason, keeps the last good cycle as the baseline for
the next diff, carries on with the remaining cycles, and exits non-zero at
the end.

Run files are written beside their final name and moved into place, so the
console, which serves `data/runs` while cycles run, never reads half a
file.

## A console session

The console is `web/index.html` (markup and styles) and `web/app.js`
(behaviour), served by `api/main.py`. Every request passes the checks in
`api/guard.py` first; run files are read through `api/run_store.py`.

1. `boot()` fetches `/api/runs`, then the run named in the URL, and checks
   it has the shape the panels need. The panels render from that one
   payload. The server checks each run file's shape when it reads it; one
   that fails is left out of `/api/runs` and reported by `/api/health`.

   The map is MapLibre GL JS 6, vendored in `web/vendor/maplibre-gl` (see its
   `VENDOR.json`) and served from this server; `web/map-loader.mjs` loads it,
   as it is an ES module and `app.js` a classic script. Only the basemap
   (CARTO) comes from elsewhere. Without WebGL, the module or the basemap,
   the console draws its own map on a canvas from the run data.
2. **Approve** opens a dialog for the officer's name.
   `POST /api/advisory/{id}/approve` passes through, in this order:
   - the body-size limit;
   - the host check (`BOB_ALLOWED_HOSTS`), which is what makes the next one
     hold against DNS rebinding;
   - the same-origin check;
   - `api/access.require`, which checks the code if one is configured (and
     refuses one shorter than 16 characters), then the write budget;
   - validation of the name.

   The run the console reads merges approval state from the audit log. If
   the log cannot be read, the run is still served, with approval state
   unknown and a notice; writes are refused with 503 and nothing recorded.

   It then appends a row to the audit log, never updated or deleted: a
   SQLite file (`api/audit.py`), or a BigQuery table (`api/bigquery_audit.py`,
   written by load jobs and read once at start; see `DEPLOY.md`). A 401 makes the dialog ask for the access code.
   **Withdraw** is the same path to `/revoke`, and records a revocation
   only if an approval stands; otherwise it is refused with 409 and nothing
   is written.
3. **Dispatch** (`POST /api/advisory/{storm}/{lead}/{id}/dispatch`) finds the
   standing approval in the audit log and records the attempt in the same
   step (`AuditLog.dispatch`), so a withdrawal cannot land in between. With none, it refuses with 409 and
   records the refusal. With one, it records who dispatched and who approved,
   and returns the payload that would be sent. Nothing is ever sent:
   every alert is `status=Exercise`.

## Telemetry

`POST /api/telemetry` goes to `telemetry/ingest.TelemetryStore.ingest`:

1. `parse` checks every field's type, position and time, and turns anything
   that cannot be a reading into a 422.
2. The optional node registry and the duplicate check come next. A registry
   that is configured but unreadable refuses telemetry with 503. From the
   duplicate check to the insert, the store holds its lock, so readings
   posted together are checked in turn, each against those stored before it.
3. `telemetry/qc.run` flags readings by channel: range, spike, flatline,
   neighbour disagreement, drift, missing channels, and stale timestamps.
   Neighbours are the fusable readings within 40 km and 20 minutes, found
   through a bounding box in SQL. Their pressure is fitted as a plane, or as
   a line when they lie along one (a coast road), or taken as the median when
   they are all in one place.
4. The reading is stored with its flags. Flagged readings are kept but not
   fused.

`telemetry/simulate.py` drives the same path with a simulated network and
injected faults, and writes `data/telemetry/<storm>_report.json` for the
console.

## Where state lives

| State | Where | Durable |
|---|---|---|
| Forecast runs | `data/runs/*.json`, committed | Yes |
| Approvals and dispatches | SQLite at `BOB_AUDIT_DB` | On a laptop, yes. On Cloud Run, in `/tmp`, so it is lost on recycle |
| Telemetry | SQLite at `BOB_TELEMETRY_DB` | As above |
| Downloaded data | `data/cache/`, not committed | Rebuilt on demand |
| Secrets | `.env` locally; Secret Manager on Cloud Run | Never in the repository |
