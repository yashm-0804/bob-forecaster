// End to end, in a real browser: open the console, approve an advisory
// through the dialog (supplying the access code when the server asks for it),
// then dispatch it. Drives headless Chrome over the DevTools protocol with
// Node's built-in WebSocket -- no test framework, no downloads.
//
// Usage: node approve_dispatch.mjs <chrome-binary> <console-url> <access-code>

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [chrome, url, code] = process.argv.slice(2);
const port = 9300 + Math.floor(Math.random() * 500);
const profile = mkdtempSync(join(tmpdir(), 'bob-e2e-'));
const browser = spawn(chrome, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', 'about:blank'],
  { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const fail = msg => { console.error(`FAIL ${msg}`); browser.kill(); process.exit(1); };

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
      const page = list.find(t => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  fail('Chrome did not start');
}

const ws = new WebSocket(await target());
await new Promise(r => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const waiting = new Map();
const problems = [];
ws.addEventListener('message', ev => {
  const msg = JSON.parse(ev.data);
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
  if (msg.method === 'Runtime.exceptionThrown') problems.push(msg.params.exceptionDetails.text);
  if (msg.method === 'Log.entryAdded' && /Content Security Policy|integrity/i.test(msg.params.entry.text))
    problems.push(msg.params.entry.text);
});
const send = (method, params = {}) => new Promise(r => {
  const id = ++seq; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params }));
});
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result.exceptionDetails) fail(`page script failed: ${expr}`);
  return r.result.result.value;
};
const until = async (expr, what, ms = 10000) => {
  for (let t = 0; t < ms; t += 100) { if (await js(expr)) return; await sleep(100); }
  fail(`timed out waiting for ${what}`);
};

await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
await send('Page.navigate', { url: `${url}/?storm=montha&lead=48#advisories` });
await until(`!!document.querySelector('[data-action="approve"]')`, 'the advisory queue');

// Accessibility basics on the rendered page, before anything is clicked.
const audit = await js(`(() => {
  const out = [];
  const name = el => (el.getAttribute('aria-label') || el.textContent || '').trim();
  if (!document.documentElement.lang) out.push('no document language');
  document.querySelectorAll('button').forEach(b => { if (!name(b)) out.push('unnamed button'); });
  document.querySelectorAll('input, select, textarea').forEach(i => {
    const labelled = i.getAttribute('aria-label') || i.closest('label')
      || (i.id && document.querySelector('label[for="' + i.id + '"]'));
    if (!labelled) out.push('unlabelled ' + i.tagName.toLowerCase() + ' ' + (i.id || i.name));
  });
  document.querySelectorAll('[role="tab"]').forEach(t => {
    const panel = document.getElementById(t.getAttribute('aria-controls') || '');
    if (!panel || panel.getAttribute('role') !== 'tabpanel') out.push('tab without panel: ' + t.id);
  });
  if (!document.querySelector('[role="tablist"]')) out.push('tabs without a tablist');
  const ids = [...document.querySelectorAll('[id]')].map(e => e.id);
  ids.filter((x, i) => ids.indexOf(x) !== i).forEach(x => out.push('duplicate id ' + x));
  document.querySelectorAll('img').forEach(img => { if (!img.hasAttribute('alt')) out.push('img without alt'); });
  return out;
})()`);
if (audit.length) fail(`accessibility: ${[...new Set(audit)].join('; ')}`);

// axe-core (vendored, WCAG 2.1 A and AA) on every panel, then later on the
// open dialog and at phone width. Any violation fails the test.
const AXE = readFileSync(fileURLToPath(new URL('./vendor/axe-core/axe.min.js', import.meta.url)), 'utf8');
await send('Runtime.evaluate', { expression: AXE });
const axeRun = async where => {
  const v = await js(`axe.run(document, {runOnly: {type: 'tag',
      values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})
    .then(r => r.violations.map(x => x.id + ' (' + x.nodes.length + ')'))`);
  if (!Array.isArray(v)) fail(`axe did not run on ${where}`);
  if (v.length) fail(`axe on ${where}: ${v.join(', ')}`);
};
for (const tab of ['assets', 'advisories', 'triggers', 'verify']) {
  await js(`selectTab(${JSON.stringify(tab)})`);
  await axeRun(`the ${tab} panel`);
}
await js(`selectTab('advisories')`);

const id = await js(`document.querySelector('[data-action="approve"]').dataset.id`);
const card = `document.getElementById('adv-${id}')`;

// Approve without the code: the dialog must ask for it rather than fail.
await js(`document.querySelector('[data-action="approve"][data-id="${id}"]').click()`);
await until(`document.getElementById('act-dialog').open`, 'the approval dialog');
await axeRun('the open approval dialog');
await js(`document.getElementById('act-operator').value = 'K. Ramesh, DDMA'`);
await js(`document.getElementById('act-submit').click()`);
await until(`!document.getElementById('act-code-row').hidden`, 'the access code field');
if (!(await js(`/access code/.test(document.getElementById('act-error').textContent)`)))
  fail('no explanation of why the code is needed');

// Now with the code.
await js(`document.getElementById('act-code').value = ${JSON.stringify(code)}`);
await js(`document.getElementById('act-submit').click()`);
await until(`!document.getElementById('act-dialog').open`, 'the dialog to close');
await until(`${card}.textContent.includes('Approved by K. Ramesh, DDMA')`, 'the approval to show');

// Dispatch: the gate passes, and the result is shown in the card.
await js(`document.querySelector('[data-action="dispatch"][data-id="${id}"]').click()`);
await until(`/Dispatch gate passed/.test(document.getElementById('res-${id}').textContent)`,
            'the dispatch result');

// The same flow by keyboard alone: real key events through Chrome's input
// pipeline, not element.click(). Enter opens the dialog from the button,
// focus lands inside it, Escape dismisses it, typing and Enter approve.
const KEYS = { Enter: [13, '\r'], Escape: [27], ArrowLeft: [37], ArrowRight: [39], Tab: [9] };
const press = async name => {
  const [code, text] = KEYS[name];
  const base = { key: name, code: name, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
  await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base, ...(text ? { text } : {}) });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
};
const second = await js(`document.querySelector('[data-action="approve"]').dataset.id`);
if (second === id) fail('the approved advisory still offers Approve');
await js(`document.querySelector('[data-action="approve"][data-id="${second}"]').focus()`);
await press('Enter');
await until(`document.getElementById('act-dialog').open`, 'the dialog opened by Enter');
if (!(await js(`document.getElementById('act-dialog').contains(document.activeElement)`)))
  fail('focus did not move into the open dialog');
await press('Escape');
await until(`!document.getElementById('act-dialog').open`, 'Escape to close the dialog');
await js(`document.querySelector('[data-action="approve"][data-id="${second}"]').focus()`);
await press('Enter');
await until(`document.getElementById('act-dialog').open`, 'the dialog opened again');
await js(`document.getElementById('act-operator').focus()`);
await send('Input.insertText', { text: 'S. Das, SEOC' });
await press('Enter');            // the code from the first approval is kept for this tab
await until(`!document.getElementById('act-dialog').open`, 'Enter to submit the approval');
await until(`document.getElementById('adv-${second}').textContent.includes('Approved by S. Das, SEOC')`,
            'the keyboard approval to show');
// Focus stays in the card, on what comes next, instead of falling to the page.
await until(`document.activeElement && document.activeElement.dataset.action === 'dispatch'
             && document.activeElement.dataset.id === ${JSON.stringify(second)}`,
            'focus on the approved advisory\'s Dispatch button');
// Tabs follow the arrow keys; an asset row answers Enter with its details.
await js(`document.getElementById('tab-advisories').focus()`);
await press('ArrowLeft');
await until(`document.getElementById('tab-assets').getAttribute('aria-selected') === 'true'`,
            'ArrowLeft to select the Assets tab');
await js(`document.querySelector('#view-assets [data-action="asset"]').focus()`);
await press('Enter');
await until(`!!document.getElementById('map-detail') && !document.getElementById('map-detail').hidden
             && document.getElementById('map-detail').textContent.includes('failure probability')`,
            'Enter on an asset row to show its details');

// A high-DPI screen: the offline map must fill its box, not draw at twice it.
await send('Emulation.setDeviceMetricsOverride',
           { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
await send('Page.navigate', { url: `${url}/?storm=fani&lead=48` });
await until(`!!document.getElementById('offline-map') || !!document.querySelector('.maplibregl-canvas')`,
            'a map');
const fit = await js(`(() => {
  const box = document.getElementById('map').getBoundingClientRect();
  const cv = document.getElementById('offline-map') || document.querySelector('.maplibregl-canvas');
  const r = cv.getBoundingClientRect();
  return [Math.round(r.width - box.width), Math.round(r.height - box.height),
          Math.round(r.right - box.right)];
})()`);
if (fit.some(d => Math.abs(d) > 1)) fail(`map does not fit its box at DPR 2: ${fit.join(', ')}`);

// A phone: no horizontal scrolling, and still no accessibility violations --
// on the cycle drafted in Telugu too, so the translations are checked with it.
await send('Emulation.setDeviceMetricsOverride',
           { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
await send('Page.navigate', { url: `${url}/?storm=montha&lead=24#advisories` });
await until(`!!document.querySelector('[data-action="approve"]')`, 'the console at phone width');
if (!await js(`!!document.querySelector('.adv-tr [lang="te-IN"]')
               && /[\u0C00-\u0C7F]/.test(document.querySelector('.adv-tr').textContent)`))
  fail('the Telugu text an approval covers is not shown in the card');
if (await js(`document.documentElement.scrollWidth > window.innerWidth + 1`))
  fail('the console scrolls sideways at 390 px');
await send('Runtime.evaluate', { expression: AXE });
await axeRun('the console at 390 px');

if (problems.length) fail(`browser reported: ${problems.join(' | ')}`);
console.log(`ok   axe clean on every panel, the dialog and at 390 px; approved and dispatched ${id}; `
  + `approved ${second} by keyboard alone; map fits at DPR 2`);
ws.close(); browser.kill();
process.exit(0);
