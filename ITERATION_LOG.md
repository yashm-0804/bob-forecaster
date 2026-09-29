# Iteration log

Controlled improvement loop. Baseline first, then one batch per iteration with
verification and re-scoring. Changes that do not clearly improve quality are
reverted.

---

## Baseline — 2026-09-22

### What it currently does

Replays a real Bay of Bengal cyclone from IMD best-track data through a hazard
model (wind, rainfall, surge screen) over real terrain, scores 6,445 real
OpenStreetMap assets through fragility curves, and drafts CAP 1.2 advisories
per department behind a human approval gate. FastAPI backend, MapLibre console.
57 tests passing, 1.7 s end to end, no cloud credentials required.

### Strengths

- **Real data throughout.** IMD best track via `imdtrack`, 6,445 OSM assets
  (4,204 named), Copernicus 30 m elevation. Nothing is synthetic.
- **A defensible thesis.** The rainfall-damage pathway is a genuine gap that
  wind-category systems miss, and the Montha replay reproduces it (0 wind /
  6,391 flood) with a test pinning the result.
- **Honest engineering.** Surge labelled a screen, LV grid labelled an
  estimate, `status=Exercise` on every alert, pluggable terrain with loud
  fallback.
- **Clean module boundaries.** `ElevationSource` let a placeholder be swapped
  for a real DEM without touching `surge_screen.py` or `pipeline.py`.

### Weaknesses

| # | Weakness | Severity |
|---|---|---|
| W1 | **Ranking has almost no discriminating power.** 400 shipped assets collapse into 17 distinct probability values; 86 share p=0.18. 336 hospitals rank near-identically. The headline claim is "asset-level, not district colours" — a 17-bucket ranking is a district colour with extra steps. | Critical |
| W2 | **README claims modules that do not exist.** The architecture table lists `verify/` (empty), Gemini drafting, parametric triggers, LV proxy, population, telemetry ingest and simulation. None are built. For a project whose differentiator is honesty about limits, this is the most damaging possible flaw. | Critical |
| W3 | **Approval gate accepts non-existent advisories.** `POST /api/advisory/FAKE-ID/approve` returns 200. The one subsystem that must be rigorous is not. | Critical |
| W4 | **Default map layer is empty.** `p_tide_1m` is checked on at load and has 2 non-zero cells out of 2,193. The console opens looking like it has no data. | High |
| W5 | **Mobile layout is broken.** Stat values clipped off-screen, banner truncated, caveat text cut. Unusable at 420 px. | High |
| W6 | No red-severity assets at all after the terrain swap — thresholds are miscalibrated for a storm of this intensity, so the severity scale is effectively two-valued. | High |
| W7 | No way to change storm or lead time; the console hardcodes `runs[0]`. A judge cannot explore. | Medium |
| W8 | 6,445 assets scored, 400 shipped, truncation never surfaced to the user. | Medium |
| W9 | In-memory approval state, lost on restart, with no audit trail. | Medium |
| W10 | No linting or type checking configured. | Low |

### Missing functionality

`verify/` (night-lights and SAR verification), Gemini drafting, parametric
trigger monitor, telemetry ingest and simulated node network, population
weighting, storm/lead switching in the UI.

### Generic or derivative aspects

The console is a competent but conventional dark dashboard: sidebar of stats,
map, ranked list. Nothing about the interface yet expresses the project's
actual point of view — that *consequence*, not probability, is what an officer
needs at 48 hours out.

### Technical risks

- Overpass and AWS are external dependencies with no offline fixture, so a
  demo on bad conference wifi degrades to a cached run only.
- `data/runs/*.json` is the only persistence; approval state is volatile.
- `.pytest_cache` is committed to the repository.

### Baseline scores

| Dimension | Score | Note |
|---|---|---|
| Concept clarity and strength | 8.5 | Strong, well-grounded, clearly stated |
| Uniqueness | 7.0 | Real thesis, undercut by flat execution |
| User value | 6.0 | Named assets are real; a flat ranking is not actionable |
| Effectiveness | 6.5 | Pipeline works; purpose not yet achieved |
| User experience | 5.0 | Empty default layer, broken mobile, no exploration |
| Visual / design quality | 7.0 | Desktop coherent; mobile fails |
| Technical quality | 7.5 | Clean modules, 57 tests; auth hole, no lint |
| Completeness | 5.5 | Several claimed subsystems absent |
| Differentiation | 6.5 | Strong on paper, weak in the artifact |
| Presentation quality | 6.0 | README overclaim is a trust-killer |
| **Overall** | **6.55** | |

Critical weaknesses (W1–W3) make it feel worse than 6.55 suggests: a reviewer
who opens `verify/`, or sorts the asset table, loses confidence in everything
else.

### Five highest-impact improvements

1. **I1 — Rank by expected consequence, not probability.** Fixes W1 and is the
   genuine differentiator.
2. **I2 — README integrity pass.** Fixes W2.
3. **I3 — Close the approval hole.** Fixes W3.
4. **I4 — Sensible default layer, calibrated severity, mobile layout.** W4–W6.
5. **I5 — Storm and lead-time switching, truncation disclosure.** W7–W8.

---

## Iteration 1 — 2026-09-22

**Selected:** the three critical weaknesses. Fixing presentation without fixing
the ranking would only package the same flaw more attractively.

### I1 — Rank by expected consequence, not probability

`impact/consequence.py` (new). Criticality weights derived only from
attributes really present in OSM: substation voltage (79/146 mapped —
400/220/132 kV), hospital `emergency` tag and name patterns, road class. Every
weight carries a `basis` string and a confidence level (`measured` /
`inferred` / `class-default`) that reaches the UI, colour-coded.

`impact/rollup.py`: added sub-grid elevation refinement. The hazard grid is
2.2 km; the terrain under it is 123 m. Without correction every asset in a
cell got the cell's average flood depth, which was most of why the ranking
collapsed.

Ranking and severity now run on `consequence = p_failure × criticality`,
read in typical-asset-equivalents.

### I2 — README integrity

The architecture table listed `verify/`, Gemini drafting, parametric triggers,
LV proxy, population and telemetry ingest. None existed. Replaced with a table
of modules that actually exist, plus an explicit **Not built** section.

### I3 — Approval gate

`POST /api/advisory/FAKE-ID/approve` returned 200 and created an approval
record that would then satisfy the dispatch gate. Now resolves the identifier
against exported runs (404 if absent) and rejects operator names under three
characters. `revoke` validates too.

### Bugs found and fixed inside this iteration

| Bug | How it surfaced | Fix |
|---|---|---|
| Unbounded elevation correction poured up to 154 m of water into valley floors, driving substation `p_failure` to 1.00 in a 93 km/h storm | Top-10 inspection after the first run | `MAX_LOCAL_DEEPENING` cap; dry cells stay dry |
| Population estimate jumped 59,000 → 1,247,120 with no new evidence | Mobile screenshot | Weights normalised to their own mean, so criticality redistributes rather than inflates |
| First severity calibration put 783 assets (12%) in red | Severity histogram | Recalibrated to 49 (0.8%) |
| `body{overflow:hidden}` made the asset table and advisory queue unreachable on narrow screens | Mobile screenshot | `overflow-y:auto` below 1100 px |
| Default map layer had 2 non-zero cells out of 2,193 | Payload inspection | Layer chosen from actual coverage at load |

**One false lead:** I diagnosed mobile text clipping as a layout bug and made
two rounds of CSS changes before a DOM probe showed headless Chrome floors the
viewport at 500 px — the 420 px screenshots were rendering at 500 and cropping.
`NONE OVERFLOW` at 500/560/768/1024/1400. The `overflow:hidden` finding under
it was real; the clipping was not.

### Key parameter sensitivity

`MAX_LOCAL_DEEPENING` dominates the impact model. Measured:

| cap | red | max substation p | distinct values in top 400 |
|---|---|---|---|
| 0.0 m | 0 | 0.12 | 35 |
| **0.3 m** | **49** | **0.51** | **69** |
| 0.5 m | 5* | 0.69 | 58 |
| 1.0 m | 67* | 0.92 | 26 |

\* under the earlier band calibration. 0.3 m chosen on two independent
grounds: it is what a screening model can defend, and it gives the sharpest
ranking, because a larger cap saturates the depth–damage curve.

### Verification

- 79 tests passing (was 57). New: `tests/test_consequence.py`, plus
  discrimination, red-list-size, criticality-provenance and population
  regression tests.
- Horizontal overflow checked at 500/560/768/1024/1400 px — none.
- Approval gate: fake id → 404, single-initial operator → 400, real → 200,
  revoke fake → 404.
- End-to-end replay re-run and exported after every change.

### Measured movement

| | Before | After |
|---|---|---|
| Distinct consequence values in top 400 | 13 | **69** |
| Most crowded bucket | 383 assets | 22 assets |
| Red band | 0 (or 783 mis-calibrated) | **49 (0.8%)** |
| Advisories drafted | 4 | 5 (DISCOM now fires) |
| Tests | 57 | 79 |

### Scores

| Dimension | Baseline | Iter 1 | Δ |
|---|---|---|---|
| Concept clarity | 8.5 | 9.0 | +0.5 |
| Uniqueness | 7.0 | 8.5 | +1.5 |
| User value | 6.0 | 8.0 | +2.0 |
| Effectiveness | 6.5 | 8.0 | +1.5 |
| User experience | 5.0 | 7.5 | +2.5 |
| Visual / design | 7.0 | 7.5 | +0.5 |
| Technical quality | 7.5 | 8.5 | +1.0 |
| Completeness | 5.5 | 6.5 | +1.0 |
| Differentiation | 6.5 | 8.5 | +2.0 |
| Presentation | 6.0 | 7.5 | +1.5 |
| **Overall** | **6.55** | **7.95** | **+1.40** |

### Remaining backlog

1. **B1** — `verify/` is empty. The honest loop (predict → check against
   VIIRS/Sentinel-1 → report misses) is the project's most distinctive claim
   and is unbuilt. Lowest dimension is Completeness at 6.5.
2. **B2** — OSM tagging artifacts reach the top of the list: a medical shop
   tagged `emergency=yes` ranks ×3.0 as an emergency hospital.
3. **B3** — No storm or lead-time switching; a reviewer cannot explore.
4. **B4** — The map is the centre of the console and fails entirely without
   a CDN. No offline basemap fallback.
5. **B5** — Approval state is in-memory and lost on restart.

---

## Iteration 2 — 2026-09-22

**Selected:** B1. Completeness was the lowest dimension at 6.5, and the gap was
`verify/` — an empty directory behind the project's most distinctive claim:
predict, check, publish the misses.

### What was built

`verify/metrics.py` — contingency table with POD, FAR, CSI and bias; Brier
score; Brier skill score against climatology; reliability bins. Every score is
paired with its counterpart, because POD alone rewards crying wolf and FAR
alone rewards silence.

`verify/ensemble_skill.py` — the one verification runnable today with no
external data: the 50 perturbed members against IMD's own post-analysis best
track. Both sides real.

`verify/observations.py` — VIIRS Black Marble and Sentinel-1 declared with
their real dataset identifiers, what each needs, and why it is unavailable.
`load_observed` returns `(None, reason)` and never a substitute number.

Console gains a **Checks** tab. Tabs became deep-linkable (`#verify`), which
made the panel verifiable in a headless screenshot and is independently useful.

### Result

| | |
|---|---|
| Mean track error | 16.7 km |
| Landfall error | 28.1 km |
| Truth inside ensemble spread | 100% of 32 steps |
| IMD published 48 h landfall error | 34.4 km |

Our 28.1 km spread is consistent with IMD's published operational error at the
lead time the ensemble was built for. That confirms the uncertainty is
honestly sized. It is **not** a skill claim, and both the code and the UI say
so: the members are perturbed from the same track they are scored against, so
the envelope hit rate is close to tautological. Real skill needs a forecast
issued before the event — the Weather Lab archive is the route.

### Decision: no fabricated verification

Earth Engine is registered but unauthenticated, so post-landfall imagery is
unreachable. The alternatives were to skip the step silently, synthesise a
plausible comparison, or state the gap. The third is the only one compatible
with a project whose case rests on honesty about limits, and it is enforced by
test: an unavailable source must return a reason, never a number.

### Verification

- 93 tests passing (was 79). New `tests/test_verify.py` covers the
  cry-wolf and stay-silent failure modes, sea masking, Brier calibration, and
  the honesty rules.
- Checks panel renders at 500 / 768 / 1400 px.
- Fixed: the ranking note was showing above the Checks and Advisories panels,
  where it describes nothing.

### Scores

| Dimension | Iter 1 | Iter 2 | Δ |
|---|---|---|---|
| Concept clarity | 9.0 | 9.0 | — |
| Uniqueness | 8.5 | 9.0 | +0.5 |
| User value | 8.0 | 8.0 | — |
| Effectiveness | 8.0 | 8.5 | +0.5 |
| User experience | 7.5 | 8.0 | +0.5 |
| Visual / design | 7.5 | 8.0 | +0.5 |
| Technical quality | 8.5 | 9.0 | +0.5 |
| Completeness | 6.5 | 8.0 | +1.5 |
| Differentiation | 8.5 | 9.0 | +0.5 |
| Presentation | 7.5 | 8.5 | +1.0 |
| **Overall** | **7.95** | **8.50** | **+0.55** |

### Remaining backlog

1. **B4** — the map is the centre of the console and fails completely without a
   CDN. On venue wifi a judge sees an empty middle column. Highest remaining
   UX risk.
2. **B3** — no storm or lead-time switching; a reviewer cannot explore.
3. **B2** — OSM tagging artifacts reach the top of the list (a medical shop
   tagged `emergency=yes` ranks ×3.0).
4. **B5** — approval state is in-memory, lost on restart.
5. **B6** — no lint or type check configured.

---

## Iteration 3 — 2026-09-22

**Selected:** B4. The map occupied the centre of the console and failed
completely without a CDN — on venue wifi a judge would have seen an empty
column where the product is.

### What was built

Everything needed to draw this coast was already in the payload: hazard grids,
the track, and every asset's position. Only the map library and the basemap
tiles came from outside. So the pipeline now also exports a `land_mask` at grid
resolution (a few KB), and the console has a canvas renderer that draws sea,
land, coastline, the active hazard layer, the track, asset markers and the
landfall point — with **no library, no tiles and no network**.

It is deliberately plain: no pan, no zoom, no labels. It exists so a console on
a restricted network still shows where the storm went and what is under it.

### Bugs found

| Bug | How it surfaced | Fix |
|---|---|---|
| The fallback only caught *synchronous* failures. MapLibre constructs fine and fails asynchronously when its basemap or WebGL context is unavailable, leaving a black rectangle with nothing thrown | Screenshot showed black where the "unavailable" message used to be | `map.on('error')` plus a readiness timeout; "did not become ready" is now treated as failure |
| **`#map` measured 10,306 px tall.** Grid and flex items default to `min-height:auto`, so `#right`'s asset list set the row height for all three panes and `.view`'s internal scroll never engaged | DOM probe reporting element geometry | `min-height:0` on the grid children. **Pre-existing layout bug**, invisible while the map filled the space |
| Canvas sized from its parent's height fed back into that height | Same probe: canvas 840×10306 | Canvas absolutely positioned; measured from `getBoundingClientRect` |
| Hazard layer at full opacity buried the coastline | Screenshot | Alpha capped at 0.55; coastline traced on top, last |

### Method note

I guessed at the black map twice before instrumenting it, then a DOM probe gave
the answer in one shot: WebGL disabled (a headless artifact, not a real-world
bug — but the fallback correctly catches it), and a 10,306 px container.
The probe should have come first. Same lesson as the phantom mobile clipping
in iteration 1.

### Verification

- 95 tests (was 93). New: land-mask sanity and a payload-size ceiling.
- Offline map renders at 500 / 900 / 1400 px.
- Coastline traces the real Andhra shore; the landfall marker sits on it.

### Scores

| Dimension | Iter 2 | Iter 3 | Δ |
|---|---|---|---|
| Concept clarity | 9.0 | 9.0 | — |
| Uniqueness | 9.0 | 9.0 | — |
| User value | 8.0 | 8.5 | +0.5 |
| Effectiveness | 8.5 | 8.5 | — |
| User experience | 8.0 | 9.0 | +1.0 |
| Visual / design | 8.0 | 8.5 | +0.5 |
| Technical quality | 9.0 | 9.0 | — |
| Completeness | 8.0 | 8.5 | +0.5 |
| Differentiation | 9.0 | 9.0 | — |
| Presentation | 8.5 | 8.5 | — |
| **Overall** | **8.50** | **8.75** | **+0.25** |

### Remaining backlog

1. **B3** — no storm or lead-time switching; a reviewer cannot explore. Blocks
   Effectiveness and Presentation from 9.
2. **B2** — OSM tagging artifacts reach the top (a medical shop tagged
   `emergency=yes` ranks ×3.0).
3. **B5** — approval state in memory, lost on restart.
4. **B6** — no lint or type check configured.

---

## Iteration 4 — 2026-09-22

**Selected:** B3 and B2 — the two items blocking 9.0.

### B2 — tagging artifacts at the top of the list

OSM applies `emergency=yes` loosely. Only 2 of 34 tagged hospitals in the AOI
were artifacts, but both reached the top: **"Koteswara rao medical shop"
ranked third overall.** An artifact at the top costs far more credibility than
one buried in it.

The name now vetoes the tag when the two disagree, and a vetoed tag drops from
`measured` to `inferred` confidence. Small-facility patterns widened to cover
shops, pharmacies, diagnostics and labs.

### B3 — a second storm, which turns the thesis into a demonstration

`imdtrack` carries 40 named Bay of Bengal storms since 2013, offline. Added
named regions and generated **Fani (2019)** over coastal Odisha alongside
Montha over Andhra.

| | Montha | Fani |
|---|---|---|
| IMD category | SCS | ESCS |
| Peak wind | 93 km/h | 213 km/h |
| Land with P(gust > 90 km/h) | 5.9% | 32.6% |
| Wind-driven assets | **0** | **123** |

This is the project's central claim, now checkable in two clicks rather than
asserted in a README. The switcher is the argument, not a convenience.

### Bug found

Overpass returned **504 Gateway Timeout** on the Odisha box — larger, and
containing Bhubaneswar. Rather than shrink the region, queries now split into
tiles above 1.1° and stitch with de-duplication, since a way straddling a tile
edge returns from both sides. That makes any AOI work, not just this one.

### Verification

- 97 tests (was 95). New: the shop-tagged-emergency regression and the dental
  variant.
- Both runs generated end to end; Fani's Odisha coastline is derived correctly
  from its own DEM tiles and differs visibly from Andhra's.
- Switcher verified via `?storm=fani`; runs are URL-addressable.

### Scores

| Dimension | Iter 3 | Iter 4 | Δ |
|---|---|---|---|
| Concept clarity | 9.0 | 9.0 | — |
| Uniqueness | 9.0 | 9.0 | — |
| User value | 8.5 | 9.0 | +0.5 |
| Effectiveness | 8.5 | 9.0 | +0.5 |
| User experience | 9.0 | 9.0 | — |
| Visual / design | 8.5 | 9.0 | +0.5 |
| Technical quality | 9.0 | 9.0 | — |
| Completeness | 8.5 | 8.5 | — |
| Differentiation | 9.0 | 9.5 | +0.5 |
| Presentation | 8.5 | 9.0 | +0.5 |
| **Overall** | **8.75** | **9.00** | **+0.25** |

**Stopping condition met:** overall 9.0, no dimension below 8.5.

### Why Completeness stays at 8.5

Gemini advisory drafting is named explicitly in the brief and is not built. It
needs an API key this session does not have. Advisory prose is template-based
and the README says so. This is the one gap that requires input from you rather
than more work from me.

Also outstanding, all lower impact: parametric trigger monitor, telemetry
ingest path, in-memory approval state, no lint or type check.

## Iteration 5 — 2026-09-27: satellite verification

Earth Engine sign-in unblocked the last stage of the plan: scoring the
forecast against what satellites saw.

### What was built

- `verify/satellite.py` pulls GPM IMERG rain, the VIIRS Black Marble
  night-light drop and Sentinel-1 flood extent onto the hazard grid with
  `computePixels`, caching each layer on disk. Sentinel-1 uses a same-orbit
  pair and UN-SPIDER's change-detection thresholds. Night lights use the
  cloud-masked product, so a cloudy night reads as unknown, not as lights on.
- `verify/observed_skill.py` scores rain (with R-CLIPER alongside, to test the
  GFS switch), flood and outage forecasts. The flood score also reports where
  observed and predicted water sit, so a miss says what kind of miss it is.
- The post-event trigger rain index is now observed IMERG rainfall.
- The console's Checks tab shows each result with a verdict built from the
  scores, so a bad result cannot be worded as a good one.

### Bugs found

- **The Earth Engine terrain was a 3×3 grid.** The fetch asked for the DEM
  with no scale and got back nine pixels. That silently became the terrain
  for any run on a signed-in machine, and it moved Fani's flood-driven count
  from 1,475 to 2,672. The first Montha satellite scores were computed on it
  and are void. The fetch now requests the AWS path's resolution in
  half-degree blocks, and refuses any grid under 100 px a side. The fixed
  path agrees with AWS to 0.1–0.3 m median elevation and 99.9% land/sea.
- Undefined scores such as POD with nothing observed were NaN, which is not
  valid JSON and would have blanked the console. They are now null, and the
  export refuses NaN outright.
- Tests depended on whether the laptop was signed in to Earth Engine. The
  suite now forces it off.

### Results, reported as they came out

At T−48 h. The README carries the full table.

- **Rain, Montha:** GFS beats R-CLIPER on bias, correlation and error. The
  correlation of 0.32 is still weak.
- **Flood, both storms:** poor. Predicted water is on the coastal strip.
  Observed water is inland and higher up, where the ponding term cannot put
  it, because it weights low ground near the coast.
- **Outage, Fani:** 36 of 43 lit substation cells went dark, and the model
  expected 3 failures. Substation fragility does not capture area-wide
  outage.
- **Terrain sensitivity:** two fetches of the same DEM move Fani's newly-red
  count from 88 to 71.

### Deliberately not done

The flood term was not re-tuned against these results. Two storms are the
only test set, and fitting to them would turn the one honest check into a
flattering one. Any replacement term needs a third storm to judge it.

### Verification

- 191 tests (was 165), lint and types clean. New tests cover the grid
  request, cache, Sentinel-1 pair choice, night-light masking, every scoring
  function, null-not-NaN, and the degenerate-terrain guard.
- Both storms were replayed by the agent with the satellite checks on.
  Fani on AWS terrain reproduces the previous commit exactly, which isolates
  every figure change to the terrain source.

### Gemini drafting goes live, and meets its quota

The Gemini key arrived mid-iteration and lives in `.env`, which git ignores.
Only `run.sh` and the agent read it, and the test suite clears it.

- **First live run:** two of five advisories drafted, with Telugu that passed
  the number check. The other three failed with 503 overload, and then 429.
- **The 429 was a daily quota.** The free tier allows 20 requests a day for
  `gemini-3.7-flash`. Drafting one request per department costs about 38
  requests for a two-storm replay.
- **Fix:** one request per forecast cycle covers every department. Each
  advisory is still checked against its own facts only, so a number
  borrowed from another department's block is rejected. Replies are cached
  by prompt, so replays are free and reproducible. A full replay now costs
  8 requests.
- **Failure handling:** overloads and per-minute limits are retried. A daily
  quota is not, because waiting seconds cannot help, and the note says so.
  The run summary now reports how many advisories Gemini actually drafted.
  It used to name the model whenever a key was present.
- **Also corrected:** the README's architecture diagram showed Gemini reading
  IMD bulletins. That was planned and never built. Gemini drafts and
  translates advisories.

Today's quota was spent before the batching fix, so the committed runs are
template-drafted and say so. Re-running the two replays after the quota
resets drafts every cycle.
