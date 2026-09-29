// Screenshots of the console, for the README, the deck and anyone who wants
// to see it without running it. Drives headless Chrome over the DevTools
// protocol with Node's built-in WebSocket, as tests/e2e/approve_dispatch.mjs
// does. Headless Chrome has no GPU, so by default the map is the console's own
// offline map. With --gl, Chrome renders WebGL in software (SwiftShader) and
// the screenshots show MapLibre and the basemap, as a normal browser does.
//
// Usage: node scripts/screenshots.mjs <chrome-binary> <console-url> <out-dir> [--gl]

import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [chrome, url, out, mode] = process.argv.slice(2);
const gl = mode === '--gl';
mkdirSync(out, { recursive: true });
const port = 9800 + Math.floor(Math.random() * 100);
const graphics = gl ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : ['--disable-gpu'];
const browser = spawn(chrome, ['--headless=new', ...graphics, `--remote-debugging-port=${port}`,
  `--user-data-dir=${mkdtempSync(join(tmpdir(), 'bob-shots-'))}`, '--no-first-run',
  '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fail = msg => { console.error(`FAIL ${msg}`); browser.kill(); process.exit(1); };

let target;
for (let i = 0; i < 60 && !target; i++) {
  try {
    const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    target = pages.find(t => t.type === 'page')?.webSocketDebuggerUrl;
  } catch { /* not up yet */ }
  if (!target) await sleep(250);
}
if (!target) fail('Chrome did not start');
const ws = new WebSocket(target);
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const waiting = new Map();
ws.addEventListener('message', ev => {
  const msg = JSON.parse(ev.data);
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
});
const send = (method, params = {}) => new Promise(r => {
  const id = ++seq; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params }));
});
const js = async expr => (await send('Runtime.evaluate',
  { expression: expr, awaitPromise: true, returnByValue: true })).result.result.value;
const until = async (expr, what) => {
  for (let t = 0; t < 15000; t += 100) { if (await js(expr)) return; await sleep(100); }
  fail(`timed out waiting for ${what}`);
};
const size = (width, height, scale = 1, mobile = false) =>
  send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile });
const open = async (path, ready = `!!document.querySelector('[data-action="approve"]')`) => {
  await send('Page.navigate', { url: url + path });
  await until(ready, path);
  // The map: MapLibre with its basemap loaded, or the offline map.
  await until(`(typeof map !== 'undefined' && map && map.loaded()) || !!document.getElementById('offline-map')`,
              'a map');
  await sleep(gl ? 2500 : 700);                  // let tiles, layers and fonts settle
  const which = await js(`document.getElementById('offline-map') ? 'offline map' : 'MapLibre'`);
  console.log(`   map: ${which}`);
};
const shot = async (name, caption) => {
  const { result } = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(out, name), Buffer.from(result.data, 'base64'));
  console.log(`${name}  ${caption}`);
};

await send('Page.enable'); await send('Runtime.enable');
await size(1440, 900);

await open('/?storm=montha&lead=48#assets');
await shot('01-assets.png', 'Montha, T-48 h: storm, hazard layers, map, and assets ranked by expected consequence');
await js(`document.querySelector('#view-assets [data-action="asset"]').click()`);
await sleep(400);
await shot('02-asset-detail.png', 'An asset picked in the table: ringed on the map, its figures in the card');
await js(`selectTab('advisories')`); await sleep(300);
await shot('03-advisories.png', 'Department advisories: drafted from the scores, CAP 1.2, awaiting a named approval');
await js(`document.querySelector('[data-action="approve"]').click()`);
await until(`document.getElementById('act-dialog').open`, 'the approval dialog');
await js(`document.getElementById('act-operator').value = 'K. Ramesh, DDMA'`);
await shot('04-approve-dialog.png', 'Approving: the officer names themself; nothing is sent without this');
await js(`document.getElementById('act-dialog').close()`);
await js(`selectTab('triggers')`); await sleep(300);
await shot('05-triggers.png', 'Parametric triggers: payout probability per zone, and basis risk');
await js(`selectTab('verify')`); await sleep(300);
await shot('06-checks.png', 'Checks: the forecast against IMD and against what satellites saw, misses included');

await open('/?storm=fani&lead=48#assets');
await shot('07-fani.png', 'Fani, T-48 h: the same console on a wind-driven storm');

await size(390, 844, 2, true);
await open('/?storm=montha&lead=48#advisories');
await shot('08-phone.png', 'At phone width');

ws.close(); browser.kill();
process.exit(0);
