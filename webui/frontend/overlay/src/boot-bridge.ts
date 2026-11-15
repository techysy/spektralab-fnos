// boot-bridge.ts -- one synchronous gate, imported FIRST by main.tsx (patched
// copy): decides whether the page is served by the spektralab-fnos bridge or
// is plain `vite` dev (mock host). Top-level await: every later module sees
// window.__SPK_BRIDGE__ set.
//
// The app may live under a sub-path (fnOS unified gateway: /app/<appname>/),
// so every bridge URL is built from the page's own directory, probed here and
// exported as __SPK_BASE__ (with a trailing slash).

declare global {
  interface Window {
    __SPK_BRIDGE__?: boolean;
    __SPK_BASE__?: string;
  }
}

function pageBase(): string {
  const p = window.location.pathname;
  return p.endsWith('/') ? p : p.slice(0, p.lastIndexOf('/') + 1) || '/';
}

try {
  const base = pageBase();
  const r = await fetch(base + 'api/appinfo', { headers: { Accept: 'application/json' } });
  const ok = r.ok && !!(await r.json().catch(() => null))?.ok;
  if (ok) {
    window.__SPK_BRIDGE__ = true;
    window.__SPK_BASE__ = base;
  } else {
    // a nested probe may 404 when the app is served at the root but the
    // directory guess went wrong; fall back to the origin root
    const r2 = await fetch('/api/appinfo', { headers: { Accept: 'application/json' } });
    window.__SPK_BRIDGE__ = r2.ok && !!(await r2.json().catch(() => null))?.ok;
    window.__SPK_BASE__ = '/';
  }
} catch {
  window.__SPK_BRIDGE__ = false;
  window.__SPK_BASE__ = '/';
}

export const isBridge = () => window.__SPK_BRIDGE__ === true;
export const bridgeBase = () => window.__SPK_BASE__ ?? '/';
