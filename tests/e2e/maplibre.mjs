// The MapLibre map in a real browser engine: Chrome rendering WebGL in
// software (SwiftShader), the vendored MapLibre (web/vendor/maplibre-gl) and
// the live CARTO basemap, under the console's content policy. Fails on any
// content-policy violation, script error or unloaded layer.
//
// Usage: node maplibre.mjs <chrome-binary> <console-url>

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [chrome, url] = process.argv.slice(2);
const port = 9600 + Math.floor(Math.random() * 200);
const browser = spawn(chrome, ['--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
  `--remote-debugging-port=${port}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'bob-gl-'))}`,
  '--no-first-run', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fail = msg => { console.error(`FAIL ${msg}`); browser.kill(); process.exit(1); };

let target;
for (let i = 0; i < 60 && !target; i++) {
  try {
    target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json())
      .find(t => t.type === 'page')?.webSocketDebuggerUrl;
  } catch { /* not up yet */ }
  if (!target) await sleep(250);
}
if (!target) fail('Chrome did not start');
const ws = new WebSocket(target);
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const waiting = new Map();
const problems = [];
ws.addEventListener('message', ev => {
  const msg = JSON.parse(ev.data);
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
  if (msg.method === 'Runtime.exceptionThrown') problems.push(msg.params.exceptionDetails.text);
  if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') problems.push(msg.params.entry.text);
});
const send = (method, params = {}) => new Promise(r => {
  const id = ++seq; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params }));
});
const js = async expr => (await send('Runtime.evaluate',
  { expression: expr, awaitPromise: true, returnByValue: true })).result.result.value;
const until = async (expr, what, ms = 30000) => {
  for (let t = 0; t < ms; t += 200) { if (await js(expr)) return; await sleep(200); }
  fail(`timed out waiting for ${what}; browser reported: ${problems.join(' | ') || 'nothing'}`);
};

await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
await send('Page.navigate', { url: `${url}/?storm=montha&lead=48#assets` });
await until(`typeof map !== 'undefined' && !!map && map.loaded()`, 'MapLibre and its basemap');
if (await js(`!!document.getElementById('offline-map')`)) fail('fell back to the offline map');
await until(`['src-rain_mm', 'assets', 'track'].every(s => map.isSourceLoaded(s))`,
            'the hazard, asset and track sources');
const shown = await js(`LAYERS.filter(l => l.on).map(l => map.getLayoutProperty('lyr-' + l.id, 'visibility'))`);
if (!shown.length || shown.some(v => v !== 'visible')) fail(`checked layers not visible: ${shown}`);

// A table row takes the map to the asset.
await js(`document.querySelector('#view-assets [data-action="asset"]').click()`);
await sleep(1500);
const zoom = await js(`map.getZoom()`);
if (!(zoom > 9)) fail(`the map did not fly to the asset (zoom ${zoom})`);

// axe on the map view too, the MapLibre controls included.
const AXE = readFileSync(fileURLToPath(new URL('./vendor/axe-core/axe.min.js', import.meta.url)), 'utf8');
await send('Runtime.evaluate', { expression: AXE });
const violations = await js(`axe.run(document, {runOnly: {type: 'tag',
    values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})
  .then(r => r.violations.map(x => x.id + ' (' + x.nodes.length + ')'))`);
if (!Array.isArray(violations)) fail('axe did not run');
if (violations.length) fail(`axe on the MapLibre view: ${violations.join(', ')}`);

const version = await js(`maplibregl.getVersion()`);
if (problems.length) fail(`browser reported: ${problems.join(' | ')}`);
console.log(`ok   MapLibre ${version} loaded the basemap and every layer; a row flew the map to zoom ${zoom.toFixed(1)}; axe clean`);
ws.close(); browser.kill();
process.exit(0);
