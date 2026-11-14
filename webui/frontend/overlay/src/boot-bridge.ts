// boot-bridge.ts -- one synchronous gate, imported FIRST by main.tsx (patched
// copy): decides whether the page is served by the spektralab-fnos bridge or
// is plain `vite` dev (mock host). Top-level await: every later module sees
// window.__SPK_BRIDGE__ set.

declare global {
  interface Window {
    __SPK_BRIDGE__?: boolean;
  }
}

try {
  const r = await fetch('/api/appinfo', { headers: { Accept: 'application/json' } });
  window.__SPK_BRIDGE__ = r.ok && !!(await r.json().catch(() => null))?.ok;
} catch {
  window.__SPK_BRIDGE__ = false;
}

export const isBridge = () => window.__SPK_BRIDGE__ === true;
