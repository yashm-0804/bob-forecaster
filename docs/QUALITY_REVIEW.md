# Quality review loops

A record of the improvement loops run against this repository in September
2026. Each loop fixed issues, packaged the evidence, and handed a snapshot to
a separate reviewer with a fresh context. That reviewer had the rubric but no
previous scores and no implementer commentary. **Only the reviewer's scores
appear here.** The reviewer ran in the same environment as the implementer, so
each review is labelled "fresh-context, not fully isolated".

Weights: functional correctness 20%, reliability 15%, tests 15%, code quality
10%, type safety 10%, security 10%, and 5% each for performance, UX and
accessibility, documentation, and build/CI.

## Loop 1

**Baseline found on inspection:**
- A stored cross-site-scripting (XSS) hole: the approving officer's name was
  inserted into the console unescaped. Rated P0.
- Telemetry accepted wrongly typed values. A text latitude was stored as
  trusted, and then crashed ingest for every neighbouring node. Rated P1.
- No access control on approve, revoke, dispatch or telemetry.
- Unbounded operator input, and anonymous revocations.
- The test suite needed the network. A fresh offline clone had 3 failures.
- No CI and no pinned dependencies.
- SQLite connections were leaked, producing 59 resource warnings.

**Fixed in loop 1:**
- The XSS, with a regression test that fails on the old page.
- Telemetry type, position and time validation.
- Access codes for writes, failing closed on Cloud Run.
- Named revocations, bounded input, and security headers.
- A hermetic suite: an offline pipeline test, plus fixtures for Weather Lab
  and GFS.
- GitHub Actions CI, pinned requirements, and closed connections.

**Official scorecard (reviewer 1):**

| Factor | Score |
|---|---:|
| Functional correctness | 6.8 |
| Reliability | 6.8 |
| Tests | 7.0 |
| Code quality | 7.0 |
| Type safety | 7.0 |
| Security | 6.5 |
| Performance | 7.5 |
| UX and accessibility | 6.5 |
| Documentation | 7.0 |
| Build and CI | 5.5 |
| **Weighted overall** | **6.81** |

Decision: continue. No P0 remained. The reviewer's P1 findings:
- The Gemini number guardrail could be bypassed with number words, or with a
  computed number given the wrong unit.
- The audit log on Cloud Run was neither durable nor shared between instances.

## Loop 2

**Fixed:**
- **Guardrail.** It now rejects number words (English, Telugu and Odia) and
  numbers in the wrong unit. Malformed replies keep the template.
- **Approvals.** Identifiers carry a fingerprint of the final text, so an
  approval covers exactly what was read.
- **Telemetry.** A year bound, duplicate refusal, and an optional node
  registry.
- **Console script.** It moved to `web/app.js` with no inline handlers, and
  the content policy now forbids inline script. The MapLibre library is pinned
  by subresource-integrity (SRI) hashes.
- **Approval dialog.** An accessible dialog replaced `prompt()`, a Withdraw
  button was added, and dispatch results show in the card.
- **Tabs.** They follow the ARIA tabs pattern.
- **Requests.** Bodies over 64 KB are refused, and parsed runs are cached.
- **Health check.** `/api/health` reports whether the audit log is ephemeral.
  The deploy command caps Cloud Run at one instance.
- **Types.** Every function is annotated. pyright runs in standard mode over
  the application code and the tests.
- **Complexity.** It is capped at 10.
- **Shared code.** One TLS helper and one SQLite helper.
- **Checks.**
  - ESLint on the console.
  - A real-browser test of approve then dispatch.
  - Terrain tests on a committed DEM extract.
  - Coverage measured over application code only.
- **Build.**
  - Hash-locked dependencies.
  - The base image pinned by digest.
  - Linux wheel availability verified.
- **Ensemble spread** below 24 h continues IMD's trend instead of clamping.
- Test-client warnings removed by moving to Starlette 1.7 with httpx2.

**Official scorecard (reviewer 2):**

| Factor | Score |
|---|---:|
| Functional correctness | 6.0 |
| Reliability | 6.0 |
| Tests | 7.0 |
| Code quality | 7.0 |
| Type safety | 6.5 |
| Security | 7.0 |
| Performance | 7.0 |
| UX and accessibility | 7.0 |
| Documentation | 6.5 |
| Build and CI | 6.0 |
| **Weighted overall** | **6.53** |

Decision: continue. The overall score fell because the second reviewer found
two P1 defects that neither the implementer nor the first reviewer had seen:
- **Roads scored zero from wind.** Their curve was keyed `road_tree_blockage`,
  while roads are `road_segment`.
- **A null sensor channel crashed telemetry ingest**, even though the
  validator accepted it.

Among its other findings:
- The guardrail was bypassable with hyphenated units, Telugu and Odia unit
  words, and multiplier words.
- A dispatch was recorded under the approver's name.
- The README claimed a low-voltage density layer that does not exist.
- Faint text failed WCAG contrast.
- A resize listener leaked on every storm switch.

## Loop 3

**Fixed:**
- **Roads** are scored for wind. A test now ties every loaded asset class to
  its curves. Fani's wind-driven assets went from 122 to 792; Montha is
  unchanged.
- **Null channels** are flagged `missing:<channel>` and never fused, and
  neighbour checks skip them. Numbers beyond float range are refused. A seeded
  fuzz test of 2,600 messages confirms ingest never returns 500.
- **Live ingest** flags late readings, using a clock supplied by the API.
- **The guardrail** catches hyphenated units, Telugu and Odia unit words, and
  multiplier words.
- **Audit.** Dispatches record who dispatched, and the approver goes in the
  note. The health check no longer shows where data is kept. Node locations
  need the operator code.
- **Rate limits** on writes.
- **Deployment.** The deploy guide uses Secret Manager, and `EE_PROJECT` has
  no default.
- **Honesty of the docs.** The low-voltage claim is corrected. So are the
  calibration claim and the "every module is exercised" claim.
- **Console.**
  - Contrast meets WCAG AA, with a test.
  - There is a loading state, and the resize leak is fixed, with a test.
  - An accessibility audit runs inside the browser test.
- **Console JS coverage** is measured with c8: 80% of lines, with a 75% floor.
  Every panel renders from the committed runs in the tests.
- **Typing.** pyright's strict mode passes for `api`, `telemetry`, `advisory`
  and `common`, and the schema's channel fields are typed optional.
- **CI.** Actions are pinned by commit, and the image job waits for the
  checks.
- **The agent** diffs cycles on every red asset, not only the 400 shipped to
  the table.
- **Benchmark.** `scripts/benchmark.py` records the timing figures in
  `docs/BENCHMARK.md`.

**Official scorecard (reviewer 3):**

| Factor | Score |
|---|---:|
| Functional correctness | 6.8 |
| Reliability | 6.6 |
| Tests | 7.5 |
| Code quality | 7.5 |
| Type safety | 7.5 |
| Security | 7.0 |
| Performance | 7.5 |
| UX and accessibility | 6.5 |
| Documentation | 7.5 |
| Build and CI | 6.5 |
| **Weighted overall** | **7.11** |

Decision: continue. One new P1, introduced in loop 3: the rate limit was
counted before the access check. Thirty requests without a code from a
shared address could lock out an officer who had the code.

Other findings:
- More guardrail bypasses: other unit spellings, Unicode numerals, and
  "a score of". The reviewer called the earlier fixes patches of the reported
  strings, not of the class of problem.
- The offline map was clipped on high-DPI screens.
- A stray file in `data/runs` broke approvals.
- c8's temporary files had been committed.
- The README overstated Gemini as working.
- The project id appeared in the exported runs.
- A cross-site dispatch was possible in open mode.

## Loop 4

**Fixed:**
- **Rate limit.** It is now applied after the access check and keyed by
  code. Wrong codes are throttled per address and never block a right code.
- **Guardrail, rebuilt by class** in `advisory/numbers.py`:
  - digits in every script;
  - every other Unicode numeral;
  - a unit lexicon with punctuation normalised;
  - currency.

  Property tests sweep every spelling, every separator and every numeral
  (over 250 cases).
- **Run files** are found in one place, so stray files are ignored
  everywhere.
- **Offline map.** It is sized to its box, checked at DPR 2 in the browser
  test.
- **Panel failures** are shown in the panel.
- **Escaping.** Remaining interpolated values are escaped. Rows have a
  button role, and the canvas has a text alternative.
- **Cross-site writes** are refused.
- **The project id** is out of exported reasons.
- **Coverage output** is out of the repository.
- **Accessibility.** axe-core (vendored, WCAG 2.1 A and AA) runs in the
  browser test on every panel, the open dialog and 390 px. There are no
  violations.
- **Types.**
  - The console's JS is type-checked with TypeScript's `checkJs`.
  - pyright strict covers all application code, using pandas and SciPy stubs
    plus minimal local stubs for eccodes, imdtrack and rasterio.
- **Docs.** `docs/ARCHITECTURE.md` added. README status rows for Gemini,
  advisories and the ensemble corrected.

### Scorecard 4 (independent, fresh context)

| Factor | Score |
|---|---:|
| Functional correctness | 7.2 |
| Reliability | 7.2 |
| Tests | 7.3 |
| Code quality | 7.6 |
| Type safety | 7.4 |
| Security | 7.3 |
| Performance | 7.5 |
| UX and accessibility | 7.8 |
| Documentation | 7.4 |
| Build and CI | 6.8 |
| **Weighted overall** | **7.32** |

Decision: continue. One P1: the guardrail read "10,000" as the facts 10 and
0, and did not read "50k" or "10 lacs" at all.

P2 findings:
- The neighbour plane fit gave a 966 hPa residual beside collinear
  neighbours, and flagged 66 of 200 clean readings in a near-collinear case.
- The README described `BOB_NODE_REGISTRY` as a JSON list. Set that way,
  every telemetry post returned 500 while health reported ok.
- DNS rebinding passed the same-origin check in open mode.
- A replay stopped at the first non-degraded failure, and run files were
  written in place.

Also noted:
- The console's JS failed 254 checks under `tsc --strict`.
- Asset rows did nothing in offline mode.
- The offline map drew only one layer.
- The API docs page had no content policy, and there was no HSTS.
- A withdrawal with nothing to withdraw was recorded.
- Four documentation statements were wrong.
- 43% of the test count was parametrised unit spellings.

## Loop 5

**Fixed:**
- **Guardrail.**
  - A number is read whole however it is grouped: commas (including the
    Indian lakh style), apostrophes, thin, no-break and ordinary spaces.
    "10.000" is read both ways.
  - Scales are rejected: k, lakh/lac, crore/cr, mn, bn, x, times, fold,
    and upper-case M and B.
  - Digits glued to Latin letters that are neither a unit nor an ordinal
    are rejected.
  - Scale words glued to digits in Telugu and Odia are caught.
  - The advisory's own asset names are masked as facts, and units are still
    checked on the unmasked text.
  - The documented remaining limit: a digit word from an asset name may be
    repeated on its own.
- **Neighbour fit.** It fits only along the directions the neighbours span:
  a plane, a line along a road, or the median. The 3 false flags in the
  simulated Montha network are now 0, and every injected fault is still
  caught.
- **Registry.** A file path, documented as such. An unreadable registry
  refuses telemetry with a 503 and appears in `/api/health` as
  `ok: false` with the reason.
- **Host allowlist.** `BOB_ALLOWED_HOSTS`: loopback names by default, plus
  `*.run.app` on Cloud Run. Other API changes:
  - HSTS on Cloud Run.
  - API docs off on Cloud Run unless `BOB_API_DOCS=1`, and served with a
    hash-based policy locally.
  - Gzip at level 5.
- **Replays and runs.**
  - A failed cycle is recorded and the replay continues, exiting non-zero.
  - Run files are written to a staging file and moved into place.
  - Withdrawing with no standing approval returns 409 and records nothing,
    atomically.
- **Console.**
  - `tsc --strict` passes with 0 errors: payload typedefs, `byId`, and a
    typed MapLibre surface.
  - Rows show a detail card in every map mode.
  - The offline map draws every checked layer.
  - There is one map fallback path. It also fixes a blank map after a
    storm switch when the offline map fails too.
  - Sidebar figures are escaped.
- **Performance.** The neighbour query uses a bounding box in SQL: at 2,000
  nodes, median ingest went from 3.5 to 2.6 ms. Benchmarks now include 500
  and 2,000 nodes.
- **Docs.** The four wrong statements are corrected, and the guardrail's
  limits are listed.

**Not done, and why:**
- **Splitting `app.js` into ES modules, injecting the API's stores instead
  of module globals, and typing the Python run payload end to end.** Each is
  an architecture change for maintainability rather than a defect fix, and
  the loop's rules say to preserve the architecture unless a bug requires
  otherwise.
- **The Docker build, a CI run, a deployment and a GPU browser check.**
  These need the owner.

### Scorecard 5 (independent, fresh context)

| Factor | Score |
|---|---:|
| Functional correctness | 7.3 |
| Reliability | 7.4 |
| Tests | 7.8 |
| Code quality | 7.6 |
| Type safety | 7.5 |
| Security | 7.2 |
| Performance | 7.8 |
| UX and accessibility | 8.0 |
| Documentation | 7.8 |
| Build and CI | 6.5 |
| **Weighted overall** | **7.48** |

Decision: continue. No P0 or P1.

P2 findings:
- The wrong-code limit never slows guessing, because the right code always
  gets through; a 2-character code fell to 936 fast guesses.
- Operator reads spent the write budget.
- A corrupt or unreachable audit database made `GET /api/run` return 500
  while health said ok.
- The image was open for writes outside Cloud Run.
- The guardrail accepted computed numbers reused without their unit, units
  outside its lexicon, "rupees", signs and "category 3".
- There was no remediation plan for model skill.

P3 findings:
- A race between dispatch and revoke.
- Malformed Gemini replies were cached.
- An unknown `--region` failed every cycle.
- Track popup fields were not escaped.
- Four documentation statements were wrong.

## Loop 6

**Fixed:**
- **Access codes.**
  - Codes shorter than 16 characters are refused (503) and reported in
    health. Length, not the rate limit, is what defeats guessing, and the
    docs and the rate-limit test now say so.
  - Code-protected reads spend no write budget.
  - The image sets `BOB_REQUIRE_TOKENS=1`, so it fails closed wherever it
    runs.
- **Audit store failures.**
  - Runs are served without the audit log when it cannot be read, with
    approval state unknown and a notice.
  - Storage errors answer 503 with "nothing was recorded" and never name
    the file.
  - Health probes both stores.
- **Guardrail.**
  - A number code computed in a unit may appear only with a unit.
  - Speeds are read however joined ("/", "per", "an", any time unit).
  - New units are read so that they never match a fact: power, mass,
    volume, area and money.
  - Also rejected: signs, labels, and durations said with an article.
  - Asset names' own quantities count as facts.
- **Atomicity and caching.**
  - Dispatch checks and records in one step, under an `RLock`.
  - Only replies that parse as JSON objects are cached.
- **Smaller fixes.**
  - `--region` rejects unknown names.
  - The track popup escapes its fields.
- **Console.**
  - Approvals are re-read when the tab returns.
  - A run of the wrong shape is refused by name.
- **Browser test.** It now includes a keyboard-only pass: Enter, Escape,
  typing, arrow keys and asset rows.
- **Types.** The API's small responses have typed models, and advisories are
  indexed by identifier.
- **CI.** It runs `check.sh` itself, so the two cannot drift. Coverage
  floors are raised to 90% (Python) and 85% (JS).
- **Coverage.** `verify/satellite.py` rose from 51% to 98% and
  `hazard/terrain.py` from 62% to 97%, through a recording Earth Engine
  stand-in and fakes of urlopen and rasterio. Two deliberate mutations were
  caught.
- **Load.** The benchmark adds a real server under 50 concurrent clients:
  about 860 run reads and 960 approvals a second, all 200.
- **Docs.** `docs/MODEL_SKILL.md` sets out the plan, and the doc
  corrections are made.

**Test count:** 675 to 480, because about 420 parametrised spelling cases
became five sweep tests that check every case and list every failure. The
number of distinct behaviours checked went up.

**Not done:** splitting `app.js` into modules, and typing the full run
payload in Python; both are architectural. The Docker build, CI run,
deployment and GPU browser check need the owner.

### Scorecard 6 (independent, fresh context)

| Factor | Score |
|---|---:|
| Functional correctness | 7.3 |
| Reliability | 7.4 |
| Tests | 8.2 |
| Code quality | 7.8 |
| Type safety | 8.2 |
| Security | 7.6 |
| Performance | 7.9 |
| UX and accessibility | 8.2 |
| Documentation | 8.3 |
| Build and CI | 7.0 |
| **Weighted overall** | **7.73** |

Decision: continue.

The two P1s are both documented with a remediation plan and neither is
resolved:
- The audit log is not durable on Cloud Run.
- Flood and outage skill is below climatology.

P2 findings:
- One truncated run file made every approval a 500.
- The guardrail passed "category IV" and "tens of households".
- Identity rests on a shared code and a typed name.
- The image and CI have never run.
- `app.js` is still one file.

P3 findings:
- `/openapi.json` was public on Cloud Run.
- The Origin check compares netloc only.
- A non-ASCII code could never match.
- `lead_hours` was not escaped.
- The storage test relied on `chmod`.
- Telemetry QC read its context outside the lock.
- Public health described code problems.
- The offline map drew the track off its box.

## Loop 7

**Fixed:**
- **Run files.** Each is checked for its shape when read. A damaged one
  costs only itself: it is not listed, answers 503, and appears in health.
  Approvals on the other runs carry on.
- **Guardrail.** Labels with Roman numerals and "tens of" are rejected.
  Reusing a computed number in its own unit for another quantity is
  documented as a limit.
- **Schema.** `/openapi.json` goes with the docs: off on Cloud Run.
- **Access codes.** A code with characters outside ASCII is a
  misconfiguration, refused and reported. Public messages name the setting;
  the log says what is wrong with it.
- **Telemetry.** From the duplicate check to the insert, the store holds its
  lock, so neighbours posting together are checked in turn.
- **Console.** Lead times are numbers only, and the offline map is clipped to
  the grid box.
- **Tests.**
  - The storage-failure test uses a file where a directory should be, so it
    works even as root.
  - The JS coverage floors add 80% branches and 85% functions.
  - Every new test fails on 7d8d521.
- **Docs.** The asset count in the README is corrected.

**Not done, and why:**
- **The Origin scheme check.** Cloud Run terminates TLS, so the server sees
  http while the browser says https. Comparing schemes would need the
  forwarded protocol, which cannot be verified without a deployment.
- **Hash-chained audit rows.** This is a schema change and needs approval.
- **The durable audit store (Firestore or Cloud SQL) and verified identity
  (IAP).** These are paid infrastructure and deployment decisions.
- **Model skill.** The plan in `docs/MODEL_SKILL.md` is a modelling effort
  on held-out storms.
- **The image, CI, a deployment and the GPU browser check.** These need the
  owner.

### Scorecard 7 (independent, fresh context; resumed after a usage-limit interruption)

| Factor | Score |
|---|---:|
| Functional correctness | 7.2 |
| Reliability | 7.4 |
| Tests | 8.2 |
| Code quality | 7.8 |
| Type safety | 8.3 |
| Security | 7.5 |
| Performance | 8.0 |
| UX and accessibility | 8.1 |
| Documentation | 8.2 |
| Build and CI | 7.0 |
| **Weighted overall** | **7.71** |

Decision: continue.

The three P1s are documented, and they need the owner or are a modelling
effort:
- The audit store is not durable.
- Model skill is poor.
- Identity rests on a shared code.

P2 findings:
- The guardrail passed "10 dead", "1 in 3", "by 3 pm", "50 months" and
  "fortnight".
- No committed run was drafted by Gemini.
- Rankings are public.
- `test_pipeline` reads the committed JSON.

P3 findings:
- Deep JSON gave a 500.
- A damaged telemetry report gave a 500.
- `driver` was unescaped.
- The dispatch lead was not an integer.
- `HEAD /` returned 405.

The owner then asked for security checks and a look at the frontend, and set
the stopping point: an overall of 8.0.

## Between loops 7 and 8, at the owner's request

- **A `security` step in `check.sh` and CI.**
  - Bandit's rules (ruff `S`) on application code. There were 19 findings,
    all fixed: https-only downloads through `ingest.net`, fixed SQL text,
    explicit checks instead of asserts, and git run by its full path.
  - `scripts/secret_scan.py` over every tracked file and every commit. It
    found no credentials. The Earth Engine project id is in 4 old commits,
    and is listed as a note: scrubbing history is the owner's call.
  - `pip-audit`.
- **Frontend.** Screenshots in `docs/screenshots` and the README, from
  `scripts/screenshots.mjs`.

## Loop 8

- **A critical advisory in MapLibre.** The new JavaScript library audit
  found GHSA-jrc7-96c5-q579, a sanitiser bypass (XSS), in maplibre-gl 4.7.1,
  the version the console loaded from cdnjs. cdnjs no longer publishes
  MapLibre's JavaScript, and version 6 is ES-module only. So MapLibre 6.11.2
  is now vendored in `web/vendor`, with npm's integrity hash and per-file
  sha256 in `VENDOR.json`, and loaded by `web/map-loader.mjs`.
- **Content policy.**
  - It allows scripts from this server only.
  - `worker-src 'self' blob:` for MapLibre's workers.
  - `connect-src data:` for the hazard images MapLibre 6 fetches. Without
    it the overlays were blocked; found in a browser.
- **`scripts/js_audit.py`.** It checks the vendored files against their
  hashes, queries OSV for advisories, and confirms the page loads nothing
  from another origin.
- **The MapLibre path, verified for the first time.** Headless Chrome with
  software WebGL loads MapLibre 6.11.2, the CARTO basemap and every layer.
  A table row flies the map, and axe is clean on the map view
  (`tests/e2e/maplibre.mjs`, an opt-in network test). Stand-in tests of
  initMap, the layers, the popups and the fallbacks took JS line coverage
  from 87.5% to 96.2%.
- **Guardrail.** It now rejects casualty claims in English, Telugu and Odia,
  odds, clock times, and spans in months, years and fortnights.
- **Live Gemini.** Montha T−24 h was regenerated with live Gemini: all four
  advisories drafted, with Telugu, every field passing the guardrail. The
  other cycles hit a 503 or the daily limit and say so. The regeneration
  reproduced every computed field of every Montha run exactly; only the
  advisories differ.
- **Fixes.**
  - Deep JSON answers 400.
  - A damaged telemetry report answers 503.
  - `HEAD /` works.
  - `driver` is escaped.
  - The dispatch lead is an integer.
- **Tests.** The dropped audit-read assertion is restored. The JS floors
  are 94% lines, 90% functions and 80% branches.

### Scorecard 8 (independent, fresh context; not fully isolated)

| Factor | Score |
|---|---:|
| Functional correctness | 7.2 |
| Reliability | 7.5 |
| Tests | 8.2 |
| Code quality | 7.4 |
| Type safety | 8.0 |
| Security | 7.6 |
| Performance | 8.0 |
| UX and accessibility | 8.1 |
| Documentation | 8.0 |
| Build and CI | 7.0 |
| **Weighted overall** | **7.65** |

Decision: continue.

The two P1s are unchanged, and both need the owner or are a modelling
effort:
- The audit store is not durable.
- Flood and outage forecasts have no demonstrated skill.

P2 findings:
- CAP urgency and certainty came from the consequence band, not from
  probability and lead time. An advisory about failure probabilities of
  13–18% said `Likely`.
- Operator identity is self-declared under one shared code. This is by
  design and documented.

P3 findings:
- The guardrail passed Roman numerals, "halve" and fractions like "1/3".
- The sensor-network panel did not escape server values.
- The Origin/Host comparison was case-sensitive.
- Uvicorn trusted `X-Forwarded-For` from 127.0.0.1, so rotating it got
  round the wrong-code limit.
- A malformed `BOB_*_PER_MIN` stopped the server starting.
- `HEAD` on API routes returned 405.
- The fragility docstring contradicted the README.
- CAP `<sent>` recorded when the replay was made, not the forecast cycle.

Also noted:
- Branch coverage was not enforced.
- Twelve broad `except Exception` handlers could hide programming errors.
- `api/main.py` mixed middleware, models, caches and routes in 776 lines.

## Loop 9

- **CAP semantics.** Severity still comes from the consequence band.
  - Urgency comes from the lead time: 12 hours or less is `Immediate`, 24
    hours or less is `Expected`, anything longer is `Future`, and no
    landfall time gives `Unknown`.
  - Certainty comes from the highest failure probability among the listed
    assets: over 50% is `Likely`, 5% or more is `Possible`, anything lower
    is `Unlikely`.
  - `<sent>` is the forecast cycle.
  - All eight replays were regenerated. Only `cap_xml` changed, plus two
    draft notes that now name today's Gemini quota instead of a 503. The
    Montha T−24 h reply came from the cache and is still Gemini-drafted.
- **Security.**
  - uvicorn runs with `--no-proxy-headers`. The test for it fails with
    uvicorn's defaults.
  - Origin and Host are compared case-insensitively.
  - The network panel escapes every value, and says so when there is no
    report.
  - Dispatch stays disabled in the console until the advisory is approved.
  - The content policy names the basemap's hosts instead of allowing any
    https source.
- **Reliability.**
  - `common/errors.reraise_bugs` lets programming errors (TypeError,
    AttributeError, NameError and others) out of the broad handlers in
    the pipeline, the Gemini path, OSM, terrain and Earth Engine.
  - A malformed budget setting falls back to its default and is reported
    in `/api/health`, instead of stopping the server.
  - `/api/health` also reports writes that are refused for want of a
    code, and reads the run files once.
- **Guardrail.** It now rejects Roman numerals with a unit, fractions,
  "halve", and certainty words such as "certain" and "guaranteed".
  - The first version of the Roman check missed "power out for XLVIII
    hours": an empty numeral matched earlier and consumed the real one.
    The loop's own probes found it. The pattern now needs at least one
    numeral letter.
  - A unit now ends at its clause, so "48 hours, then" is read in hours.
    It was read as a bare number, which fails safe but misreads the
    text. The Gemini-drafted Montha T−24 h replay regenerates
    byte-identical under the changed guardrail.
- **HEAD** works on every GET route, by middleware.
- **Structure.** `api/main.py` went from 793 lines to 354. What every
  request passes through is in `api/guard.py`, the run files in
  `api/run_store.py`, the models in `api/models.py`, and the docs pages in
  `api/docs.py`. The OpenAPI schema and the middleware order are the same
  before and after the split.
- **Tests.** Branch coverage is on, with a floor of 92% counting branches.
  The fragility docstring now says the curves are compared with recorded
  damage, not fitted to it. The README has a three-command start at the
  top.
- **Found by the loop's own evidence run.** A new test failed on a machine
  with an HTTP proxy set, because it sent its requests to the local server
  through the proxy. It now goes direct.

### Scorecard 9 (independent, fresh context; not fully isolated)

| Factor | Score |
|---|---:|
| Functional correctness | 7.0 |
| Reliability | 7.5 |
| Tests | 8.0 |
| Code quality | 7.8 |
| Type safety | 7.8 |
| Security | 7.4 |
| Performance | 8.0 |
| UX and accessibility | 8.0 |
| Documentation | 8.0 |
| Build and CI | 6.0 |
| **Weighted overall** | **7.53** |

Decision: continue.

P1 findings:
- **New, and caused by this loop.** CI's image smoke test expected a
  healthy server from an image started without access codes. Loop 9 made
  health report writes refused for want of a code, so the job could no
  longer pass. The loop's own image rehearsal recorded `ok:false` and did
  not flag the conflict.
- The audit store is not durable. This is documented.

P2 findings:
- The console showed only the English text of an advisory, though an
  approval covers every language.
- Operator identity is self-declared under a shared code. This is by
  design.
- Forecast skill has not been shown.
- Two mutants survived the suite: dropping the translations from the
  content fingerprint, and dropping the escaping in the CAP headline.

P3 findings:
- `<senderName>` named the recipient.
- A bad access code was logged on every request.
- The operator code is kept in `sessionStorage`.
- The app-wide `OSError` handler reports any I/O error as storage.
- `HEAD` renders the whole body and discards it.
- Bare counts can be reused.

## Loop 10

- **The CI image job.** Its checks moved to `scripts/smoke_test.sh`. CI now
  starts two containers: one with throwaway codes, which must be healthy
  with writes protected by code, and one without, which must fail closed.
  `tests/test_ci_smoke.py` runs the same script against a server started
  with the Dockerfile's settings and flags plus the settings `ci.yml` gives
  each container. The test fails when the codes are taken out of `ci.yml`,
  which is the original mistake. Docker is still not installed, so the
  image itself is still not built.
- **Translations in the console.** Each advisory card now shows every
  translation the approval covers, in full and escaped. The text is marked
  with its language, so a screen reader reads it in the right voice. The
  approval dialog names the languages it covers. The browser test now runs
  axe at 390 px on the Telugu-drafted Montha T−24 h, and checks that the
  Telugu text is shown.
- **CAP.** `<senderName>` is the originator, and the recipient department
  is the `<audience>`, in the order the CAP 1.2 schema requires. All eight
  replays were regenerated. Only the sender and audience changed; the
  identifiers and the drafting are the same.
- **Tests that kill the two surviving mutants.** A changed translation
  changes the identifier. Model text holding `& < > "` gives well-formed
  CAP with that text.
- **Log noise.** A misconfigured access code is logged once per problem,
  not on every request. `/api/health` still reports it every time.
- **Found by the loop's own evidence run.** The first version of the smoke
  script piped the page into `grep -q`. That stops reading at the first
  match, so curl, still writing, could fail with exit 23 under `pipefail`.
  It failed once in four runs, and would have made the CI job flaky too.
  The page is now read whole, then searched, and the test passed 20 runs
  out of 20.
