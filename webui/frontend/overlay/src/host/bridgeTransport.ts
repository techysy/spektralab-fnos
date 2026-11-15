// bridgeTransport.ts -- the engine host, reached through the fnOS bridge
// service (bridge.py). Same HOST-PROTOCOL framing the Tauri core relays,
// carried over HTTP: POST /api/rpc moves one request frame in and one reply
// frame out (binary payloads intact), /api/events is SSE carrying the host's
// event frames.

import type { HostState } from '@shared/protocol';
import { HostCallError, type Reply, type Transport } from './transport';

// the app may live under a sub-path (fnOS gateway /app/<name>/); boot-bridge
// resolves the base before anything here runs
declare global {
  interface Window { __SPK_BASE__?: string }
}
const api = (p: string) => `${window.__SPK_BASE__ ?? '/'}${p}`;

const RPC_TIMEOUT_DEFAULT_MS = 180_000;

interface AppInfo {
  ok: boolean;
  mode?: string;
  version?: string;
  backend_available?: boolean;
}

function encodeFrame(header: object, payload: Uint8Array | undefined): Uint8Array {
  const h = new TextEncoder().encode(JSON.stringify(header));
  const p = payload ?? new Uint8Array(0);
  const out = new Uint8Array(8 + h.length + p.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, h.length, true);
  dv.setUint32(4, p.length, true);
  out.set(h, 8);
  out.set(p, 8 + h.length);
  return out;
}

export function bridgeTransport(): Transport {
  let nextId = 1;
  const stateListeners = new Set<(s: HostState) => void>();
  const eventListeners = new Set<(e: Record<string, unknown>) => void>();
  let hello: Record<string, unknown> | null = null;
  let readyPromise: Promise<void> | null = null;
  let es: EventSource | null = null;

  function noteState(s: HostState) {
    for (const l of stateListeners) l(s);
  }

  function connectEvents() {
    if (es) return;
    es = new EventSource(api('api/events'));
    es.onmessage = (m) => {
      try {
        const msg = JSON.parse(m.data) as Record<string, unknown>;
        if ('event' in msg) {
          for (const l of eventListeners) l(msg);
          if (msg.event === 'host_down') {
            noteState({ phase: 'failed', reason: 'engine host exited', detail: 'see /api/diagnostics' });
            es?.close();
            es = null;
          }
        }
      } catch {
        /* keep-alive comments never reach onmessage */
      }
    };
    es.onerror = () => {
      // EventSource retries on its own; surface a soft state once.
      noteState({ phase: 'restarting', reason: 'event stream lost', attempt: 1 });
    };
  }

  async function ready(): Promise<void> {
    if (!readyPromise) {
      readyPromise = (async () => {
        const r = await fetch(api('api/hello'));
        if (!r.ok) throw new Error(`bridge /api/hello ${r.status}`);
        const j = (await r.json()) as { ok: boolean; hello: Record<string, unknown> };
        if (!j.ok) throw new Error('bridge /api/hello not ok');
        hello = { ...(j.hello ?? {}), bridge: true };
        noteState({ phase: 'ready', hello: hello as never });
        connectEvents();
      })();
    }
    return readyPromise;
  }

  return {
    kind: 'bridge',
    async request(method, params, opts): Promise<Reply> {
      await ready();
      const id = nextId++;
      const frame = encodeFrame({ id, method, params }, opts?.payload);
      const t0 = performance.now();
      const r = await fetch(api('api/rpc'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: frame.buffer.slice(frame.byteOffset, frame.byteOffset + frame.byteLength) as ArrayBuffer,
        signal: AbortSignal.timeout(opts?.timeoutMs ?? RPC_TIMEOUT_DEFAULT_MS),
      });
      if (!r.ok) {
        let code = 'internal';
        let message = `bridge /api/rpc ${r.status}`;
        try {
          const j = (await r.json()) as { error?: { code: string; message: string } };
          code = j.error?.code ?? code;
          message = j.error?.message ?? message;
        } catch {
          /* non-JSON error */
        }
        throw new HostCallError(method, code, message);
      }
      const buf = new Uint8Array(await r.arrayBuffer());
      if (buf.length < 8) throw new HostCallError(method, 'internal', 'empty reply frame');
      const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
      const hlen = dv.getUint32(0, true);
      const plen = dv.getUint32(4, true);
      const header = JSON.parse(new TextDecoder().decode(buf.subarray(8, 8 + hlen))) as {
        ok: boolean;
        result?: Record<string, unknown>;
        error?: { code: string; message: string };
      };
      if (!header.ok) throw new HostCallError(method, header.error?.code ?? 'internal', header.error?.message ?? 'host error');
      return {
        result: (header.result ?? {}) as Record<string, unknown>,
        payload: buf.subarray(8 + hlen, 8 + hlen + plen),
        // (performance mark kept for parity with the desktop renderer)
        ...(performance.now() - t0 > 0 ? {} : {}),
      };
    },
    async state() {
      try {
        await ready();
        return { phase: 'ready', hello: hello as never };
      } catch (e) {
        return { phase: 'failed', reason: 'bridge unreachable', detail: String(e) };
      }
    },
    onState(cb) {
      stateListeners.add(cb);
      return () => stateListeners.delete(cb);
    },
    onEvent(cb) {
      eventListeners.add(cb);
      void ready().then(() => connectEvents()).catch(() => {});
      return () => eventListeners.delete(cb);
    },
    async restart() {
      await fetch(api('api/host/restart'), { method: 'POST' });
      readyPromise = null;
      es?.close();
      es = null;
      await ready();
      noteState({ phase: 'ready', hello: hello as never });
    },
    async diagnostics() {
      const r = await fetch(api('api/diagnostics'));
      return r.json();
    },
  };
}

export type { AppInfo };
