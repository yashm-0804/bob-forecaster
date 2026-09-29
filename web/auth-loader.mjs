// Google sign-in for officers (Firebase Authentication), served from this
// server: web/vendor/firebase, see its VENDOR.json. The console script is a
// classic script, so this module sets it up and hands it over:
// `window.bobAuth`, then an `auth-ready` event. When the server has no
// sign-in configured (/api/auth-config says null), nothing is handed over and
// the console works as before, with the operator access code.
import { initializeApp } from './vendor/firebase/firebase-app.js';
import {
  browserSessionPersistence, getAuth, GoogleAuthProvider, onAuthStateChanged, setPersistence,
  signInWithPopup, signOut,
} from './vendor/firebase/firebase-auth.js';

/** @param {{email: string | null, displayName: string | null} | null} user */
const officer = user => (user && user.email ? { email: user.email, name: user.displayName || '' } : null);

const reply = await fetch('/api/auth-config').then(r => r.json()).catch(() => null);
if (reply && reply.firebase) {
  const auth = getAuth(initializeApp(reply.firebase));
  // Signed in for this tab only, as the access code was.
  await setPersistence(auth, browserSessionPersistence);
  window.bobAuth = {
    signIn: () => signInWithPopup(auth, new GoogleAuthProvider()).then(r => officer(r.user)),
    signOut: () => signOut(auth),
    token: () => (auth.currentUser ? auth.currentUser.getIdToken() : Promise.resolve(null)),
    user: () => officer(auth.currentUser),
    onChange: callback => onAuthStateChanged(auth, user => callback(officer(user))),
  };
  window.dispatchEvent(new Event('auth-ready'));
}
