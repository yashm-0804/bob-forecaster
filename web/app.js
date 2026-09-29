// @ts-check -- checked by tsc --strict in check.sh and CI (see tests/js/app-globals.d.ts).
/* The operator console. Served as /static/app.js by api/main.py. */

/* The payload's shape, as pipeline.export and api/main.py write it. Declared
   here so the checker holds every panel to it: a renamed field is a type
   error, not a panel that quietly shows "undefined". */
/**
 * @typedef {'red' | 'orange' | 'yellow' | 'green'} Severity
 * @typedef {{storm: string, lead_hours: number}} RunRef
 * @typedef {{id: string, name: string, ramp: string[], on?: boolean, coverage?: number}} Layer
 * @typedef {{lat_min: number, lat_max: number, lon_min: number, lon_max: number,
 *            rows: number, cols: number}} Grid
 * @typedef {{lat: number, lon: number, vmax_ms: number, pressure: number, rmax_km: number,
 *            time: string, grade: string, landfall?: boolean | string}} TrackPoint
 * @typedef {{name: string, asset_class: string, lat: number, lon: number, p_failure: number,
 *            p_failure_p10: number, p_failure_p90: number, wind_kmh: number | null,
 *            depth_m: number | null, rain_mm: number | null, driver: string,
 *            severity: Severity, consequence: number, criticality: number,
 *            criticality_basis: string, criticality_confidence: string}} Asset
 * @typedef {{identifier: string, recipient: string, lead_hours: number[], severity: Severity,
 *            headline: string, instruction: string, ensemble_note: string, languages: string[],
 *            pending_languages?: string[], drafted_by?: string, draft_notes?: string[],
 *            translations?: Record<string, Translation>,
 *            approved: boolean | null, approved_by?: string | null, cap_xml: string}} Advisory
 * @typedef {{headline?: string, instruction?: string, description?: string}} Translation
 * @typedef {{first_cycle?: boolean, previous_lead_hours?: number, summary: string,
 *            assets_newly_red: string[]}} Changes
 * @typedef {{hits: number, false_alarms: number, pod: number | null, far: number | null}} Contingency
 * @typedef {{median_km_from_coast: number | null, median_elevation_m: number | null}} Place
 * @typedef {{label: string, bias_ratio: number | null, correlation: number | null,
 *            rmse_mm: number | null, mean_forecast_mm: number | null,
 *            mean_observed_mm: number | null, cells: number,
 *            [threshold: string]: unknown}} RainScore
 * @typedef {{error?: string, forecast?: RainScore, r_cliper?: RainScore, threshold_mm: number,
 *            provenance: {start: string, end: string, source: string}}} RainCheck
 * @typedef {{error?: string, contingency_at_p50?: Contingency,
 *            where?: {observed_flooded?: Place, predicted_flooded?: Place},
 *            observed_flooded_cells: number, predicted_flooded_cells: number,
 *            brier_skill_vs_climatology: number | null, rule: string,
 *            provenance: {before: string, after: string, relative_orbit: number,
 *                         after_minus_landfall_days: number}}} FloodCheck
 * @typedef {{error?: string, note?: string, contingency?: Contingency, observed_outages: number,
 *            substations_with_lights: number, rank_correlation: number | null,
 *            mean_drop_top_quarter_predicted: number | null, mean_drop_rest: number | null,
 *            rule: string}} OutageCheck
 * @typedef {{available: boolean, rain?: RainCheck, flood?: FloodCheck, outage?: OutageCheck}} Observed
 * @typedef {{available: boolean, name: string, measures: string, dataset: string,
 *            requires: string, reason: string}} ObservationSource
 * @typedef {{source: string, issued_lead_hours?: number, members: number, steps_verified: number,
 *            mean_track_error_km: number, landfall_ensemble_mean_error_km?: number | null,
 *            landfall_error_km: number, envelope_hit_rate: number, caveat: string}} EnsembleSkill
 * @typedef {{imd_published_landfall_error_km: {[lead: string]: number}, source: string,
 *            ensemble_mean_error_at_landfall_km?: number, our_mean_landfall_spread_km?: number,
 *            interpretation: string}} VsImd
 * @typedef {{ensemble: EnsembleSkill, vs_imd: VsImd, observed?: Observed,
 *            observations: {sources: ObservationSource[], note: string}}} Verification
 * @typedef {{peril: string, p_partial_or_more: number, observed_index: number | string,
 *            unit: string, observed_payout: number, tiers: {threshold: number}[]}} Peril
 * @typedef {{zone: string, basis_risk: string, perils: Peril[], red_assets: number}} Zone
 * @typedef {{zones: Zone[], note: string, material_loss_rule: string}} Triggers
 * @typedef {{storm: string, storm_id: string, peak_grade: string, peak_wind_kmh: number,
 *            min_pressure_hpa: number, hours_to_landfall: number, landfall_time: string,
 *            ensemble_members: number,
 *            ensemble?: {source: string, model?: string, attribution?: string, reason?: string},
 *            p_gust_over_90kmh_land_pct: number, p_storm_tide_over_1m_land_pct: number,
 *            max_rain_mm: number, driver_split: {wind: number, flood: number},
 *            by_class: {[assetClass: string]: {total: number, expected_failures: number}},
 *            people_without_power_est: number, assets_scored: number,
 *            verification?: Verification, triggers?: Triggers}} Summary
 * @typedef {{summary: Summary, grid: Grid, layers: {[layer: string]: number[][] | undefined},
 *            land_mask?: number[][], track: TrackPoint[], landfall_index: number,
 *            assets: Asset[], advisories: Advisory[], changes?: Changes,
 *            approvals_unavailable?: string}} Run
 * @typedef {{nodes: {[tier: string]: number}, faults_injected: {[fault: string]: number},
 *            faults_caught: {[fault: string]: number},
 *            strongest_3h_fall_at_landfall?: {node_id: string, hpa: number} | null,
 *            clean_flagged: number, clean_readings: number, false_flag_rate: number,
 *            note: string}} NetworkReport
 * @typedef {{ok: boolean, status?: number, data?: unknown, needsCode?: boolean,
 *            needsSignIn?: boolean, detail: string,
 *            message?: string}} WriteResult
 * @typedef {{would_send_to: string, channels: string[], approved_by: string,
 *            cap_status: string, reason: string}} DispatchReceipt
 */
/* MapLibre, as far as this file uses it. The library ships no types to a
   browser script, so its surface is declared here and nothing beyond it. */
/**
 * @typedef {{features: {properties: any}[], lngLat: unknown}} MapEvent
 * @typedef {{
 *   flyTo(options: {center: number[], zoom: number}): void,
 *   remove(): void,
 *   on(type: string, layerOrFn: string | ((e?: any) => void), fn?: (e: MapEvent) => void): void,
 *   addControl(control: unknown, position: string): void,
 *   addSource(id: string, source: object): void,
 *   addLayer(layer: object): void,
 *   getLayer(id: string): unknown,
 *   setLayoutProperty(id: string, name: string, value: string): void,
 *   getCanvas(): HTMLCanvasElement,
 * }} MapLike
 */

/** An element the page is built with. Missing means the page is broken,
    which guard() then reports in the panel concerned.
    @param {string} id @returns {HTMLElement} */
function byId(id){
  const el = document.getElementById(id);
  if(!el) throw new Error(`the page has no #${id}`);
  return el;
}

/** @type {{[severity: string]: string}} */
const SEV = {red:'#f85149', orange:'#e3a008', yellow:'#d4a72c', green:'#3fb950'};
const API = '';
/** The run on screen; boot() and loadRun() set it. @type {Run | null} */
let RUN = null;
/** @type {MapLike | null} */
let map = null;

/** The run on screen, for code that only runs once there is one.
    @returns {Run} */
function run(){
  if(!RUN) throw new Error('no run is loaded');
  return RUN;
}

/** @type {Layer[]} */
const LAYERS = [
  {id:'p_gust_90kmh', name:'P(gust > 90 km/h)', ramp:['#1a1f2e','#4a3f7a','#8b5cf6','#f85149']},
  {id:'p_tide_1m',    name:'P(storm tide > 1 m)', ramp:['#0d1a26','#164e63','#0891b2','#67e8f9']},
  {id:'rain_mm',      name:'Rainfall accumulation', ramp:['#0d1f17','#14532d','#16a34a','#86efac']},
];

/* Which layer opens depends on the storm, not on a hardcoded choice.
   Defaulting to storm tide meant a weak, rain-driven storm like Montha opened
   with a layer holding 2 non-zero cells out of 2,193 — a console that looks
   like it has no data. Pick whichever layer actually carries signal. */
function pickDefaultLayer(){
  let best = null, bestFill = -1;
  for(const l of LAYERS){
    const g = run().layers[l.id]; if(!g) continue;
    let nonzero = 0, total = 0;
    for(const row of g) for(const v of row){ total++; if(v > 0.001) nonzero++; }
    const fill = total ? nonzero/total : 0;
    l.coverage = fill;
    if(fill > bestFill){ bestFill = fill; best = l; }
  }
  LAYERS.forEach(l => l.on = (l === best));
  return best;
}

/** @type {RunRef[]} */
let RUNS = [];
const stormsAvailable = () => [...new Set(RUNS.map(r => r.storm))];
/** @param {string} storm */
const leadsFor = storm => RUNS.filter(r => r.storm === storm)
  .map(r => r.lead_hours).sort((a, b) => b - a);

/* Every read goes through here, so a server error or an unreachable server
   is a message on screen, never a silent unhandled rejection. */
/** @param {string} url @returns {Promise<any>} parsed JSON, shape-checked by its caller's type */
async function getJson(url){
  const r = await fetch(url);
  let data = null;
  try { data = await r.json(); } catch(e) { /* not JSON: described below */ }
  if(!r.ok) throw new Error(describe(r.status, data));
  return data;
}

/** The run, if it has the shape every panel relies on; otherwise an error
    naming what is missing, so the console says so once instead of each panel
    failing on its own. @param {unknown} data @returns {Run} */
function checkRun(data){
  const r = /** @type {{[k: string]: unknown}} */ (data && typeof data === 'object' ? data : {});
  const s = /** @type {{[k: string]: unknown}} */ (r.summary && typeof r.summary === 'object' ? r.summary : {});
  const missing = [
    ...['summary', 'grid', 'layers'].filter(k => !r[k] || typeof r[k] !== 'object'),
    ...['track', 'assets', 'advisories'].filter(k => !Array.isArray(r[k])),
    ...(typeof s.storm === 'string' ? [] : ['summary.storm']),
    ...(typeof s.hours_to_landfall === 'number' ? [] : ['summary.hours_to_landfall']),
  ];
  if(missing.length) throw new Error(`the server sent a run this console cannot read (no ${missing.join(', ')})`);
  return /** @type {Run} */ (data);
}

/** The run list, if it is one. @param {unknown} data @returns {RunRef[]} */
function checkRuns(data){
  const ok = Array.isArray(data) && data.every(x => x && typeof x.storm === 'string'
                                                   && typeof x.lead_hours === 'number');
  if(!ok) throw new Error('the server sent a run list this console cannot read');
  return /** @type {RunRef[]} */ (data);
}

/** A server answer as a sentence: FastAPI's detail, or its validation errors.
    @param {number} status @param {unknown} data @returns {string} */
function describe(status, data){
  const d = data && typeof data === 'object' ? /** @type {{detail?: unknown}} */ (data).detail : null;
  if(typeof d === 'string') return d;
  if(Array.isArray(d) && d.length) return d.map(x => String(x && x.msg)).join('; ');
  return `The server answered ${status}.`;
}

/** @param {string} what @param {unknown} err */
function showFatal(what, err){
  document.body.innerHTML =
    `<div class="empty" role="alert" style="padding-top:80px">${escapeHtml(what)}<br><br>`
    + `<span style="color:var(--ink-faint)">${escapeHtml(errorText(err))}</span><br><br>`
    + '<button class="ok" data-action="reload">Try again</button></div>';
}

async function boot(){
  try { RUNS = checkRuns(await getJson(API+'/api/runs')); }
  catch(err){ showFatal('The console could not reach its server.', err); return; }
  if(!RUNS.length){
    document.body.innerHTML =
      '<div class="empty" style="padding-top:80px">No runs available.<br><br>'
      + 'Generate one: <code>python -c "import pipeline; '
      + 'pipeline.export(pipeline.run())"</code></div>';
    return;
  }
  // A storm and cycle named in the URL win, so a link can open a specific
  // moment in a specific storm. Otherwise T-48h, the first lead time at which
  // most departments can still act.
  const q = new URLSearchParams(location.search);
  const storm = (q.get('storm') || RUNS[0].storm).toLowerCase();
  const leads = leadsFor(storm);
  const lead = +(q.get('lead') || (leads.includes(48) ? 48 : leads[0]));
  const r = RUNS.find(x => x.storm === storm && x.lead_hours === lead) || RUNS[0];
  try { RUN = checkRun(await getJson(`${API}/api/run/${encodeURIComponent(r.storm)}/${Number(r.lead_hours)}`)); }
  catch(err){ showFatal(`Could not load ${r.storm} at T-${r.lead_hours}h.`, err); return; }

  /* Panels first, map last, each isolated.
     The map depends on a CDN and a remote basemap; the asset table and
     advisory queue depend on nothing but the payload already in hand. An
     operator who cannot reach a tile server must still be able to read which
     substations are at risk and approve an advisory, so a map failure must
     never take the console down with it. */
  guard('sidebar', renderSidebar);
  guard('assets', renderAssets);
  guard('advisories', renderAdvisories);
  guard('verify', renderVerify);
  guard('triggers', renderTriggers);
  renderNetwork().catch(e => console.warn('[console] network report', e));
  // Honour a deep link once the panels exist.
  if(location.hash) selectTab(location.hash.slice(1));
  showMap();
}

/* The map, in the best form available: MapLibre, else the offline canvas,
   else a sentence saying so. Every path that draws a map comes through here,
   so none can end on an empty rectangle. */
function showMap(){
  if(typeof maplibregl !== 'undefined'){ guard('map', initMap, fallbackMap); return; }
  // MapLibre is an ES module (web/map-loader.mjs), loaded alongside this
  // classic script; it announces itself. Waited for briefly, then given up on.
  const ready = () => { clearTimeout(wait); guard('map', initMap, fallbackMap); };
  const wait = setTimeout(() => {
    window.removeEventListener('maplibre-ready', ready);
    guard('map', initMap, fallbackMap);
  }, mapLibraryWaitMs);
  window.addEventListener('maplibre-ready', ready, {once: true});
}
/** How long to wait for the map library before drawing the offline map. */
let mapLibraryWaitMs = 4000;
function fallbackMap(){
  guard('fallback-map', drawOfflineMap, () => {
    offlinePaint = null;
    byId('map').innerHTML =
      '<div class="empty" style="padding-top:120px">Map unavailable.<br><br>'
      + 'Asset rankings and advisories are unaffected and remain usable '
      + 'in the panel on the right.</div>';
  });
}

/* IMD best-track times are UTC but carry no timezone suffix. The browser
   reads a bare ISO datetime as *local* time, so on an IST machine every time
   in the console was shifted 5 h 30 m -- Montha's 21:00 UTC landfall showed
   as 15:30. Treat unsuffixed timestamps as the UTC they are. */
/** @param {string} iso */
function fmtUtc(iso){
  const s = String(iso);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
  return d.toUTCString().slice(5, 22);
}

/** @type {{[c: string]: string}} */
const ENTITIES = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
/** Text, made safe to put in HTML. @param {unknown} s @returns {string} */
function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c => ENTITIES[c]);
}

/** What went wrong, as text, whatever was thrown. @param {unknown} err */
function errorText(err){
  return err instanceof Error ? err.message : String(err);
}

/* Each panel draws on its own, so one failure cannot blank the console. A
   failure is shown in the panel itself -- an officer must know a list is
   missing, not see an empty one and assume nothing is at risk. */
/** @type {{[panel: string]: string}} */
const PANEL_OF = {sidebar: 'storm-block', assets: 'view-assets', advisories: 'view-advisories',
                  verify: 'view-verify', triggers: 'view-triggers'};
/** @param {string} what @param {() => void} fn @param {(err: unknown) => void} [onFail] */
function guard(what, fn, onFail){
  try { fn(); }
  catch(err){
    console.error(`[console] ${what} failed:`, err);
    if(onFail) { onFail(err); return; }
    const el = PANEL_OF[what] && document.getElementById(PANEL_OF[what]);
    if(el) el.innerHTML = `<div class="empty" role="alert">This panel could not be drawn: `
      + `${escapeHtml(errorText(err))}. The other panels are unaffected.</div>`;
  }
}

function renderSidebar(){
  const s = run().summary;
  // The switcher is the argument, not a convenience. Montha at 93 km/h scores
  // as negligible on wind and is entirely flood-driven; Fani at 213 km/h is
  // not. Being able to flip between them turns the project's central claim
  // from an assertion into something a reviewer checks in two clicks.
  const cur = s.storm.toLowerCase(), storms = stormsAvailable(), leads = leadsFor(cur);
  const ch = run().changes;
  byId('storm-block').innerHTML = `
    ${storms.length > 1 ? `<div class="switcher">${storms.map(st => `
      <button class="swbtn ${st === cur ? 'on' : ''}" data-action="load" data-storm="${escapeHtml(st)}"
              data-lead="${leadsFor(st).includes(s.hours_to_landfall) ? s.hours_to_landfall : leadsFor(st)[0]}">
        ${escapeHtml(st.charAt(0).toUpperCase() + st.slice(1))}
      </button>`).join('')}</div>` : ''}
    ${leads.length > 1 ? `<div class="cycles" role="group" aria-label="Forecast cycle">${leads.map(l => `
      <button class="cyc ${l === s.hours_to_landfall ? 'on' : ''}" data-action="load" data-storm="${escapeHtml(cur)}" data-lead="${Number(l)}">T&minus;${Number(l)}h</button>`).join('')}</div>` : ''}
    <div class="storm-name">${escapeHtml(s.storm)}</div>
    <div class="storm-sub">${escapeHtml(s.storm_id)} · IMD ${escapeHtml(s.peak_grade)} · peak ${Number(s.peak_wind_kmh)} km/h · ${Number(s.min_pressure_hpa)} hPa</div>
    <div class="countdown">T−${Number(s.hours_to_landfall)}h<small>to landfall · ${fmtUtc(s.landfall_time)} UTC</small></div>
    ${ch ? `<div class="changes ${ch.first_cycle ? 'first' : ''}">
      <div class="changes-h">${ch.first_cycle ? 'First cycle' : `Since T&minus;${Number(ch.previous_lead_hours)}h`}</div>
      <div>${escapeHtml(ch.summary)}</div>
      ${!ch.first_cycle && ch.assets_newly_red.length ? `<div class="changes-list">Newly red: ${
        ch.assets_newly_red.slice(0, 4).map(escapeHtml).join(', ')}${
        ch.assets_newly_red.length > 4 ? ` +${ch.assets_newly_red.length - 4} more` : ''}</div>` : ''}
    </div>` : ''}`;

  byId('hazard-stats').innerHTML = `
    ${stat('Ensemble members', s.ensemble_members)}
    ${stat('Forecast source', s.ensemble && s.ensemble.source === 'weatherlab'
        ? s.ensemble.model + ' (issued)' : 'perturbed best track')}
    ${stat('Land area, P(gust>90km/h)', s.p_gust_over_90kmh_land_pct+'%')}
    ${stat('Land area, P(tide>1m)', s.p_storm_tide_over_1m_land_pct+'%')}
    ${stat('Peak rainfall', s.max_rain_mm+' mm')}
    ${stat('Dominant driver', driverLabel(s.driver_split))}
    ${stat('Wind-driven assets', s.driver_split.wind.toLocaleString())}`;

  pickDefaultLayer();
  byId('layers').innerHTML = LAYERS.map(l=>`
    <div class="layer">
      <input type="checkbox" id="L-${l.id}" ${l.on?'checked':''}>
      <span class="swatch" style="background:linear-gradient(90deg,${l.ramp.join(',')})"></span>
      <label for="L-${l.id}">${l.name}</label>
    </div>`).join('');
  LAYERS.forEach(l=>{
    byId('L-'+l.id).addEventListener('change', e=>{
      if(map && map.getLayer('lyr-'+l.id))
        map.setLayoutProperty('lyr-'+l.id,'visibility',
          /** @type {HTMLInputElement} */ (e.target).checked?'visible':'none');
    });
  });

  const bc = s.by_class;
  byId('exposure-stats').innerHTML =
    Object.entries(bc).map(([k,v])=>
      stat(k.replace(/_/g,' '), Number(v.total).toLocaleString(),
           ` <span style="color:var(--ink-faint);font-weight:400">/ ${escapeHtml(v.expected_failures)} exp.</span>`)
    ).join('') +
    stat('People without power (est.)', Number(s.people_without_power_est).toLocaleString());

  byId('caveats').textContent =
    'Surge is a screening estimate, not a coupled hydrodynamic simulation. '+
    'The low-voltage grid is not modelled: OSM does not map it, so pole and '+
    'transformer damage is not counted. '+
    'Population figures are order-of-magnitude.';
}
/* A sidebar figure. Label and value are text and escaped here; `extra` is
   markup this file wrote. */
/** @param {string} label @param {unknown} value @param {string} [extra] */
const stat = (label, value, extra = '') =>
  `<div class="stat"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}${extra}</b></div>`;
/** @param {{wind: number, flood: number}} d */
function driverLabel(d){
  const t = d.wind + d.flood;
  if(!t) return '—';
  return d.flood >= d.wind
    ? `flood ${Math.round(100*d.flood/t)}%` : `wind ${Math.round(100*d.wind/t)}%`;
}

function initMap(){
  if(typeof maplibregl === 'undefined')
    throw new Error('maplibre-gl did not load (CDN blocked or offline)');

  const g = run().grid;
  /** @type {MapLike} */
  const mine = new maplibregl.Map({
    container:'map',
    style:'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    bounds:[[g.lon_min,g.lat_min],[g.lon_max,g.lat_max]], fitBoundsOptions:{padding:30}
  });
  map = mine;
  mine.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');

  /* The library loading is not the same as the map working. If the basemap
     style cannot be fetched, MapLibre constructs fine and fails later,
     asynchronously -- leaving a black rectangle where a map should be, with
     nothing thrown for a try/catch to catch. So treat "did not become ready"
     as a failure too, and hand over to the offline renderer. */
  let ready = false;
  /** @param {string} reason */
  const giveUp = reason => {
    // Only this map's own timer may give up on it. After a storm switch the
    // old timer still fires, and must not take down the new map.
    if(ready || map !== mine) return;
    ready = true;
    clearTimeout(timer);
    try { mine.remove(); } catch(e) { /* already gone */ }
    map = null;
    console.warn('[console] basemap unusable:', reason, '— drawing offline map');
    fallbackMap();
  };

  mine.on('load', ()=>{
    if(map !== mine) return;
    ready = true;
    clearTimeout(timer);
    guard('map-layers', ()=>{ addHazardLayers(mine); addTrack(mine); addAssets(mine); });
  });
  mine.on('error', /** @param {{error?: {message?: string}}} [e] */
          e => giveUp((e && e.error && e.error.message) || 'style error'));
  const timer = setTimeout(()=> giveUp('timed out waiting for the basemap'), 6000);
}

/** A canvas's 2-D context; a browser without one cannot draw either map.
    @param {HTMLCanvasElement} cv */
function context2d(cv){
  const ctx = cv.getContext('2d');
  if(!ctx) throw new Error('this browser gives no 2-D canvas');
  return ctx;
}

/* Hazard grids arrive as 2-D arrays. Paint each to a canvas and add it as an
   image source — far cheaper than one GeoJSON feature per cell. */
/** @param {MapLike} map */
function addHazardLayers(map){
  const g = run().grid;
  LAYERS.forEach(l=>{
    const data = run().layers[l.id]; if(!data) return;
    const rows = data.length, cols = data[0].length;
    let max = 0; for(const r of data) for(const v of r) if(v>max) max=v;
    if(max<=0) max = 1;

    const cv = document.createElement('canvas');
    cv.width = cols; cv.height = rows;
    const ctx = context2d(cv), img = ctx.createImageData(cols, rows);
    for(let i=0;i<rows;i++) for(let j=0;j<cols;j++){
      const t = Math.min(data[i][j]/max, 1);
      // Row 0 is the southern edge; canvas y grows downward, so flip.
      const px = (((rows-1-i)*cols)+j)*4;
      const [r,gg,b] = ramp(l.ramp, t);
      img.data[px]=r; img.data[px+1]=gg; img.data[px+2]=b;
      img.data[px+3] = t < 0.04 ? 0 : Math.round(200*Math.min(t*1.5,1));
    }
    ctx.putImageData(img,0,0);

    map.addSource('src-'+l.id, {type:'image', url:cv.toDataURL(),
      coordinates:[[g.lon_min,g.lat_max],[g.lon_max,g.lat_max],
                   [g.lon_max,g.lat_min],[g.lon_min,g.lat_min]]});
    map.addLayer({id:'lyr-'+l.id, type:'raster', source:'src-'+l.id,
      paint:{'raster-opacity':0.68, 'raster-resampling':'linear'},
      layout:{visibility: l.on?'visible':'none'}});
  });
}
/* Offline map.

   Everything needed to draw this coast is already in the payload: a land/sea
   mask, the hazard grids, the track and every asset's position. Only the map
   library and the basemap tiles come from outside, so when those are blocked
   the answer is not an empty column -- it is the same map drawn on a canvas.

   Deliberately plain: no pan, no zoom, no labels. It exists so that a console
   on a venue network that blocks CDNs still shows where the storm went and
   which assets are under it. */
/** The offline map's painter while it is showing, and the asset it rings. */
/** @type {(() => void) | null} */
let offlineResize = null;
/** @type {(() => void) | null} */
let offlinePaint = null;
/** @type {Asset | null} */
let offlineFocus = null;
function drawOfflineMap(){
  const host = byId('map');
  const g = run().grid, mask = run().land_mask;
  if(!mask) throw new Error('no land mask in this run');

  host.innerHTML = '<canvas id="offline-map" role="img" aria-label="Offline map of the '
    + 'hazard grid, track and assets. The same assets are listed, ranked, in the Assets panel."></canvas>'
    + '<div id="offline-note">Offline map — basemap unavailable, drawn from run data</div>';
  const cv = /** @type {HTMLCanvasElement} */ (byId('offline-map'));

  const paint = () => {
    // Measure the box, not the canvas inside it. The canvas is absolutely
    // positioned precisely so that it can never feed its own size back into
    // this measurement -- doing so once produced a 10,306 px tall canvas.
    const box = host.getBoundingClientRect();
    const w = Math.round(box.width), h = Math.round(box.height);
    if(w < 20 || h < 20) return;
    // Cap the backing store: a high-DPR screen on a tall panel can otherwise
    // ask for a canvas larger than the browser will allocate.
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = Math.min(w * dpr, 4096);
    cv.height = Math.min(h * dpr, 4096);
    const ctx = context2d(cv);
    ctx.setTransform(cv.width / w, 0, 0, cv.height / h, 0, 0);

    // Keep the aspect ratio honest rather than stretching the coast to fit.
    const gw = g.lon_max - g.lon_min, gh = g.lat_max - g.lat_min;
    const scale = Math.min(w / gw, h / gh) * 0.92;
    const ox = (w - gw * scale) / 2, oy = (h - gh * scale) / 2;
    /** @param {number} lon */
    const X = lon => ox + (lon - g.lon_min) * scale;
    /** @param {number} lat */
    const Y = lat => oy + (g.lat_max - lat) * scale;   // north at the top

    ctx.fillStyle = '#0a0f16'; ctx.fillRect(0, 0, w, h);   // sea

    const rows = mask.length, cols = mask[0].length;
    const cw = (gw * scale) / cols, ch = (gh * scale) / rows;

    ctx.fillStyle = '#1b2430';                              // land
    for(let i = 0; i < rows; i++)
      for(let j = 0; j < cols; j++)
        if(mask[i][j] > 0.5)
          ctx.fillRect(ox + j*cw, oy + (rows-1-i)*ch, Math.ceil(cw)+1, Math.ceil(ch)+1);

    // Everything from here on is drawn inside the grid's own box: the
    // track starts days before landfall, often far out to sea, and drawn
    // unclipped it ran off the map's edge into the page.
    ctx.save();
    ctx.beginPath(); ctx.rect(ox, oy, gw * scale, gh * scale); ctx.clip();

    // Every checked layer, as the checkboxes say, each translucent.
    for(const layer of LAYERS.filter(l => l.on)){
      const data = run().layers[layer.id];
      if(!data) continue;
      let max = 0;
      for(const row of data) for(const v of row) if(v > max) max = v;
      if(max > 0){
        const lr = data.length, lc = data[0].length;
        const lw = (gw * scale) / lc, lh = (gh * scale) / lr;
        for(let i = 0; i < lr; i++) for(let j = 0; j < lc; j++){
          const t = data[i][j] / max;
          if(t < 0.05) continue;
          const [r, gg, b] = ramp(layer.ramp, t);
          // Kept translucent on purpose. At full opacity a widespread field
          // like rainfall covers the whole land area and the coast -- the one
          // thing that makes this readable as a map -- disappears under it.
          ctx.fillStyle = `rgba(${r},${gg},${b},${Math.min(t*0.75, 0.55)})`;
          ctx.fillRect(ox + j*lw, oy + (lr-1-i)*lh, Math.ceil(lw)+1, Math.ceil(lh)+1);
        }
      }
    }

    // Coastline last, so it survives whatever hazard layer is showing. Traced
    // by marking land cells that touch sea -- crude, but it is the difference
    // between a map and a coloured grid.
    ctx.fillStyle = '#8da9c4';
    /** @param {number} i @param {number} j */
    const isLand = (i, j) =>
      i >= 0 && j >= 0 && i < rows && j < cols && mask[i][j] > 0.5;
    for(let i = 0; i < rows; i++) for(let j = 0; j < cols; j++){
      if(!isLand(i, j)) continue;
      if(isLand(i-1,j) && isLand(i+1,j) && isLand(i,j-1) && isLand(i,j+1)) continue;
      ctx.fillRect(ox + j*cw, oy + (rows-1-i)*ch, Math.max(cw, 1.5), Math.max(ch, 1.5));
    }

    ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2; ctx.setLineDash([5, 3]);
    ctx.beginPath();
    run().track.forEach((p, i) => i ? ctx.lineTo(X(p.lon), Y(p.lat)) : ctx.moveTo(X(p.lon), Y(p.lat)));
    ctx.stroke(); ctx.setLineDash([]);

    run().assets.filter(a => a.severity !== 'green').forEach(a => {
      ctx.beginPath();
      ctx.arc(X(a.lon), Y(a.lat), 2.5 + 4*Math.min(a.consequence/2, 1), 0, Math.PI*2);
      ctx.fillStyle = SEV[a.severity]; ctx.globalAlpha = 0.85; ctx.fill();
      ctx.globalAlpha = 1;
    });

    const lf = run().track[run().landfall_index];
    if(lf){
      ctx.beginPath(); ctx.arc(X(lf.lon), Y(lf.lat), 7, 0, Math.PI*2);
      ctx.fillStyle = '#f85149'; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
    }

    // The asset last picked in the table, ringed so it can be found.
    if(offlineFocus){
      ctx.beginPath(); ctx.arc(X(Number(offlineFocus.lon)), Y(Number(offlineFocus.lat)), 11, 0, Math.PI*2);
      ctx.lineWidth = 2.5; ctx.strokeStyle = '#ffffff'; ctx.stroke();
    }
    ctx.restore();
  };

  offlineFocus = null;
  offlinePaint = paint;
  paint();
  // One resize handler at a time: each storm switch redraws the offline map,
  // and adding a handler per draw left every earlier map repainting too.
  if(offlineResize) window.removeEventListener('resize', offlineResize);
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let t;
  offlineResize = () => { clearTimeout(t); t = setTimeout(paint, 120); };
  window.addEventListener('resize', offlineResize);
  LAYERS.forEach(l => {
    const box = /** @type {HTMLInputElement | null} */ (document.getElementById('L-' + l.id));
    if(box) box.addEventListener('change', () => { l.on = box.checked; paint(); });
  });
}

/** A colour from a ramp, for 0 <= t <= 1. @param {string[]} colors @param {number} t
    @returns {number[]} r, g, b */
function ramp(colors, t){
  const seg = 1/(colors.length-1), i = Math.min(Math.floor(t/seg), colors.length-2);
  const f = (t - i*seg)/seg;
  /** @param {string} c */
  const hex = c => [parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16)];
  const a = hex(colors[i]), b = hex(colors[i+1]);
  return a.map((v,k)=>Math.round(v + (b[k]-v)*f));
}

/** What a track point's popup says; every value escaped or made a number.
    @param {TrackPoint} p */
function trackPointHtml(p){
  const landfall = p.landfall === 'true' || p.landfall === true;
  return `<b>${landfall ? 'LANDFALL · ' : ''}${escapeHtml(p.grade)}</b><br>`
    + `${escapeHtml(fmtUtc(p.time))} UTC<br>`
    + `${Math.round(Number(p.vmax_ms) * 3.6)} km/h · ${escapeHtml(p.pressure)} hPa · `
    + `Rmax ${escapeHtml(p.rmax_km)} km`;
}

/** @param {MapLike} map */
function addTrack(map){
  const pts = run().track.map(p=>[p.lon,p.lat]);
  map.addSource('track',{type:'geojson',data:{type:'Feature',geometry:{type:'LineString',coordinates:pts}}});
  map.addLayer({id:'track-line',type:'line',source:'track',
    paint:{'line-color':'#58a6ff','line-width':2.5,'line-dasharray':[2,1.4]}});

  map.addSource('track-pts',{type:'geojson',data:{type:'FeatureCollection',
    features:run().track.map((p,i)=>({type:'Feature',
      geometry:{type:'Point',coordinates:[p.lon,p.lat]},
      properties:{...p, landfall: i===run().landfall_index}}))}});
  map.addLayer({id:'track-dots',type:'circle',source:'track-pts',
    paint:{'circle-radius':['case',['get','landfall'],7,3.5],
           'circle-color':['case',['get','landfall'],'#f85149','#58a6ff'],
           'circle-stroke-width':['case',['get','landfall'],2,0],
           'circle-stroke-color':'#fff'}});

  map.on('click','track-dots',e=>{
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(trackPointHtml(e.features[0].properties)).addTo(map);
  });
  map.on('mouseenter','track-dots',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','track-dots',()=>map.getCanvas().style.cursor='');
}

/** @param {MapLike} map */
function addAssets(map){
  const shown = run().assets.filter(a=>a.severity!=='green');
  map.addSource('assets',{type:'geojson',data:{type:'FeatureCollection',
    features:shown.map(a=>({type:'Feature',
      geometry:{type:'Point',coordinates:[a.lon,a.lat]},properties:a}))}});
  map.addLayer({id:'assets-pt',type:'circle',source:'assets',
    paint:{
      'circle-radius':['interpolate',['linear'],['get','p_failure'],0,3.5,1,9],
      'circle-color':['match',['get','severity'],
        'red',SEV.red,'orange',SEV.orange,'yellow',SEV.yellow,SEV.green],
      'circle-stroke-width':1,'circle-stroke-color':'rgba(0,0,0,.55)','circle-opacity':.9}});

  map.on('click','assets-pt',e=>{
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(assetDetailHtml(e.features[0].properties)).addTo(map);
  });
  map.on('mouseenter','assets-pt',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','assets-pt',()=>map.getCanvas().style.cursor='');
}

/* What an asset marker says: one builder for the map's popup and the map's
   detail card, so a keyboard user reaching an asset from the table reads the
   same thing a mouse user reads from its marker. Everything is escaped. */
/** @param {Asset} a */
function assetDetailHtml(a){
  /** @param {number} x */
  const pct = x => (Number(x) * 100).toFixed(0);
  return `<b>${escapeHtml(a.name)}</b><br>`
    + `<span style="color:#8b949e">${escapeHtml(String(a.asset_class).replace(/_/g,' '))}</span><br><br>`
    + `<b style="color:${SEV[a.severity] || SEV.green}">${pct(a.p_failure)}% failure probability</b><br>`
    + `<span style="color:#8b949e">ensemble ${pct(a.p_failure_p10)}–${pct(a.p_failure_p90)}%</span><br><br>`
    + `wind ${escapeHtml(a.wind_kmh)} km/h · water ${escapeHtml(a.depth_m)} m · `
    + `rain ${escapeHtml(a.rain_mm)} mm<br>driver: <b>${escapeHtml(a.driver)}</b>`;
}

/* The card over the map that a table row fills. It lives inside #map, which
   the offline and "unavailable" renderers replace, so it is made on demand. */
function mapDetail(){
  let card = document.getElementById('map-detail');
  if(!card){
    card = document.createElement('div');
    card.id = 'map-detail';
    card.setAttribute('role', 'status');
    byId('map').appendChild(card);
  }
  return card;
}

/* A table row, activated: the map goes to the asset if it can, and the card
   says what the marker would -- in every map mode, including none. */
/** The rows the asset table shows, by rank. @type {Asset[]} */
let shownAssets = [];
/** @param {Asset | undefined} a */
function showAsset(a){
  if(!a) return;
  if(map) map.flyTo({center: [Number(a.lon), Number(a.lat)], zoom: 11});
  else if(offlinePaint){ offlineFocus = a; offlinePaint(); }
  const card = mapDetail();
  card.innerHTML = assetDetailHtml(a)
    + '<button class="ghost" data-action="close-detail" aria-label="Close asset details">Close</button>';
  card.hidden = false;
}

function renderAssets(){
  const at = run().assets.filter(a=>a.severity!=='green');
  byId('n-assets').textContent = String(at.length);
  const scored = run().summary.assets_scored, shipped = run().assets.length;
  byId('rank-note').innerHTML =
    `Ranked by <b>expected consequence</b> — likelihood &times; how much depends on it. `
    + `Showing the worst ${Math.min(at.length,150).toLocaleString()} of `
    + `${shipped.toLocaleString()} sent to the browser, from `
    + `${scored.toLocaleString()} scored.`;
  shownAssets = at.slice(0, 150);
  byId('view-assets').innerHTML = at.length ? shownAssets.map((a, k)=>`
    <div class="row" role="button" data-action="asset" data-rank="${k}" tabindex="0"
         aria-label="${escapeHtml(a.name)}: show on the map">
      <div class="row-top">
        <span class="dot" style="background:${SEV[a.severity]}"></span>
        <span class="row-name">${escapeHtml(a.name)}</span>
        <span class="row-p" style="color:${SEV[a.severity]}" title="expected consequence">${a.consequence.toFixed(2)}</span>
      </div>
      <div class="row-meta">
        <span class="pill">${escapeHtml(String(a.asset_class).replace(/_/g,' '))}</span>
        <span>${(a.p_failure*100).toFixed(0)}% likely</span>
        <span>&times;${a.criticality.toFixed(1)} critical</span>
        <span>${escapeHtml(a.driver)}</span>
      </div>
      <div class="row-basis conf-${String(a.criticality_confidence).replace(/[^a-z-]/g,'')}">${escapeHtml(a.criticality_basis)}</div>
    </div>`).join('') : '<div class="empty">No assets above the alerting threshold.</div>';
}

/** Every translation an approval covers, in full: the officer approves the
    text in each language, so each is read here, not only in the raw XML. The
    text is marked with its language, so a screen reader reads it in that
    language's voice. Only the languages the advisory carries -- its CAP --
    are shown. @param {Advisory} a */
function translationsHtml(a){
  const texts = a.translations || {};
  return a.languages.filter(lang => lang !== 'en-IN' && texts[lang]).map(lang => {
    const t = texts[lang];
    return `
      <section class="adv-tr" aria-label="Text in ${escapeHtml(lang)}">
        <div class="adv-tr-lang">${escapeHtml(lang)}</div>
        <div lang="${escapeHtml(lang)}">
          <div class="adv-tr-headline">${escapeHtml(t.headline || '')}</div>
          <div class="adv-tr-body">${escapeHtml(t.instruction || '')}</div>
          <div class="adv-tr-note">${escapeHtml(t.description || '')}</div>
        </div>
      </section>`;
  }).join('');
}

function renderAdvisories(){
  const advs = run().advisories;
  byId('n-adv').textContent = String(advs.length);
  // The approval record could not be read: say so, rather than let every
  // advisory look unapproved.
  const unknown = run().approvals_unavailable;
  byId('view-advisories').innerHTML = (unknown
    ? `<div class="empty" role="alert">${escapeHtml(unknown)}</div>` : '')
    + (advs.length ? advs.map(a=>`
    <div class="adv" id="adv-${escapeHtml(a.identifier)}">
      <div class="adv-head">
        <div class="adv-to">${escapeHtml(a.recipient)} · useful T−${Number(a.lead_hours[0])}…${Number(a.lead_hours[1])}h</div>
        <div class="adv-headline" style="color:${SEV[a.severity]}">${escapeHtml(a.headline)}</div>
      </div>
      <div class="adv-body">${escapeHtml(a.instruction)}</div>
      <div class="adv-note">${escapeHtml(a.ensemble_note)}</div>${translationsHtml(a)}
      <div class="adv-foot">
        ${a.approved === null ? '<span class="approved">Approval state unknown</span> ' : ''}${a.approved
          ? `<span class="approved">✓ Approved by ${escapeHtml(a.approved_by)}</span>
             <button class="ghost" data-action="revoke" data-id="${escapeHtml(a.identifier)}">Withdraw</button>`
          : `<button class="ok" data-action="approve" data-id="${escapeHtml(a.identifier)}">Approve</button>`}
        <button class="ghost" data-action="cap" data-id="${escapeHtml(a.identifier)}">CAP XML</button>
        <button class="ghost" data-action="dispatch" data-id="${escapeHtml(a.identifier)}"${a.approved ? ''
          : ' disabled title="Approve first: nothing is dispatched without a named approval"'}>Dispatch</button>
        <span class="langs">${a.languages.map(l=>`<span class="lang">${escapeHtml(l)}</span>`).join('')}${
          (a.pending_languages||[]).map(l=>`<span class="lang pending" title="No verified text in this language yet">${escapeHtml(l)} pending</span>`).join('')}</span>
      </div>
      <div class="adv-prov">Drafted by <b>${escapeHtml(a.drafted_by || 'template')}</b>${
        (a.draft_notes||[]).length ? ` &middot; ${(a.draft_notes||[]).map(n=>escapeHtml(n)).join(' ')}` : ''}</div>
      <div class="adv-result" id="res-${escapeHtml(a.identifier)}" role="status" hidden></div>
      <pre id="cap-${escapeHtml(a.identifier)}" hidden></pre>
    </div>`).join('') : '<div class="empty">No department advisory met the alerting threshold for this run.</div>');
}

/* The claim this panel exists to keep honest: predict, check, and publish the
   misses. Anything not yet checkable says so rather than showing a number. */
function renderVerify(){
  const v = run().summary.verification;
  if(!v){ byId('view-verify').innerHTML =
    '<div class="empty">This run predates the verification step.</div>'; return; }

  const e = v.ensemble, imd = v.vs_imd, ens = run().summary.ensemble || {source: 'perturbed'};
  const ran = v.observed && v.observed.available;
  const obs = ran ? '' : v.observations.sources.map(s=>`
    <div class="vrow">
      <div class="vrow-top">
        <span class="vstate ${s.available?'ok':'pending'}">${s.available?'available':'not available'}</span>
        <b>${escapeHtml(s.name)}</b>
      </div>
      <div class="vmeta">Measures ${escapeHtml(s.measures)}</div>
      <div class="vmeta"><code>${escapeHtml(s.dataset)}</code> &middot; needs ${escapeHtml(s.requires)}</div>
      <div class="vwhy">${escapeHtml(s.reason)}</div>
    </div>`).join('');

  byId('view-verify').innerHTML = `
    <div class="vsec">
      <h4>Ensemble against the observed track</h4>
      <div class="vsource ${e.source === 'weatherlab' ? 'real' : 'self'}">${
        e.source === 'weatherlab'
          ? `Real forecast &middot; ${escapeHtml(ens.model)} issued ${escapeHtml(e.issued_lead_hours)} h before landfall`
          : 'Self-verification &middot; perturbed from the best track'}</div>
      <div class="vstat"><span>Members</span><b>${escapeHtml(e.members)}</b></div>
      <div class="vstat"><span>Track positions checked</span><b>${escapeHtml(e.steps_verified)}</b></div>
      <div class="vstat"><span>Mean track error</span><b>${escapeHtml(e.mean_track_error_km)} km</b></div>
      ${e.landfall_ensemble_mean_error_km != null ? `<div class="vstat"><span>Ensemble-mean error at landfall time</span><b>${escapeHtml(e.landfall_ensemble_mean_error_km)} km</b></div>` : ''}
      <div class="vstat"><span>Average member error at landfall time</span><b>${escapeHtml(e.landfall_error_km)} km</b></div>
      <div class="vstat"><span>Truth inside the spread</span><b>${num(e.envelope_hit_rate*100, 0)}%</b></div>
      <div class="vwhy">${escapeHtml(e.caveat)}</div>
      ${ens.attribution ? `<div class="vmeta">Forecast data: ${escapeHtml(ens.attribution)}</div>` : ''}
      ${ens.reason ? `<div class="vmeta">${escapeHtml(ens.reason)}</div>` : ''}
    </div>

    <div class="vsec">
      <h4>Against IMD's published operational error</h4>
      <div class="vstat"><span>IMD 24 h</span><b>${escapeHtml(imd.imd_published_landfall_error_km['24h'])} km</b></div>
      <div class="vstat"><span>IMD 48 h</span><b>${escapeHtml(imd.imd_published_landfall_error_km['48h'])} km</b></div>
      <div class="vstat"><span>IMD 72 h</span><b>${escapeHtml(imd.imd_published_landfall_error_km['72h'])} km</b></div>
      <div class="vstat"><span>${imd.source === 'weatherlab' ? 'Ensemble-mean error, this storm' : 'Our spread at landfall'}</span><b>${
        escapeHtml(imd.source === 'weatherlab' ? imd.ensemble_mean_error_at_landfall_km : imd.our_mean_landfall_spread_km)} km</b></div>
      <div class="vwhy">${escapeHtml(imd.interpretation)}</div>
    </div>

    <div class="vsec" id="net-sec"><h4>Sensor network (simulated)</h4>
      <div class="vwhy">No network simulation for this storm.</div></div>

    <div class="vsec">
      <h4>Against what actually happened</h4>
      ${observedChecks(v.observed)}
      ${obs}
      <div class="vwhy">${escapeHtml(v.observations.note)}</div>
    </div>`;
}

/* Satellite checks. Every sentence here is built from the scores, so a bad
   result reads as bad: nothing is phrased by hand to soften it. */
/** A figure, or a dash when there is none. @param {number | null | undefined} x @param {number} [d] */
const num = (x, d=2) => x == null ? '&mdash;' : Number(x).toFixed(d);
// Run timestamps are UTC, some without an offset: read them as UTC, not local.
/** @param {string | undefined} iso */
const day = iso => iso ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')
  .toLocaleDateString('en-GB', {day:'numeric', month:'short', timeZone:'UTC'}) : '?';
/** @param {Observed | undefined} o */
function observedChecks(o){
  if(!o || !o.available) return '';
  /** @type {string[]} */
  const parts = [];

  const r = o.rain;
  if(r && r.error) parts.push(checkError('Rain against GPM IMERG', r.error));
  else if(r && r.forecast){
    const f = r.forecast, c = r.r_cliper, k = `over_${r.threshold_mm}mm`;
    const cols = c ? [f, c] : [f];
    /** @param {string} label @param {(score: RainScore) => string} fn */
    const row = (label, fn) => `<tr><td>${label}</td>${cols.map(x=>`<td>${fn(x)}</td>`).join('')}</tr>`;
    const better = c && f.rmse_mm != null && c.rmse_mm != null
      ? (f.rmse_mm < c.rmse_mm ? 'lower' : 'higher') : null;
    parts.push(`<div class="vrow">
      <div class="vrow-top"><b>Rain against GPM IMERG</b></div>
      <div class="vverdict ${rainClass(f)}">
        ${escapeHtml(f.label.toUpperCase())} ${amountPhrase(f.bias_ratio)};
        it ${placePhrase(f.correlation)} (correlation ${num(f.correlation)}).
        ${better ? `Its error is ${better} than R-CLIPER's.` : ''}</div>
      <table class="vtab"><tr><th></th>${cols.map(x=>`<th>${escapeHtml(x.label)}</th>`).join('')}</tr>
        ${row('Mean forecast, mm', x=>num(x.mean_forecast_mm, 0))}
        ${row('Bias (1 = right total)', x=>num(x.bias_ratio))}
        ${row('Correlation with observed', x=>num(x.correlation))}
        ${row('RMSE, mm', x=>num(x.rmse_mm, 0))}
        ${row(`Hit score over ${Number(r.threshold_mm)} mm (CSI)`,
              x=>num(/** @type {{csi?: number | null} | undefined} */ (x[k])?.csi))}
      </table>
      <div class="vmeta">Observed mean ${num(f.mean_observed_mm, 0)} mm over ${f.cells} land cells,
        ${day(r.provenance.start)}&ndash;${day(r.provenance.end)} &middot; <code>${escapeHtml(r.provenance.source)}</code></div>
    </div>`);
  }

  const fl = o.flood;
  if(fl && fl.error) parts.push(checkError('Flooding against Sentinel-1', fl.error));
  else if(fl && fl.contingency_at_p50){
    const c = fl.contingency_at_p50, w = fl.where || {};
    const verdict = fl.observed_flooded_cells === 0
      ? ['mixed', 'Sentinel-1 saw no new flooding in this area, so there was nothing to detect.']
      : c.hits === 0
        ? ['bad', `Missed: none of the ${fl.observed_flooded_cells} cells Sentinel-1 saw flooded were predicted.`]
        : [skillClass(c), `Caught ${c.hits} of ${fl.observed_flooded_cells} flooded cells, with ${plural(c.false_alarms, 'false alarm')}.`];
    /** @param {Place | undefined} x */
    const place = x => x ? `${num(x.median_km_from_coast, 0)} km inland, ${num(x.median_elevation_m, 0)} m up` : 'none';
    parts.push(`<div class="vrow">
      <div class="vrow-top"><b>Flooding against Sentinel-1</b></div>
      <div class="vverdict ${verdict[0]}">${verdict[1]}</div>
      <div class="vstat"><span>Flooded cells, observed / predicted</span><b>${fl.observed_flooded_cells} / ${fl.predicted_flooded_cells}</b></div>
      <div class="vstat"><span>Detected (POD) &middot; false alarms (FAR)</span><b>${num(c.pod)} &middot; ${num(c.far)}</b></div>
      <div class="vstat"><span>Brier skill vs climatology</span><b>${num(fl.brier_skill_vs_climatology)}</b></div>
      ${w.observed_flooded ? `<div class="vstat"><span>Observed flooding, typical cell</span><b>${place(w.observed_flooded)}</b></div>
      <div class="vstat"><span>Predicted flooding, typical cell</span><b>${place(w.predicted_flooded)}</b></div>` : ''}
      <div class="vmeta">Radar pair ${day(fl.provenance.before)} &rarr; ${day(fl.provenance.after)}, orbit ${fl.provenance.relative_orbit},
        ${num(fl.provenance.after_minus_landfall_days, 1)} days after landfall &middot; ${escapeHtml(fl.rule)}</div>
    </div>`);
  }

  const ou = o.outage;
  if(ou && ou.error) parts.push(checkError('Outages against VIIRS night lights', ou.error));
  else if(ou && ou.contingency){
    const c = ou.contingency;
    const verdict = ou.observed_outages === 0
      ? (c.false_alarms
          ? ['bad', `No lit substation lost half its light, so ${c.false_alarms === 1 ? 'the one predicted outage was a false alarm' : `all ${c.false_alarms} predicted outages were false alarms`}.`]
          : ['mixed', 'No lit substation lost half its light, and none was predicted to: nothing to detect.'])
      : [skillClass(c), `Caught ${c.hits} of ${plural(ou.observed_outages, 'observed outage')}, with ${plural(c.false_alarms, 'false alarm')}.`];
    parts.push(`<div class="vrow">
      <div class="vrow-top"><b>Outages against VIIRS night lights</b></div>
      <div class="vverdict ${verdict[0]}">${verdict[1]}</div>
      <div class="vstat"><span>Lit substations with a clear night after</span><b>${ou.substations_with_lights}</b></div>
      <div class="vstat"><span>Outages, observed / predicted</span><b>${ou.observed_outages} / ${c.hits + c.false_alarms}</b></div>
      <div class="vstat"><span>Rank correlation, risk vs light lost</span><b>${num(ou.rank_correlation)}</b></div>
      <div class="vstat"><span>Light lost, riskiest quarter / the rest</span><b>${num(ou.mean_drop_top_quarter_predicted)} / ${num(ou.mean_drop_rest)}</b></div>
      <div class="vmeta">${escapeHtml(ou.rule)}</div>
    </div>`);
  } else if(ou && ou.note) parts.push(`<div class="vrow"><div class="vrow-top"><b>Outages against VIIRS night lights</b></div><div class="vwhy">${escapeHtml(ou.note)}</div></div>`);

  return parts.join('');
}
/** @param {number} n @param {string} word */
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
/* Detection is only good if the alarms were mostly real too. */
/** @param {Contingency} c */
function skillClass(c){
  if(c.pod == null || c.pod < 0.2 || (c.far != null && c.far > 0.8)) return 'bad';
  return c.pod >= 0.5 && (c.far == null || c.far <= 0.5) ? 'ok' : 'mixed';
}
/** @param {number | null} r */
function placePhrase(r){
  if(r == null) return 'could not be compared on where rain fell';
  if(r >= 0.6) return 'also placed the rain well';
  if(r >= 0.3) return 'placed the rain only loosely';
  if(r > 0) return 'barely placed the rain';
  return 'put the rain in the wrong places';
}
/** @param {{bias_ratio: number | null, correlation: number | null}} f */
function rainClass(f){
  const totalOk = f.bias_ratio != null && f.bias_ratio >= 0.8 && f.bias_ratio <= 1.25;
  if(f.correlation == null || f.correlation <= 0) return 'bad';
  return totalOk && f.correlation >= 0.6 ? 'ok' : 'mixed';
}
/** @param {number | null} bias */
function amountPhrase(bias){
  if(bias == null) return 'could not be compared on total rain';
  if(bias > 1.25) return `over-forecast the total rain (bias ${num(bias)})`;
  if(bias < 0.8) return `under-forecast the total rain (bias ${num(bias)})`;
  return `got the total rain about right (bias ${num(bias)})`;
}
/** @param {string} title @param {string} err */
function checkError(title, err){
  return `<div class="vrow"><div class="vrow-top"><span class="vstate pending">failed</span><b>${title}</b></div>
    <div class="vwhy">${escapeHtml(err)}</div></div>`;
}

/** @param {string} storm @param {number} lead */
async function loadRun(storm, lead){
  // On failure the current run stays on screen, rather than a blank console.
  try { RUN = checkRun(await getJson(`${API}/api/run/${encodeURIComponent(storm)}/${Number(lead)}`)); }
  catch(err){ notify(`Could not load ${storm} at T-${lead}h: ${errorText(err)}`); return; }
  history.replaceState(null, '', `?storm=${storm}&lead=${lead}${location.hash}`);
  if(map){ try { map.remove(); } catch(e) {} map = null; }
  byId('map').innerHTML = '';
  guard('sidebar', renderSidebar);
  guard('assets', renderAssets);
  guard('advisories', renderAdvisories);
  guard('verify', renderVerify);
  guard('triggers', renderTriggers);
  renderNetwork().catch(e => console.warn('[console] network report', e));
  showMap();
}

/* Parametric triggers. Before landfall: how likely each payout tier is,
   across the ensemble. After: whether the index fired, and whether that
   matched the damage -- basis risk, in both directions. */
/** @type {{[basis: string]: string[]}} */
const BASIS = {
  'aligned': ['ok', 'Payout and loss agree'],
  'loss without payout': ['bad', 'Loss without payout'],
  'payout without modelled loss': ['warn', 'Payout without modelled loss'],
};
function renderTriggers(){
  const t = run().summary.triggers;
  const el = byId('view-triggers');
  if(!t || !t.zones.length){
    el.innerHTML = '<div class="empty">No policy zones are defined for this region.</div>';
    return;
  }
  /** @param {number} p */
  const bar = p => `<span class="pbar"><span style="width:${Math.round(p*100)}%"></span></span>`;
  el.innerHTML = `<div class="trg-note">${escapeHtml(t.note)}</div>` + t.zones.map(z => {
    const [cls, label] = BASIS[z.basis_risk] || ['', z.basis_risk];
    return `<div class="trg">
      <div class="trg-h"><b>${escapeHtml(z.zone)}</b><span class="basis ${escapeHtml(cls)}">${escapeHtml(label)}</span></div>
      ${z.perils.map(p => `<div class="trg-row">
        <span class="trg-peril">${escapeHtml(p.peril)}</span>
        ${bar(p.p_partial_or_more)}
        <span class="trg-p">${Math.round(p.p_partial_or_more*100)}%</span>
        <span class="trg-obs">observed ${escapeHtml(p.observed_index)} ${escapeHtml(p.unit)}${
          p.observed_payout ? ` &rarr; <b>${Math.round(p.observed_payout*100)}% paid</b>` : ' &rarr; no payout'}</span>
      </div>`).join('')}
      <div class="trg-meta">Tiers: wind ${z.perils[0].tiers.map(x=>Number(x.threshold)).join(' / ')} km/h &middot;
        rain ${z.perils[1].tiers.map(x=>Number(x.threshold)).join(' / ')} mm &middot; ${Number(z.red_assets)} red assets in zone</div>
    </div>`;
  }).join('') + `<div class="trg-note">Material loss means ${escapeHtml(t.material_loss_rule)}.
    Probability bars show the chance of at least a partial payout, across the forecast ensemble.</div>`;
}

/* The simulated network's QC report: which injected faults were caught and
   how many clean readings were wrongly flagged -- both, because a gate that
   catches every fault by flagging everything is useless. */
async function renderNetwork(){
  const el = document.getElementById('net-sec'); if(!el) return;
  const storm = run().summary.storm;
  /** @type {NetworkReport} */
  let n;
  try {
    n = /** @type {NetworkReport} */ (await getJson(`${API}/api/telemetry/report/${encodeURIComponent(storm.toLowerCase())}`));
  } catch(err) {
    // Said in the panel: an empty section reads as "no network", which is
    // not the same as "the report could not be read".
    el.innerHTML = '<h4>Sensor network (simulated)</h4>'
      + `<div class="vwhy" role="status">No network report for this storm: ${escapeHtml(errorText(err))}</div>`;
    return;
  }
  const tiers = Object.entries(n.nodes).map(([t,c]) => `${Number(c)} tier ${t}`).join(' · ');
  const faults = Object.keys(n.faults_injected).map(f =>
    `<div class="vstat"><span>${escapeHtml(f)} fault readings caught</span>`
    + `<b>${Number(n.faults_caught[f])} / ${Number(n.faults_injected[f])}</b></div>`).join('');
  const fall = n.strongest_3h_fall_at_landfall;
  el.innerHTML = `<h4>Sensor network (simulated)</h4>
    <div class="vmeta">${escapeHtml(tiers)}</div>
    ${faults}
    <div class="vstat"><span>Clean readings wrongly flagged</span><b>${Number(n.clean_flagged)} / ${Number(n.clean_readings).toLocaleString()} (${num(n.false_flag_rate*100, 2)}%)</b></div>
    ${fall ? `<div class="vstat"><span>Strongest 3 h pressure fall at landfall</span><b>${num(fall.hpa, 2)} hPa</b></div>` : ''}
    <div class="vwhy">${escapeHtml(n.note)}</div>`;
}

/* Writes may need an operator access code (api/access.py). When the server
   asks for one, the dialog shows a field for it; an accepted code is kept for
   this browser tab only. */
function storedCode(){
  try { return sessionStorage.getItem('bob-access'); } catch(e) { return null; }
}
/** @param {string | null} code */
function storeCode(code){
  try {
    if(code) sessionStorage.setItem('bob-access', code);
    else sessionStorage.removeItem('bob-access');
  } catch(e) { /* storage blocked: the code is simply asked for again */ }
}

/** @param {string} url @param {object} body @param {string} [code] @returns {Promise<WriteResult>} */
async function write(url, body, code){
  // The officer's Google sign-in where the server uses sign-in
  // (web/auth-loader.mjs hands it over), else the access code.
  const key = window.bobAuth ? await window.bobAuth.token() : (code || storedCode());
  const r = await fetch(url, {method: 'POST',
    headers: {'Content-Type': 'application/json', ...(key ? {'Authorization': 'Bearer ' + key} : {})},
    body: JSON.stringify(body || {})});
  let data = null;
  try { data = await r.json(); } catch(e) { /* not JSON */ }
  if(r.ok && code) storeCode(code);
  if(r.status === 401) storeCode(null);
  const signIn = !!window.bobAuth;
  return {ok: r.ok, status: r.status, data, needsCode: r.status === 401 && !signIn,
          needsSignIn: r.status === 401 && signIn,
          detail: describe(r.status, data)};
}

/** @param {string} id */
const advisory = id => run().advisories.find(x => x.identifier === id);

/* Approve or revoke: the network half, separate from the dialog so it can be
   tested without a browser. Returns what happened; updates the run on success. */
/** @param {string} mode @param {string} id
    @param {{operator?: string, note?: string, code?: string}} [fields] */
async function submitAction(mode, id, {operator = '', note = '', code = ''} = {}){
  let res;
  try { res = await write(`${API}/api/advisory/${encodeURIComponent(id)}/${mode}`,
                          {operator, note}, code); }
  catch(err){ return {ok: false, detail: 'Could not reach the server. Nothing was recorded.'}; }
  // A 409 on withdrawal means there was no approval to withdraw -- another
  // officer got there first -- so the page catches up with the record.
  const a = advisory(id);
  if(a && (res.ok || (mode === 'revoke' && res.status === 409))){
    a.approved = res.ok && mode === 'approve';
    a.approved_by = a.approved ? /** @type {{operator: string}} */ (res.data).operator : null;
    renderAdvisories();
  }
  return res;
}

/** @param {string} id @param {string} [code] @returns {Promise<WriteResult>} */
async function dispatchAction(id, code = ''){
  const s = run().summary;
  let res;
  try { res = await write(`${API}/api/advisory/${encodeURIComponent(s.storm.toLowerCase())}/`
                          + `${Math.trunc(Number(s.hours_to_landfall))}/${encodeURIComponent(id)}/dispatch`, {}, code); }
  catch(err){ return {ok: false, detail: 'Could not reach the server. Nothing was dispatched.'}; }
  const j = /** @type {DispatchReceipt} */ (res.data);
  res.message = res.ok
    ? `Dispatch gate passed. Would send to ${j.would_send_to} via ${j.channels.join(', ')}, `
      + `approved by ${j.approved_by}, CAP status ${j.cap_status}. ${j.reason}`
    : `Blocked: ${res.detail}`;
  return res;
}

/* The dialog: one form for approving, revoking and supplying a code. */
/** @typedef {'approve' | 'revoke' | 'code'} DialogMode */
/** @type {{mode: DialogMode, id: string} | null} */
let pending = null;
/** @param {DialogMode} mode @param {string} id */
function openDialog(mode, id){
  const a = advisory(id);
  pending = {mode, id};
  const dlg = /** @type {HTMLDialogElement} */ (byId('act-dialog'));
  byId('act-title').textContent =
    mode === 'approve' ? 'Approve advisory' : mode === 'revoke' ? 'Withdraw approval' : 'Access code needed';
  byId('act-what').textContent = a ? `${a.recipient}: ${a.headline}` : '';
  if(a && mode !== 'code'){
    // An approval covers every language the advisory carries; say which.
    const l = a.languages;
    const langs = l.length > 1 ? `${l.slice(0, -1).join(', ')} and ${l[l.length - 1]}` : l[0];
    byId('act-what').textContent += `. This covers the text in ${langs}, as shown in the card.`;
  }
  // Signed in, the account is who acts: no name to type, and it says whose.
  const who = window.bobAuth ? window.bobAuth.user() : null;
  if(who && mode !== 'code') byId('act-what').textContent += ` Recorded as ${who.email}.`;
  byId('act-names').hidden = mode === 'code';
  byId('act-who').hidden = !!who;
  /** @type {HTMLInputElement} */ (byId('act-operator')).required = mode !== 'code' && !who;
  byId('act-code-row').hidden = mode !== 'code';
  byId('act-error').textContent = '';
  byId('act-submit').textContent =
    mode === 'approve' ? 'Approve' : mode === 'revoke' ? 'Withdraw' : 'Continue';
  dlg.showModal();
}

/** A named input of the dialog's form.
    @param {HTMLFormElement} form @param {string} name @returns {HTMLInputElement} */
function field(form, name){
  const el = /** @type {HTMLInputElement | null} */ (form.elements.namedItem(name));
  if(!el || typeof el.value !== 'string') throw new Error(`the dialog has no ${name} field`);
  return el;
}

/** @param {SubmitEvent} e */
async function onDialogSubmit(e){
  e.preventDefault();
  if(!pending) return;
  const form = /** @type {HTMLFormElement} */ (e.target);
  const who = window.bobAuth ? window.bobAuth.user() : null;
  const fields = {operator: who ? who.email : field(form, 'operator').value.trim(),
                  note: field(form, 'note').value.trim(), code: field(form, 'code').value};
  const {mode, id} = pending;
  // Recording can take seconds (the audit trail may be BigQuery): say so,
  // and let the button be pressed once.
  const button = /** @type {HTMLButtonElement} */ (byId('act-submit'));
  const label = button.textContent;
  button.disabled = true;
  button.textContent = mode === 'code' ? 'Sending…' : 'Recording…';
  let res;
  try {
    res = mode === 'code' ? await dispatchAction(id, fields.code)
                          : await submitAction(mode, id, fields);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
  if(res.needsSignIn){
    byId('act-error').textContent = `${res.detail} Sign in again from the banner at the top.`;
    return;
  }
  if(res.needsCode){
    byId('act-code-row').hidden = false;
    byId('act-error').textContent =
      fields.code ? 'That access code was not accepted.' : 'This action needs the operator access code.';
    field(form, 'code').focus();
    return;
  }
  if(!res.ok && mode !== 'code'){
    byId('act-error').textContent = res.detail;
    return;
  }
  /** @type {HTMLDialogElement} */ (byId('act-dialog')).close();
  form.reset();
  if(mode === 'code') showResult(id, res.message || '');
  pending = null;
  focusNext(mode, id);
}

/** The card was redrawn while the dialog was open, so the control that
    opened it -- where focus would return -- is gone. Focus its successor:
    Dispatch after an approval, Approve after a withdrawal.
    @param {DialogMode} mode @param {string} id */
function focusNext(mode, id){
  const next = mode === 'revoke' ? 'approve' : 'dispatch';
  const quoted = id.replace(/["\\]/g, '\\$&');
  const el = /** @type {HTMLElement | null} */ (
    document.querySelector(`[data-action="${next}"][data-id="${quoted}"]`));
  if(el) el.focus();
}

/** @param {string} id @param {string} text */
function showResult(id, text){
  const el = document.getElementById('res-' + id);
  if(el){ el.textContent = text; el.hidden = false; }
}

/** @param {string} id */
function approve(id){ asOfficer(() => openDialog('approve', id)); }
/** @param {string} id */
function revoke(id){ asOfficer(() => openDialog('revoke', id)); }

/** Where the server uses sign-in, sign in first if no one is. The popup
    opens from the click itself -- browsers block popups opened later -- so
    nothing is awaited before it. @param {() => void} then */
function asOfficer(then){
  const auth = window.bobAuth;
  if(!auth || auth.user()){ then(); return; }
  auth.signIn().then(o => { if(o) then(); },
                     err => notify(`Sign-in did not complete: ${errorText(err)}`));
}

/** Who is signed in, in the banner, with the way in or out.
    @param {Officer | null} o */
function renderAuth(o){
  const el = byId('auth-state');
  el.hidden = false;
  el.innerHTML = o
    ? `Signed in as <b>${escapeHtml(o.email)}</b> <button class="ghost" data-action="sign-out">Sign out</button>`
    : '<button class="ghost" data-action="sign-in">Sign in with Google</button>';
}
/** Start following the sign-in, once web/auth-loader.mjs has handed it over. */
function followAuth(){ if(window.bobAuth) window.bobAuth.onChange(renderAuth); }
if(window.bobAuth) followAuth(); else window.addEventListener('auth-ready', followAuth);

/** @param {string} id */
async function dispatch(id){
  // Sign in first, from the click itself, when sign-in is in use.
  if(window.bobAuth && !window.bobAuth.user()){ asOfficer(() => { void dispatch(id); }); return; }
  const res = await dispatchAction(id);
  if(res.needsCode){ openDialog('code', id); return; }
  showResult(id, res.message || '');
}

/** @param {string} id */
function toggleCap(id){
  const pre = byId('cap-'+id);
  const a = advisory(id);
  pre.textContent = a ? a.cap_xml : '';
  pre.hidden = !pre.hidden;
}

/* Tabs are addressable, so a link can point at the panel it is about --
   "look at the Checks tab" works as a URL rather than an instruction. */
/** @param {string} name @returns {boolean} whether there was such a tab */
function selectTab(name){
  const tab = document.querySelector(`.tab[data-view="${name}"]`);
  if(!tab) return false;
  document.querySelectorAll('.tab').forEach(x=>{
    x.classList.remove('on'); x.setAttribute('aria-selected','false');
    x.setAttribute('tabindex','-1');
  });
  document.querySelectorAll('.view').forEach(x=>x.classList.remove('on'));
  tab.classList.add('on'); tab.setAttribute('aria-selected','true');
  tab.setAttribute('tabindex','0');
  byId('view-'+name).classList.add('on');
  // The ranking note explains the asset table and is meaningless above the
  // other panels.
  byId('rank-note').hidden = (name !== 'assets');
  return true;
}

/* The WAI-ARIA tabs pattern: one tab in the Tab order, arrows move between
   them, Home and End jump to the ends. */
/** @type {NodeListOf<HTMLElement>} */ (document.querySelectorAll('.tab')).forEach((t, i, all)=>{
  t.onkeydown = e => {
    const to = {ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1}[e.key];
    if(to !== undefined){
      e.preventDefault();
      const next = all[(to + all.length) % all.length];
      next.focus(); next.click();
    } else if(e.key==='Enter'||e.key===' '){ e.preventDefault(); t.click(); }
  };
  t.onclick = ()=>{
    const view = t.dataset.view || '';
    selectTab(view);
    history.replaceState(null, '', '#' + view);
  };
});

window.addEventListener('hashchange', ()=> selectTab(location.hash.slice(1)));

/* One listener for every button the panels draw. Handlers are named by
   data-action rather than written inline, so the page's content policy can
   forbid inline script. */
/** @type {{[action: string]: (el: HTMLElement) => void}} */
const ACTIONS = {
  reload: () => location.reload(),
  load: el => loadRun(el.dataset.storm || '', Number(el.dataset.lead)),
  approve: el => approve(el.dataset.id || ''),
  revoke: el => revoke(el.dataset.id || ''),
  'dialog-cancel': () => {
    /** @type {HTMLDialogElement} */ (byId('act-dialog')).close();
    pending = null;
  },
  cap: el => toggleCap(el.dataset.id || ''),
  dispatch: el => dispatch(el.dataset.id || ''),
  'sign-in': () => asOfficer(() => {}),
  'sign-out': () => { if(window.bobAuth) void window.bobAuth.signOut(); },
  asset: el => showAsset(shownAssets[Number(el.dataset.rank)]),
  'close-detail': () => { mapDetail().hidden = true; },
};
/** Run the action of the nearest element matching `selector`, if any.
    @param {Event} e @param {string} selector */
function actOn(e, selector){
  const target = /** @type {Element} */ (e.target);
  const el = /** @type {HTMLElement | null} */ (target.closest && target.closest(selector));
  const act = el && ACTIONS[el.dataset.action || ''];
  if(el && act){ e.preventDefault(); act(el); }
}
document.addEventListener('click', e => actOn(e, '[data-action]'));
// Rows that act as buttons answer Enter and Space as buttons do.
document.addEventListener('keydown', e => {
  if(e.key === 'Enter' || e.key === ' ') actOn(e, '[role="button"][data-action]');
});

/* Another officer may approve or withdraw while this page sits in a
   background tab. Coming back to it re-reads the approval state, so a stale
   "Approved" is not what the officer acts on. Only approval fields change;
   the map and panels are left as they are. */
let lastApprovalRefresh = 0;
async function refreshApprovals(){
  if(!RUN || Date.now() - lastApprovalRefresh < 5000) return;
  lastApprovalRefresh = Date.now();
  const shown = run(), s = shown.summary;
  let fresh;
  try {
    fresh = checkRun(await getJson(
      `${API}/api/run/${encodeURIComponent(s.storm.toLowerCase())}/${Math.trunc(Number(s.hours_to_landfall))}`));
  } catch(err) {
    // Keep what is on screen: the next action reports it if the server is gone.
    console.warn('[console] approval refresh failed', err);
    return;
  }
  if(RUN !== shown) return;          // the officer switched storms meanwhile
  const by = new Map(fresh.advisories.map(a => [a.identifier, a]));
  for(const a of shown.advisories){
    const f = by.get(a.identifier);
    if(f){ a.approved = f.approved; a.approved_by = f.approved_by; }
  }
  shown.approvals_unavailable = fresh.approvals_unavailable;
  guard('advisories', renderAdvisories);
}
document.addEventListener('visibilitychange', () => {
  if(document.visibilityState === 'visible') refreshApprovals();
});
window.addEventListener('focus', () => { refreshApprovals(); });

/** @type {ReturnType<typeof setTimeout> | undefined} */
let notifyTimer;
/** @param {string} text */
function notify(text){
  const el = byId('toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(notifyTimer);
  notifyTimer = setTimeout(() => { el.hidden = true; }, 8000);
}

const actForm = document.getElementById('act-form');
if(actForm) actForm.addEventListener('submit', onDialogSubmit);

boot();
