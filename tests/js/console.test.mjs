// Unit tests for the operator console's rendering, run under Node with a
// minimal page stub -- no browser, no network. Run: node tests/js/console.test.mjs
//
// What matters most here is that text the server stores on behalf of a
// visitor (an approving officer's name) or pulls from OpenStreetMap (asset
// names) is escaped before it becomes HTML.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const APP = fileURLToPath(new URL('../../web/app.js', import.meta.url));
// Compiled once, with its real path, so coverage tools attribute lines to it.
const script = new vm.Script(readFileSync(APP, 'utf8'), { filename: APP });

const context2d = () => new Proxy({}, {
  get: (target, key) => (key in target ? target[key]
    : key === 'createImageData' ? (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) })
    : () => {}),
  set: (target, key, value) => { target[key] = value; return true; },
});

function element(size = 0) {
  const listeners = {};
  return { innerHTML: '', textContent: '', hidden: false, style: {}, dataset: {}, checked: false,
           getBoundingClientRect: () => ({ width: size, height: size, left: 0, top: 0 }),
           getContext: () => context2d(), toDataURL: () => 'data:image/png;base64,', focus() {},
           showModal() {}, close() {}, width: 0, height: 0, listeners,
           classList: { add() {}, remove() {}, toggle() {} },
           setAttribute() {}, querySelectorAll: () => [], appendChild() {},
           addEventListener(type, fn) { (listeners[type] ??= []).push(fn); } };
}

/* MapLibre, as far as the console uses it: records what is asked of it and
   lets a test fire the events a real map would. */
function fakeMapLibre() {
  const made = [];
  class Map {
    constructor(options) {
      this.options = options; this.handlers = {}; this.sources = {}; this.layers = {};
      this.flights = []; this.removed = false; made.push(this);
    }
    addControl() {}
    on(type, layerOrFn, fn) { this.handlers[fn ? `${type}:${layerOrFn}` : type] = fn || layerOrFn; }
    fire(key, event) { this.handlers[key](event); }
    addSource(id, source) { this.sources[id] = source; }
    addLayer(layer) { this.layers[layer.id] = JSON.parse(JSON.stringify(layer)); }
    getLayer(id) { return this.layers[id]; }
    setLayoutProperty(id, name, value) { this.layers[id].layout[name] = value; }
    flyTo(options) { this.flights.push(options); }
    remove() { this.removed = true; }
    getCanvas() { return { style: {} }; }
  }
  const popups = [];
  class Popup {
    setLngLat(at) { this.at = at; return this; }
    setHTML(html) { this.html = html; popups.push(this); return this; }
    addTo() { return this; }
  }
  class NavigationControl {}
  return { Map, Popup, NavigationControl, made, popups };
}

function page({ fetch: fetchStub, prompts = [], size = 0 } = {}) {
  const elements = {};
  const alerts = [];
  const listeners = {};
  const windowListeners = {};
  const storage = {};
  const context = {
    console: { log() {}, warn() {}, error() {} },
    document: {
      getElementById: id => (elements[id] ??= element(size)),
      createElement: () => element(size),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: (type, fn) => { (listeners[type] ??= []).push(fn); },
      body: element(),
    },
    window: {
      addEventListener: (type, fn) => { (windowListeners[type] ??= new Set()).add(fn); },
      removeEventListener: (type, fn) => { windowListeners[type]?.delete(fn); },
    },
    location: { search: '', hash: '', protocol: 'http:' },
    history: { replaceState() {} },
    URLSearchParams,
    alert: msg => alerts.push(String(msg)),
    prompt: () => (prompts.length ? prompts.shift() : null),
    sessionStorage: { getItem: k => storage[k] ?? null, setItem: (k, v) => { storage[k] = v; },
                      removeItem: k => { delete storage[k]; } },
    // By default nothing resolves: boot() waits instead of rendering stub data.
    fetch: fetchStub || (() => new Promise(() => {})),
    setTimeout, clearTimeout,
  };
  vm.createContext(context);
  script.runInContext(context);
  // Simulate a click on an element carrying data-* attributes.
  const click = dataset => {
    const target = { dataset, closest: () => target };
    (listeners.click || []).forEach(fn => fn({ target, preventDefault() {} }));
  };
  // A key press on a role="button" element carrying data-* attributes.
  const key = (name, dataset) => {
    const target = { dataset, closest: sel => (sel.includes('role="button"') ? target : null) };
    (listeners.keydown || []).forEach(fn => fn({ key: name, target, preventDefault() {} }));
  };
  return { context, elements, alerts, storage, click, key, windowListeners,
           run: code => vm.runInContext(code, context) };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const HOSTILE = '<img src=x onerror="alert(1)">';

function advisory(extra = {}) {
  return {
    identifier: 'T5-TEST-1', recipient: 'Health Department', lead_hours: [48, 24],
    severity: 'red', headline: 'h', instruction: 'i', ensemble_note: 'n',
    languages: ['en-IN'], pending_languages: ['te-IN'], drafted_by: 'template',
    draft_notes: [], approved: false, approved_by: null, cap_xml: '<alert/>', ...extra,
  };
}

test('an approving officer name is escaped, not rendered as markup', () => {
  const p = page();
  p.context.__adv = advisory({ approved: true, approved_by: HOSTILE });
  p.run('RUN = { advisories: [__adv], summary: {} }; renderAdvisories();');
  const out = p.elements['view-advisories'].innerHTML;
  assert.ok(!out.includes('<img'), 'raw <img> reached the page');
  assert.ok(out.includes('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'));
});

test('every server string in an advisory card is escaped', () => {
  const p = page();
  p.context.__adv = advisory({ recipient: HOSTILE, headline: HOSTILE, instruction: HOSTILE,
                               ensemble_note: HOSTILE, drafted_by: HOSTILE,
                               languages: [HOSTILE], pending_languages: [HOSTILE],
                               draft_notes: [HOSTILE] });
  p.run('RUN = { advisories: [__adv], summary: {} }; renderAdvisories();');
  assert.ok(!p.elements['view-advisories'].innerHTML.includes('<img'));
});

test('every translation an approval covers is shown in full, escaped, in its language', () => {
  // Found in review: the card showed only the English, so an officer approved
  // Telugu text they could not see anywhere but the raw XML.
  const p = page();
  p.context.__adv = advisory({ languages: ['en-IN', 'te-IN'], pending_languages: [],
    translations: { 'te-IN': { headline: 'మోంథా: 48 గంటలు', instruction: HOSTILE, description: 'వివరణ' },
                    'or-IN': { headline: 'not requested, so not in the CAP either' } } });
  p.run('RUN = { advisories: [__adv], summary: {} }; renderAdvisories();');
  const html = p.elements['view-advisories'].innerHTML;
  assert.ok(html.includes('<div lang="te-IN">'), 'marked, so it is read in its own voice');
  assert.ok(html.includes('మోంథా: 48 గంటలు') && html.includes('వివరణ'));
  assert.ok(!html.includes('<img'), 'escaped');
  assert.ok(!html.includes('not requested'), 'only the languages the advisory carries');
});

test('the approval dialog says which languages an approval covers', () => {
  const { p } = dialogPage(() => response(200, {}));
  p.context.__adv2 = advisory({ identifier: 'T5-TEST-2', languages: ['en-IN', 'te-IN'],
                                translations: { 'te-IN': { headline: 'మోంథా' } } });
  p.run('RUN.advisories.push(__adv2);');
  p.click({ action: 'approve', id: 'T5-TEST-2' });
  assert.match(p.elements['act-what'].textContent, /covers the text in en-IN and te-IN/);
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  assert.match(p.elements['act-what'].textContent, /covers the text in en-IN\b/);
});

test('escapeHtml covers the five HTML metacharacters', () => {
  const p = page();
  assert.equal(p.run(`escapeHtml('<a href="x">&\\'</a>')`),
               '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
});

test('a rain verdict is graded on both total and placement', () => {
  const p = page();
  assert.equal(p.run('rainClass({bias_ratio: 1.0, correlation: 0.7})'), 'ok');
  assert.equal(p.run('rainClass({bias_ratio: 0.82, correlation: 0.32})'), 'mixed');
  assert.equal(p.run('rainClass({bias_ratio: 1.0, correlation: -0.1})'), 'bad');
  assert.equal(p.run('placePhrase(0.32)'), 'placed the rain only loosely');
});

test('high detection with mostly false alarms is still graded bad', () => {
  const p = page();
  assert.equal(p.run('skillClass({pod: 0.9, far: 0.95})'), 'bad');
  assert.equal(p.run('skillClass({pod: 0.6, far: 0.3})'), 'ok');
  assert.equal(p.run('skillClass({pod: null, far: null})'), 'bad');
});

test('run timestamps without an offset are read as UTC', () => {
  const p = page();
  assert.equal(p.run("day('2025-11-01T00:00:00')"), '1 Nov');
  assert.equal(p.run("day('2025-11-01T00:00:00+00:00')"), '1 Nov');
});

test('satellite checks that failed show their error, escaped', () => {
  const p = page();
  const out = p.run(`observedChecks({available: true, rain: {error: ${JSON.stringify(HOSTILE)}}})`);
  assert.ok(out.includes('failed'));
  assert.ok(!out.includes('<img'));
});


const response = (status, body) => Promise.resolve({
  ok: status >= 200 && status < 300, status,
  json: () => (body === undefined ? Promise.reject(new Error('not json')) : Promise.resolve(body)),
});

test('an approval refused for want of a code asks for one, then succeeds with it', async () => {
  const calls = [];
  const p = page({
    fetch: (url, opts = {}) => {
      if (!String(url).includes('/approve')) return new Promise(() => {});
      calls.push(opts.headers || {});
      return (opts.headers || {}).Authorization === 'Bearer code-123'
        ? response(200, { operator: 'K. Ramesh' })
        : response(401, { detail: 'A valid access code is required for this action' });
    },
  });
  p.context.__adv = advisory();
  p.run('RUN = { advisories: [__adv], summary: {} };');
  const first = await p.run("submitAction('approve', 'T5-TEST-1', {operator: 'K. Ramesh'})");
  assert.equal(first.needsCode, true);
  assert.equal(calls[0].Authorization, undefined);
  const second = await p.run("submitAction('approve', 'T5-TEST-1', {operator: 'K. Ramesh', code: 'code-123'})");
  assert.equal(second.ok, true);
  assert.equal(p.storage['bob-access'], 'code-123', 'an accepted code is kept for the tab');
  assert.ok(p.elements['view-advisories'].innerHTML.includes('Approved by K. Ramesh'));
  assert.ok(p.elements['view-advisories'].innerHTML.includes('data-action="revoke"'));
});

test('a rejected code is forgotten, not reused', async () => {
  const p = page({ fetch: () => response(401, { detail: 'A valid access code is required' }) });
  p.storage['bob-access'] = 'stale';
  p.context.__adv = advisory();
  p.run('RUN = { advisories: [__adv], summary: {} };');
  await p.run("submitAction('approve', 'T5-TEST-1', {operator: 'K. Ramesh'})");
  assert.equal(p.storage['bob-access'], undefined);
});

test('a server error on approval is reported with its reason, and nothing changes', async () => {
  const p = page({
    fetch: url => (String(url).includes('/approve')
      ? response(400, { detail: 'Name the accountable operator in full, not an initial' })
      : new Promise(() => {})),
  });
  p.context.__adv = advisory();
  p.run('RUN = { advisories: [__adv], summary: {} };');
  const res = await p.run("submitAction('approve', 'T5-TEST-1', {operator: 'K'})");
  assert.equal(res.ok, false);
  assert.match(res.detail, /in full, not an initial/);
  assert.equal(p.run('RUN.advisories[0].approved'), false);
});

test('withdrawing an approval puts the Approve button back', async () => {
  const p = page({ fetch: () => response(200, { approved: false, operator: 'S. Das' }) });
  p.context.__adv = advisory({ approved: true, approved_by: 'K. Ramesh' });
  p.run('RUN = { advisories: [__adv], summary: {} };');
  const res = await p.run("submitAction('revoke', 'T5-TEST-1', {operator: 'S. Das'})");
  assert.equal(res.ok, true);
  assert.equal(p.run('RUN.advisories[0].approved'), false);
  assert.ok(p.elements['view-advisories'].innerHTML.includes('data-action="approve"'));
});

test('withdrawing an approval someone else already withdrew brings the page up to date', async () => {
  const p = page({ fetch: () => response(409, { detail: 'No standing approval to withdraw; it may already have been' }) });
  p.context.__adv = advisory({ approved: true, approved_by: 'K. Ramesh' });
  p.run('RUN = { advisories: [__adv], summary: {} };');
  const res = await p.run("submitAction('revoke', 'T5-TEST-1', {operator: 'S. Das'})");
  assert.equal(res.ok, false);
  assert.match(res.detail, /already/);
  assert.equal(p.run('RUN.advisories[0].approved'), false);
  assert.ok(p.elements['view-advisories'].innerHTML.includes('data-action="approve"'));
});

test('a refused approval leaves the page as it was', async () => {
  const p = page({ fetch: () => response(409, { detail: 'conflict' }) });
  p.context.__adv = advisory({ approved: false });
  p.run('RUN = { advisories: [__adv], summary: {} };');
  const res = await p.run("submitAction('approve', 'T5-TEST-1', {operator: 'S. Das'})");
  assert.equal(res.ok, false);
  assert.equal(p.run('RUN.advisories[0].approved'), false);
});

test('an unreachable server during dispatch is a message, not an unhandled rejection', async () => {
  const p = page({
    fetch: url => (String(url).includes('/dispatch')
      ? Promise.reject(new TypeError('Failed to fetch')) : new Promise(() => {})),
  });
  p.context.__adv = advisory();
  p.run("RUN = { advisories: [__adv], summary: { storm: 'MONTHA', hours_to_landfall: 48 } };");
  const res = await p.run("dispatchAction('T5-TEST-1')");
  assert.equal(res.ok, false);
  assert.match(res.detail, /Could not reach the server/);
});

test('a dispatch result is shown in the card, as text', async () => {
  const p = page({ fetch: () => response(409, { detail: 'Advisory is not approved. <b>x</b>' }) });
  p.context.__adv = advisory();
  p.run("RUN = { advisories: [__adv], summary: { storm: 'MONTHA', hours_to_landfall: 48 } };");
  await p.run("dispatch('T5-TEST-1')");
  const out = p.elements['res-T5-TEST-1'];
  assert.match(out.textContent, /^Blocked: Advisory is not approved/);
  assert.equal(out.innerHTML, '', 'written as text, never as HTML');
});

test('validation errors from the API read as sentences', () => {
  const p = page();
  assert.equal(p.run("describe(422, {detail: [{msg: 'String should have at most 120 characters'}]})"),
               'String should have at most 120 characters');
  assert.equal(p.run('describe(502, null)'), 'The server answered 502.');
});

test('a console that cannot reach its server says so and offers a retry', async () => {
  const p = page({ fetch: () => Promise.reject(new TypeError('Failed to fetch')) });
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
  const out = p.context.document.body.innerHTML;
  assert.match(out, /could not reach its server/);
  assert.match(out, /Try again/);
});


test('buttons are wired by data-action, not inline handlers', async () => {
  const calls = [];
  const p = page({ fetch: url => { calls.push(String(url)); return new Promise(() => {}); } });
  p.run("RUN = { advisories: [], summary: {} }; RUNS = [{storm: 'fani', lead_hours: 48}];");
  p.click({ action: 'load', storm: 'fani', lead: '48' });
  assert.ok(calls.some(u => u.endsWith('/api/run/fani/48')), calls.join(' '));
});

test('no rendered control carries an inline event handler', () => {
  const p = page();
  p.context.__adv = advisory({ approved: true, approved_by: 'K. Ramesh' });
  p.run('RUN = { advisories: [__adv], summary: {} }; renderAdvisories();');
  assert.doesNotMatch(p.elements['view-advisories'].innerHTML, /\son[a-z]+=/i);
});


test('redrawing the offline map keeps one resize handler, not one per storm', () => {
  const p = page();
  p.run(`RUN = { grid: {lat_min: 15, lat_max: 17, lon_min: 80, lon_max: 82, rows: 2, cols: 2},
                land_mask: [[1, 0], [1, 1]], layers: {}, track: [], assets: [], summary: {} };`);
  p.run('drawOfflineMap(); drawOfflineMap(); drawOfflineMap();');
  assert.equal(p.windowListeners.resize.size, 1);
});


function asset(extra = {}) {
  return { name: 'Govt Hospital Peruru', asset_class: 'hospital', lat: 16.5, lon: 81.5,
           p_failure: 0.54, p_failure_p10: 0.31, p_failure_p90: 0.7, wind_kmh: 77, depth_m: 0.28,
           rain_mm: 150, driver: 'flood', severity: 'red', consequence: 1.35, criticality: 2.5,
           criticality_basis: 'beds', criticality_confidence: 'mapped', ...extra };
}
const assetRun = `RUN = { grid: {lat_min: 15, lat_max: 17, lon_min: 80, lon_max: 82, rows: 2, cols: 2},
  land_mask: [[1, 0], [1, 1]], track: [], assets: [__a], advisories: [],
  layers: {p_gust_90kmh: [[0.9, 0.2], [0.4, 0.8]], rain_mm: [[300, 10], [150, 250]]},
  summary: {assets_scored: 1} };`;

test('every field of an asset row is escaped, the driver included', () => {
  const p = page();
  p.context.__a = asset({ driver: HOSTILE, asset_class: HOSTILE, criticality_basis: HOSTILE });
  p.run(assetRun + ' renderAssets();');
  assert.ok(!p.elements['view-assets'].innerHTML.includes('<img'));
});

test('dispatch goes to the run file the export wrote, whose lead is a whole number', async () => {
  const urls = [];
  const p = page({ fetch: url => { urls.push(String(url)); return response(200, {
    would_send_to: 'x', channels: ['SMS'], approved_by: 'K', cap_status: 'Exercise', reason: '' }); } });
  p.context.__adv = advisory();
  p.run("RUN = { advisories: [__adv], summary: { storm: 'MONTHA', hours_to_landfall: 47.6 } };");
  await p.run("dispatchAction('T5-TEST-1')");
  const sent = urls.find(u => u.includes('/dispatch')) || '';
  assert.ok(sent.endsWith('/api/advisory/montha/47/T5-TEST-1/dispatch'), urls.join(' '));
});

test('an asset row shows its details with no map at all, escaped', () => {
  const p = page();
  p.context.__a = asset({ name: HOSTILE, driver: HOSTILE });
  p.run(assetRun + ' map = null; renderAssets();');
  assert.match(p.elements['view-assets'].innerHTML, /data-action="asset" data-rank="0"/);
  p.click({ action: 'asset', rank: '0' });
  const card = p.elements['map-detail'];
  assert.equal(card.hidden, false);
  assert.ok(!card.innerHTML.includes('<img'), 'raw markup reached the card');
  assert.match(card.innerHTML, /54% failure probability/);
  assert.match(card.innerHTML, /wind 77 km\/h · water 0.28 m · rain 150 mm/);
  p.click({ action: 'close-detail' });
  assert.equal(card.hidden, true);
});

test('Enter and Space on an asset row act as a click; other keys do nothing', () => {
  const p = page();
  p.context.__a = asset();
  p.run(assetRun + ' map = null; renderAssets();');
  p.key('Tab', { action: 'asset', rank: '0' });
  assert.equal(p.elements['map-detail']?.innerHTML ?? '', '');
  p.key('Enter', { action: 'asset', rank: '0' });
  assert.match(p.elements['map-detail'].innerHTML, /Govt Hospital Peruru/);
  p.click({ action: 'close-detail' });
  p.key(' ', { action: 'asset', rank: '0' });
  assert.equal(p.elements['map-detail'].hidden, false);
});

test('on the offline map an asset row rings the asset; on MapLibre it flies there', () => {
  const p = page({ size: 400 });
  p.context.__a = asset();
  p.run(assetRun + ' map = null; renderAssets(); drawOfflineMap();');
  p.click({ action: 'asset', rank: '0' });
  assert.equal(p.run('offlineFocus && offlineFocus.name'), 'Govt Hospital Peruru');
  p.run('drawOfflineMap();');
  assert.equal(p.run('offlineFocus'), null, 'a redraw for a new run clears the ring');

  const flights = [];
  p.context.__fly = opts => flights.push(opts);
  p.run('map = { flyTo: __fly };');
  p.click({ action: 'asset', rank: '0' });
  assert.deepEqual(JSON.parse(JSON.stringify(flights)), [{ center: [81.5, 16.5], zoom: 11 }]);
  assert.match(p.elements['map-detail'].innerHTML, /Govt Hospital Peruru/);
});

test('the offline map draws every checked layer, not just the first', () => {
  const fills = [];
  const p = page({ size: 400 });
  const cv = p.run("document.getElementById('offline-map')");
  cv.getContext = () => new Proxy({}, {
    get: (t, k) => (k === 'fillRect' ? () => fills.push(t.fillStyle) : k in t ? t[k] : () => {}),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  p.context.__a = asset();
  p.run(assetRun + " LAYERS.forEach(l => l.on = l.id !== 'p_tide_1m'); drawOfflineMap();");
  const rgba = fills.filter(f => String(f).startsWith('rgba('));
  // The gust ramp ends in red, the rain ramp in green: both must be painted.
  const reddish = rgba.some(f => { const [r, g] = f.slice(5).split(',').map(Number); return r > g; });
  const greenish = rgba.some(f => { const [r, g] = f.slice(5).split(',').map(Number); return g > r; });
  assert.ok(reddish && greenish, rgba.join(' '));
});

test('after a storm switch with no map library and no land mask, the map says so', async () => {
  const p = page({ fetch: () => response(200, { grid: {lat_min: 0, lat_max: 1, lon_min: 0, lon_max: 1},
                                                 layers: {}, track: [], assets: [], advisories: [],
                                                 summary: {storm: 'FANI', hours_to_landfall: 48} }) });
  p.run("RUN = { advisories: [], summary: {} }; RUNS = [{storm: 'fani', lead_hours: 48}]; mapLibraryWaitMs = 0;");
  await p.run("loadRun('fani', 48)");
  await new Promise(r => setTimeout(r, 10));        // the wait for the map library
  assert.match(p.elements.map.innerHTML, /Map unavailable/);
  assert.equal(p.run('offlinePaint'), null);
});

test('when the approval record cannot be read, the advisories say so', () => {
  const p = page();
  p.context.__adv = advisory({ approved: null });
  p.run("RUN = { advisories: [__adv], summary: {}, approvals_unavailable: 'The approval record cannot be read.' }; renderAdvisories();");
  const out = p.elements['view-advisories'].innerHTML;
  assert.match(out, /role="alert">The approval record cannot be read\./);
  assert.match(out, /Approval state unknown/);
  assert.doesNotMatch(out, /Approved by/);
});

test('a track point popup escapes every value', () => {
  const p = page();
  p.context.__pt = { lat: 16, lon: 81, vmax_ms: 30, pressure: HOSTILE, rmax_km: HOSTILE,
                     time: '2025-10-28T12:00:00', grade: HOSTILE, landfall: true };
  const out = p.run('trackPointHtml(__pt)');
  assert.ok(!out.includes('<img'));
  assert.match(out, /LANDFALL · &lt;img/);
  assert.match(out, /108 km\/h/);
});

test('coming back to the tab re-reads approvals another officer changed', async () => {
  const fresh = { advisories: [advisory({ approved: false, approved_by: null })], grid: {}, layers: {},
                  track: [], assets: [], summary: { storm: 'MONTHA', hours_to_landfall: 48 } };
  const p = page({ fetch: () => response(200, fresh) });
  p.context.__adv = advisory({ approved: true, approved_by: 'K. Ramesh' });
  p.run("RUN = { advisories: [__adv], summary: { storm: 'MONTHA', hours_to_landfall: 48 } }; renderAdvisories();");
  assert.match(p.elements['view-advisories'].innerHTML, /Approved by K. Ramesh/);
  await p.run('refreshApprovals()');
  assert.equal(p.run('RUN.advisories[0].approved'), false);
  assert.doesNotMatch(p.elements['view-advisories'].innerHTML, /Approved by/);
  assert.ok(p.windowListeners.focus && p.windowListeners.focus.size === 1);
});

test('a failed approval refresh leaves the page as it was', async () => {
  const p = page({ fetch: () => Promise.reject(new TypeError('Failed to fetch')) });
  p.context.__adv = advisory({ approved: true, approved_by: 'K. Ramesh' });
  p.run("RUN = { advisories: [__adv], summary: { storm: 'MONTHA', hours_to_landfall: 48 } };");
  await p.run('refreshApprovals()');
  assert.equal(p.run('RUN.advisories[0].approved'), true);
});

test('a run missing what the panels need is refused once, by name', async () => {
  const bad = { summary: { storm: 'MONTHA' }, grid: {}, layers: {}, track: [], assets: [] };
  const p = page({ fetch: url => (String(url).endsWith('/api/runs')
    ? response(200, [{ storm: 'montha', lead_hours: 48 }]) : response(200, bad)) });
  await p.run('boot()');
  const shown = p.context.document.body.innerHTML;
  assert.match(shown, /cannot read \(no advisories, summary\.hours_to_landfall\)/);
  assert.equal(p.run('RUN'), null, 'nothing was rendered from it');
  p.context.__good = committed('montha_48h.json');
  assert.equal(p.run('checkRun(__good).summary.storm'), 'Montha');
});

test('a run list of the wrong shape is refused', () => {
  const p = page();
  assert.throws(() => p.run("checkRuns([{storm: 3}])"), /run list/);
  assert.throws(() => p.run("checkRuns({})"), /run list/);
  assert.equal(p.run("checkRuns([{storm: 'fani', lead_hours: 48}]).length"), 1);
});

test('the offline map draws the track inside the grid box, not off its edge', () => {
  const calls = [];
  const p = page({ size: 400 });
  const cv = p.run("document.getElementById('offline-map')");
  cv.getContext = () => new Proxy({}, {
    get: (t, k) => (k in t ? t[k] : (...args) => calls.push([k, args])),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  p.context.__a = asset();
  p.run(assetRun + " run().track = [{lat: 10, lon: 90}, {lat: 16.5, lon: 81.5}]; run().landfall_index = 1; drawOfflineMap();");
  const names = calls.map(c => c[0]);
  const clip = names.indexOf('clip'), restore = names.lastIndexOf('restore');
  const trackStroke = names.indexOf('stroke', names.indexOf('lineTo'));
  assert.ok(clip > 0 && clip < trackStroke && trackStroke < restore, names.join(' '));
  const rect = calls[names.indexOf('rect')][1];
  assert.ok(rect[2] > 0 && rect[3] > 0 && rect[0] >= 0 && rect[1] >= 0, rect.join(','));
});

test('an advisory card shows its lead times as numbers only', () => {
  const p = page();
  p.context.__adv = advisory({ lead_hours: [HOSTILE, '24'] });
  p.run('RUN = { advisories: [__adv], summary: {} }; renderAdvisories();');
  const out = p.elements['view-advisories'].innerHTML;
  assert.ok(!out.includes('<img') && out.includes('T−NaN…24h'));
});

// --- the MapLibre map, with a stand-in library ----------------------------------

function mapPage() {
  const p = page({ size: 400 });
  const lib = fakeMapLibre();
  p.context.maplibregl = lib;
  p.context.__a = asset();
  p.run(assetRun + ` run().track = [{lat: 16.4, lon: 81.6, vmax_ms: 25, pressure: 990, rmax_km: 30,
                                      time: '2025-10-28T18:00:00', grade: 'SCS'}];
                     run().landfall_index = 0; run().summary = Object.assign(run().summary,
                       ${JSON.stringify({ storm: 'MONTHA', hours_to_landfall: 48 })});
                     renderSidebar === undefined; LAYERS.forEach(l => l.on = l.id === 'rain_mm');`);
  return { p, lib };
}

test('the map is built on the run\'s own grid and gets every layer once it loads', () => {
  const { p, lib } = mapPage();
  p.run('initMap()');
  const map = lib.made[0];
  assert.deepEqual(JSON.parse(JSON.stringify(map.options.bounds)), [[80, 15], [82, 17]]);
  map.fire('load');
  assert.deepEqual(Object.keys(map.sources).sort(),
                   ['assets', 'src-p_gust_90kmh', 'src-rain_mm', 'track', 'track-pts']);
  assert.equal(map.sources['src-rain_mm'].type, 'image');
  assert.equal(map.layers['lyr-rain_mm'].layout.visibility, 'visible');
  assert.equal(map.layers['lyr-p_gust_90kmh'].layout.visibility, 'none');
  assert.ok(map.layers['assets-pt'] && map.layers['track-line'] && map.layers['track-dots']);
  assert.equal(map.sources.assets.data.features.length, 1, 'green assets are left off the map');
});

test('a layer checkbox shows and hides its layer on the map', () => {
  const p = page({ size: 400 });
  const lib = fakeMapLibre();
  p.context.maplibregl = lib;
  p.context.__run = committed('montha_48h.json');
  p.run("RUN = __run; RUNS = [{storm: 'montha', lead_hours: 48}]; renderSidebar(); initMap();");
  const map = lib.made[0];
  map.fire('load');
  const box = p.elements['L-p_gust_90kmh'];
  box.checked = true;
  box.listeners.change.forEach(fn => fn({ target: box }));
  assert.equal(map.layers['lyr-p_gust_90kmh'].layout.visibility, 'visible');
  box.checked = false;
  box.listeners.change.forEach(fn => fn({ target: box }));
  assert.equal(map.layers['lyr-p_gust_90kmh'].layout.visibility, 'none');
});

test('clicking a marker opens a popup whose every value is escaped', () => {
  const { p, lib } = mapPage();
  p.run('initMap()');
  const map = lib.made[0];
  map.fire('load');
  map.fire('click:assets-pt', { lngLat: [81.5, 16.5],
    features: [{ properties: asset({ name: HOSTILE, driver: HOSTILE, asset_class: HOSTILE }) }] });
  map.fire('click:track-dots', { lngLat: [81.6, 16.4], features: [{ properties: {
    grade: HOSTILE, time: '2025-10-28T18:00:00', vmax_ms: 25, pressure: 990, rmax_km: 30, landfall: 'true' } }] });
  assert.equal(lib.popups.length, 2);
  for (const popup of lib.popups) assert.ok(!popup.html.includes('<img'), popup.html);
  assert.match(lib.popups[0].html, /54% failure probability/);
  assert.match(lib.popups[1].html, /LANDFALL/);
});

test('a basemap that fails hands over to the offline map', () => {
  const { p, lib } = mapPage();
  p.run('initMap()');
  const map = lib.made[0];
  map.fire('error', { error: { message: 'style fetch blocked by the venue network' } });
  assert.equal(map.removed, true);
  assert.equal(p.run('map'), null);
  assert.match(p.elements.map.innerHTML, /offline-map/);
  assert.equal(typeof p.run('offlinePaint'), 'function', 'the offline map is drawing');
});

test('an old map\'s late error cannot take down the map that replaced it', () => {
  const { p, lib } = mapPage();
  p.run('initMap()');
  const old = lib.made[0];
  old.fire('load');
  p.run('initMap()');                  // a storm switch: a new map
  const current = lib.made[1];
  old.fire('error', { error: { message: 'late' } });
  assert.equal(current.removed, false);
  assert.equal(p.run('map === null'), false);
  current.fire('load');
  assert.ok(current.layers['assets-pt']);
});

test('without the library the console waits briefly, then draws the offline map', async () => {
  const p = page({ size: 400 });
  p.context.__a = asset();
  p.run(assetRun + ' mapLibraryWaitMs = 5; showMap();');
  assert.doesNotMatch(p.elements.map?.innerHTML ?? '', /offline-map/, 'still waiting for the module');
  await new Promise(r => setTimeout(r, 20));
  assert.match(p.elements.map.innerHTML, /offline-map/);
  assert.equal((p.windowListeners['maplibre-ready'] || new Set()).size, 0, 'the listener is removed');
});

test('when the library arrives late the console builds the real map with it', () => {
  const p = page({ size: 400 });
  p.context.__a = asset();
  p.run(assetRun + ' mapLibraryWaitMs = 60000; showMap();');
  const lib = fakeMapLibre();
  p.context.maplibregl = lib;
  for (const fn of p.windowListeners['maplibre-ready']) fn();
  assert.equal(lib.made.length, 1, 'the map was built on the event, not after the wait');
});

test('dispatch is offered only once an advisory is approved', () => {
  const p = page();
  p.context.__a1 = advisory({ identifier: 'A-1', approved: false });
  p.context.__a2 = advisory({ identifier: 'A-2', approved: true, approved_by: 'K. Ramesh' });
  p.run('RUN = { advisories: [__a1, __a2], summary: {} }; renderAdvisories();');
  const out = p.elements['view-advisories'].innerHTML;
  assert.match(out, /data-action="dispatch" data-id="A-1" disabled title="Approve first/);
  assert.doesNotMatch(out, /data-id="A-2" disabled/);
});

test('the sensor-network report is escaped, and its absence is said, not hidden', async () => {
  const report = { nodes: { A: 39, [HOSTILE]: 1 }, faults_injected: { [HOSTILE]: 2 },
                   faults_caught: { [HOSTILE]: 1 }, clean_flagged: 0, clean_readings: 17118,
                   false_flag_rate: 0, strongest_3h_fall_at_landfall: { node_id: 'A013', hpa: -4.17 },
                   note: HOSTILE };
  const good = page({ fetch: () => response(200, report) });
  good.run("RUN = { summary: { storm: 'MONTHA' }, advisories: [] };");
  await good.run('renderNetwork()');
  const shown = good.elements['net-sec'].innerHTML;
  assert.ok(!shown.includes('<img') && shown.includes('-4.17 hPa') && shown.includes('17,118'));

  const missing = page({ fetch: () => response(503, { detail: 'The network report cannot be read' }) });
  missing.run("RUN = { summary: { storm: 'MONTHA' }, advisories: [] };");
  await missing.run('renderNetwork()');
  assert.match(missing.elements['net-sec'].innerHTML, /No network report for this storm: The network report cannot be read/);
});

test('sidebar figures are escaped', () => {
  const p = page({ size: 800 });
  p.context.__run = committed('montha_48h.json');
  p.context.__run.summary.ensemble = { source: 'weatherlab', model: HOSTILE };
  p.context.__run.summary.max_rain_mm = HOSTILE;
  p.context.__run.summary.by_class = { [HOSTILE]: { total: 3, expected_failures: HOSTILE } };
  p.run("RUN = __run; RUNS = [{storm: 'montha', lead_hours: 48}]; renderSidebar();");
  assert.ok(!p.elements['hazard-stats'].innerHTML.includes('<img'));
  assert.ok(!p.elements['exposure-stats'].innerHTML.includes('<img'));
});

const RUNS_DIR = new URL('../../data/runs/', import.meta.url);
const committed = name => JSON.parse(readFileSync(new URL(name, RUNS_DIR), 'utf8'));

for (const name of ['montha_48h.json', 'fani_48h.json', 'fani_12h.json']) {
  test(`every panel renders the committed ${name} without throwing`, () => {
    const p = page({ size: 800 });
    p.context.__run = committed(name);
    p.run(`RUN = __run; RUNS = [{storm: 'montha', lead_hours: 48}, {storm: 'fani', lead_hours: 48},
                                {storm: 'fani', lead_hours: 12}];`);
    // guard() swallows and logs; call the renderers directly so a throw fails the test.
    p.run('renderSidebar(); renderAssets(); renderAdvisories(); renderVerify(); renderTriggers();');
    p.run('drawOfflineMap();');
    const run = p.context.__run;
    assert.ok(p.elements['storm-block'].innerHTML.includes(run.summary.storm));
    assert.ok(p.elements['view-assets'].innerHTML.includes('row-name'));
    assert.ok(p.elements['view-advisories'].innerHTML.includes('data-action="approve"'));
    assert.ok(p.elements['view-verify'].innerHTML.includes('Against what actually happened'));
    assert.ok(p.elements['view-triggers'].innerHTML.length > 0);
    assert.equal(String(p.elements['n-assets'].textContent), String(run.assets.length));
  });
}

test('a satellite section with results renders every verdict', () => {
  const p = page();
  const run = committed('fani_48h.json');
  const out = p.run(`observedChecks(${JSON.stringify(run.summary.verification.observed)})`);
  for (const title of ['Rain against GPM IMERG', 'Flooding against Sentinel-1', 'Outages against VIIRS night lights'])
    assert.ok(out.includes(title), title);
});

test('boot loads the run list, then the run the URL names', async () => {
  const run = committed('fani_12h.json');
  const asked = [];
  const p = page({
    size: 800,
    fetch: url => {
      asked.push(String(url));
      if (String(url).endsWith('/api/runs'))
        return response(200, [{ storm: 'montha', lead_hours: 48 }, { storm: 'fani', lead_hours: 12 }]);
      if (String(url).endsWith('/api/run/fani/12')) return response(200, run);
      return response(404, { detail: 'none' });
    },
  });
  p.context.location.search = '?storm=fani&lead=12';
  for (let i = 0; i < 5; i++) await new Promise(r => setTimeout(r, 0));
  assert.ok(asked.includes('/api/run/fani/12'), asked.join(' '));
  assert.ok(p.elements['storm-block'].innerHTML.includes('Fani'));
});

test('switching storms keeps the current run when the new one fails to load', async () => {
  const p = page({ fetch: () => response(500, { detail: 'disk on fire' }) });
  p.context.__run = committed('montha_48h.json');
  p.run('RUN = __run;');
  await p.run("loadRun('fani', 48)");
  assert.equal(p.run('RUN.summary.storm'), 'Montha');
  assert.match(p.elements.toast.textContent, /Could not load fani/);
});

test('tabs select by name, and an unknown name changes nothing', () => {
  const p = page();
  assert.equal(p.run("selectTab('nope')"), false);
});


function dialogPage(fetchStub) {
  const p = page({ fetch: fetchStub });
  const dlg = p.context.document.getElementById('act-dialog');
  dlg.open = false;
  dlg.showModal = () => { dlg.open = true; };
  dlg.close = () => { dlg.open = false; };
  const field = value => ({ value, focus() {} });
  const form = { operator: field(''), note: field(''), code: field(''), reset() { this.operator.value = ''; } };
  // As the DOM gives them: by name, from the form's elements.
  form.elements = { namedItem: name => form[name] ?? null };
  p.context.document.getElementById('act-operator');
  p.context.__adv = advisory();
  p.run("RUN = { advisories: [__adv], summary: { storm: 'MONTHA', hours_to_landfall: 48 } };");
  const submit = () => p.context.onDialogSubmit({ preventDefault() {}, target: form });
  return { p, dlg, form, submit };
}

test('the approval dialog asks for the code only when the server does, then closes', async () => {
  const { p, dlg, form, submit } = dialogPage((url, opts = {}) =>
    (opts.headers || {}).Authorization === 'Bearer c0de'
      ? response(200, { operator: 'K. Ramesh' })
      : response(401, { detail: 'A valid access code is required' }));
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  assert.equal(dlg.open, true);
  assert.equal(p.elements['act-title'].textContent, 'Approve advisory');
  assert.equal(p.elements['act-code-row'].hidden, true);
  form.operator.value = 'K. Ramesh';
  await submit();
  assert.equal(dlg.open, true, 'still open: a code is needed');
  assert.equal(p.elements['act-code-row'].hidden, false);
  assert.match(p.elements['act-error'].textContent, /access code/);
  form.code.value = 'c0de';
  await submit();
  assert.equal(dlg.open, false);
  assert.ok(p.elements['view-advisories'].innerHTML.includes('Approved by K. Ramesh'));
});

test('while an action is being recorded the button says so and cannot be pressed twice', async () => {
  // The audit trail may be BigQuery, where an approval takes seconds to record.
  let finish;
  const { p, form, submit } = dialogPage(() => new Promise(r => { finish = r; }));
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  const button = p.elements['act-submit'];
  form.operator.value = 'K. Ramesh';
  const done = submit();
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, 'Recording…');
  finish(await response(200, { operator: 'K. Ramesh' }));
  await done;
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, 'Approve');
});

test('after an approval, focus moves to the card\'s Dispatch button, not the page', async () => {
  // Found in review: the card is redrawn while the dialog is open, so the
  // Approve button focus would have returned to no longer exists.
  const { p, form, submit } = dialogPage(() => response(200, { operator: 'K. Ramesh' }));
  let focused = null;
  p.context.document.querySelector = sel => ({ focus() { focused = sel; } });
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  form.operator.value = 'K. Ramesh';
  await submit();
  assert.equal(focused, '[data-action="dispatch"][data-id="T5-TEST-1"]');
});

// Google sign-in, as web/auth-loader.mjs hands it over (window.bobAuth).
function signInPage(fetchStub, { officer = null, signIn } = {}) {
  const d = dialogPage(fetchStub);
  const state = { officer, callbacks: [], signOuts: 0 };
  d.p.context.window.bobAuth = {
    signIn: signIn || (async () => (state.officer = { email: 'k.ramesh@osdma.example', name: 'K. Ramesh' })),
    signOut: async () => { state.signOuts += 1; state.officer = null; },
    token: async () => (state.officer ? `id-token-for-${state.officer.email}` : null),
    user: () => state.officer,
    onChange: cb => state.callbacks.push(cb),
  };
  (d.p.windowListeners['auth-ready'] || new Set()).forEach(fn => fn());
  return { ...d, state };
}
const RAMESH = { email: 'k.ramesh@osdma.example', name: 'K. Ramesh' };

test('signed in, a write carries the officer\'s sign-in, not a stored access code', async () => {
  const sent = [];
  const { p, submit } = signInPage((url, opts = {}) => {
    if (opts.method === 'POST') sent.push((opts.headers || {}).Authorization);
    return response(200, { operator: 'K. Ramesh <k.ramesh@osdma.example>' });
  }, { officer: RAMESH });
  p.storage['bob-access'] = 'an-old-access-code';
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  await submit();
  assert.deepEqual(sent, ['Bearer id-token-for-k.ramesh@osdma.example']);
});

test('signed in, the dialog asks for no name and says whose account is recorded', () => {
  const { p } = signInPage(() => response(200, {}), { officer: RAMESH });
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  assert.equal(p.elements['act-who'].hidden, true);
  assert.equal(p.elements['act-operator'].required, false);
  assert.match(p.elements['act-what'].textContent, /Recorded as k\.ramesh@osdma\.example\./);
});

test('not signed in, Approve signs in first and then opens the dialog', async () => {
  const { p, dlg } = signInPage(() => response(200, {}));
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  assert.equal(dlg.open, false, 'not before the sign-in');
  await new Promise(r => setTimeout(r, 0));
  assert.equal(dlg.open, true);
  assert.match(p.elements['act-what'].textContent, /Recorded as k\.ramesh/);
});

test('a sign-in that fails opens nothing and says why', async () => {
  const { p, dlg } = signInPage(() => response(200, {}),
    { signIn: () => Promise.reject(new Error('The popup was closed')) });
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  await new Promise(r => setTimeout(r, 0));
  assert.equal(dlg.open, false);
  assert.match(p.elements.toast.textContent, /Sign-in did not complete: .*The popup was closed/);
});

test('the banner shows who is signed in, escaped, and signs them out', async () => {
  const { p, state } = signInPage(() => response(200, {}), { officer: RAMESH });
  state.callbacks.forEach(cb => cb({ email: HOSTILE, name: '' }));
  const html = p.elements['auth-state'].innerHTML;
  assert.ok(!html.includes('<img') && html.includes('data-action="sign-out"'));
  p.click({ action: 'sign-out' });
  assert.equal(state.signOuts, 1);
  state.callbacks.forEach(cb => cb(null));
  assert.ok(p.elements['auth-state'].innerHTML.includes('Sign in with Google'));
});

test('a sign-in the server refuses asks to sign in again, not for a code', async () => {
  const { p, dlg, submit } = signInPage(
    () => response(401, { detail: 'Sign in again: this sign-in is not valid here (ValueError)' }),
    { officer: RAMESH });
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  await submit();
  assert.equal(dlg.open, true);
  assert.equal(p.elements['act-code-row'].hidden, true, 'no access-code field');
  assert.match(p.elements['act-error'].textContent, /Sign in again from the banner/);
});

test('a server refusal keeps the dialog open with the reason', async () => {
  const { p, dlg, form, submit } = dialogPage(() => response(400, { detail: 'Name the accountable operator in full' }));
  p.click({ action: 'approve', id: 'T5-TEST-1' });
  form.operator.value = 'K';
  await submit();
  assert.equal(dlg.open, true);
  assert.match(p.elements['act-error'].textContent, /in full/);
});

test('dispatch that needs a code opens the dialog in code mode', async () => {
  const { p, dlg } = dialogPage(() => response(401, { detail: 'A valid access code is required' }));
  await p.run("dispatch('T5-TEST-1')");
  assert.equal(dlg.open, true);
  assert.equal(p.elements['act-title'].textContent, 'Access code needed');
  assert.equal(p.elements['act-names'].hidden, true);
});

test('the CAP button shows the XML as text and hides it again', () => {
  const p = page();
  p.context.__adv = advisory({ cap_xml: '<alert><b>x</b></alert>' });
  p.run('RUN = { advisories: [__adv], summary: {} };');
  const pre = p.context.document.getElementById('cap-T5-TEST-1');
  pre.hidden = true;
  p.click({ action: 'cap', id: 'T5-TEST-1' });
  assert.equal(pre.hidden, false);
  assert.equal(pre.textContent, '<alert><b>x</b></alert>');
  assert.equal(pre.innerHTML, '');
  p.click({ action: 'cap', id: 'T5-TEST-1' });
  assert.equal(pre.hidden, true);
});


test('a panel that fails to draw says so in the panel, not only in the console', () => {
  const p = page();
  p.run("RUN = { assets: null, summary: {} }; guard('assets', renderAssets);");
  const out = p.elements['view-assets'].innerHTML;
  assert.match(out, /role="alert"/);
  assert.match(out, /This panel could not be drawn/);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { await fn(); console.log(`ok   ${name}`); }
  catch (err) { failed++; console.log(`FAIL ${name}\n     ${err.message}`); }
}
console.log(`${tests.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
