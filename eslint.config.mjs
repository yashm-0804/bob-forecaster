// Lints the console (web/app.js, web/map-loader.mjs, web/auth-loader.mjs), the JavaScript tests
// and scripts. Self-contained:
// no plugins or shared configs, so `npx eslint@9` needs nothing installed.
// Correctness rules only; formatting is not policed here.

const correctness = {
  'no-undef': 'error',
  'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none' }],
  'no-redeclare': 'error',
  'no-dupe-keys': 'error',
  'no-duplicate-case': 'error',
  'no-unreachable': 'error',
  'no-self-assign': 'error',
  'no-self-compare': 'error',
  'no-constant-condition': 'error',
  'no-cond-assign': 'error',
  'no-fallthrough': 'error',
  'use-isnan': 'error',
  'valid-typeof': 'error',
  'eqeqeq': ['error', 'smart'],
  'no-eval': 'error',
  'no-implied-eval': 'error',
  'no-new-func': 'error',
  'no-script-url': 'error',
};

const browser = Object.fromEntries([
  'window', 'document', 'location', 'history', 'fetch', 'sessionStorage', 'console',
  'URLSearchParams', 'setTimeout', 'clearTimeout', 'alert', 'Image', 'devicePixelRatio',
  'requestAnimationFrame', 'Path2D',
].map(g => [g, 'readonly']));
browser.maplibregl = 'readonly';          // set by web/map-loader.mjs (vendored MapLibre)
browser.Event = 'readonly';

const node = Object.fromEntries([
  'console', 'process', 'URL', 'setTimeout', 'clearTimeout', 'fetch', 'WebSocket',
  'URLSearchParams', 'Promise',
].map(g => [g, 'readonly']));

export default [
  {
    files: ['web/app.js'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'script', globals: browser },
    rules: correctness,
  },
  {
    files: ['web/map-loader.mjs', 'web/auth-loader.mjs'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'module', globals: browser },
    rules: correctness,
  },
  {
    files: ['tests/**/*.mjs', 'scripts/*.mjs'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'module',
                       globals: { ...node, Buffer: 'readonly' } },
    rules: correctness,
  },
];
