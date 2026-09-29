// MapLibre GL JS, served from this server (web/vendor/maplibre-gl, see its
// VENDOR.json), not a CDN. From version 6 it ships only as ES modules, and
// the console script is a classic script, so this module loads it and hands
// it over: `window.maplibregl`, then a `maplibre-ready` event. If the import
// fails -- an old browser, a blocked file -- no event comes, and the console
// draws its offline map instead.
import * as maplibregl from './vendor/maplibre-gl/maplibre-gl.mjs';

window.maplibregl = maplibregl;
window.dispatchEvent(new Event('maplibre-ready'));
