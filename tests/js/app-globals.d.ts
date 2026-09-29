// Globals the console expects from the page: MapLibre, which
// web/map-loader.mjs loads from web/vendor and hands over. Declared loosely;
// the part of it the console uses is typed as MapLike in web/app.js, and the
// real library is exercised by tests/e2e/maplibre.mjs in a browser.
declare const maplibregl: any;

// Google sign-in, which web/auth-loader.mjs hands over when the server has
// it configured (api/identity.py); absent otherwise.
interface Officer { email: string; name: string }
interface BobAuth {
  signIn(): Promise<Officer | null>;
  signOut(): Promise<void>;
  token(): Promise<string | null>;
  user(): Officer | null;
  onChange(callback: (officer: Officer | null) => void): void;
}
interface Window { bobAuth?: BobAuth }
