// bridgePlatform.ts -- the Platform surface (platform/index.ts) when the app
// runs behind the spektralab-fnos bridge: NAS directories replace the Tauri
// file dialogs (a built-in picker over the bridge's fs API), exports land
// beside the originals or under a picked root, sidecars/stores go through
// the bridge.  All URLs are built on the page base (the app may live under a
// sub-path behind the fnOS unified gateway).

import { baseName, type AppPaths, type FileEntry, type Platform } from './index';
import { uploadToInbox } from '../host/bridgeFileUpload';

declare global {
  interface Window { __SPK_BASE__?: string }
}
const base = () => window.__SPK_BASE__ ?? '/';
const url = (p: string) => `${base()}${p}`;

type DirListing = { ok: boolean; path: string; dirs: { path: string; name: string }[]; images: FileEntry[] };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url(path), init);
  const j = (await r.json()) as { ok: boolean; error?: { message?: string } } & T;
  if (!r.ok || !j.ok) throw new Error(j.error?.message ?? `${path} failed (${r.status})`);
  return j;
}

// -- the in-app folder picker: a small browser dialog over the bridge fs API.
//    The DOM is built imperatively; the host page's stylesheet does not know
//    these classes.

const IMG_EXT = /\.(3fr|ari|arw|bay|cr2|cr3|crw|dcr|dng|erf|fff|iiq|k25|kdc|mef|mos|mrw|nef|nrw|orf|pef|raf|raw|rwl|sr2|srf|srw|x3f|tiff?|jpe?g|png)$/i;

export function bridgePlatform(): Platform {
  return {
    kind: 'bridge',
    listImages: async (dir) => {
      const j = await api<DirListing>(`fs/list?path=${encodeURIComponent(dir)}`);
      return j.images;
    },
    expandPaths: async (paths) => {
      const out: FileEntry[] = [];
      for (const p of paths) {
        if (IMG_EXT.test(p)) {
          out.push({ path: p, name: baseName(p), size: 0, mtime_ms: 0 });
        } else {
          const j = await api<DirListing>(`fs/list?path=${encodeURIComponent(p)}`);
          out.push(...j.images);
        }
      }
      return out;
    },
    sidecarLoad: async (image) => {
      const j = await api<{ sidecar: unknown | null }>(`fs/sidecar?path=${encodeURIComponent(image)}`);
      return j.sidecar;
    },
    sidecarSave: async (image, sidecar) => {
      const j = await api<{ sidecar_path: string }>('fs/sidecar', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: image, sidecar }),
      });
      return j.sidecar_path;
    },
    sidecarPath: async (image) => {
      const j = await api<{ sidecar_path: string }>(`fs/sidecar?path=${encodeURIComponent(image)}`);
      return j.sidecar_path;
    },
    storeRead: async (area, name) => {
      const j = await api<{ value: unknown | null }>(`store/${encodeURIComponent(area)}/${encodeURIComponent(name)}`);
      return j.value;
    },
    storeWrite: async (area, name, value) => {
      await api(`store/${encodeURIComponent(area)}/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value),
      });
    },
    takeLaunchPaths: async () => {
      const q = new URLSearchParams(location.search).get('path');
      return q ? [q] : [];
    },
    pathExists: async (path) => {
      const j = await api<{ exists: boolean }>(`fs/exists?path=${encodeURIComponent(path)}`);
      return j.exists;
    },
    ensureDir: async (path) => {
      await api('fs/mkdir', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) });
    },
    appPaths: async (): Promise<AppPaths> => {
      const j = await api<{ mode: string; data_dir: string; version: string }>('appinfo');
      return {
        appData: j.data_dir,
        sidecars: 'beside each photograph (.spektra.json)',
        logs: 'bridge /api/diagnostics',
        home: j.mode === 'fnos' ? '(fnOS)' : '(bridge)',
        pictures: '(authorized roots)',
        os: j.mode === 'fnos' ? 'fnOS' : 'bridge',
        version: j.version || 'webui',
      };
    },
    pickFolder: (title) => pickFolderDialog(title),
    pickFiles: async (title) => pickFileDialog(title),
    pickSave: async (_title, defaultPath) => defaultPath,
    reveal: async () => {},
    openUrl: async (url_) => void window.open(url_, '_blank'),
    message: async (title, text) => window.alert(`${title}\n\n${text}`),
    confirm: async (title, text) => window.confirm(`${title}\n\n${text}`),
    onOpenPaths: (cb) => {
      const h = (e: MessageEvent) => {
        const d = e.data as { type?: string; paths?: string[] };
        if (d?.type === 'spektralab:open' && Array.isArray(d.paths)) cb(d.paths);
      };
      window.addEventListener('message', h);
      return () => window.removeEventListener('message', h);
    },
    onDrop: (cb) => {
      // Browser drops carry File objects, not paths: open the drop dialog.
      const over = (e: DragEvent) => e.preventDefault();
      const drop = (e: DragEvent) => {
        e.preventDefault();
        const files = Array.from(e.dataTransfer?.files ?? []).filter((f) => IMG_EXT.test(f.name));
        if (files.length) cb(['__upload__']);
        if (files.length) queueUploads(files);
      };
      window.addEventListener('dragover', over);
      window.addEventListener('drop', drop);
      return () => {
        window.removeEventListener('dragover', over);
        window.removeEventListener('drop', drop);
      };
    },
    setTitle: async (t) => void (document.title = t),
    log: (level, m) => console[level === 'error' ? 'error' : level === 'warn' ? 'warn' : 'info'](m),
    toggleFullscreen: async () => {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    },
  };
}

// ---------------------------------------------------------------- upload queue

let pendingUploads: File[] = [];
const uploadListeners = new Set<(files: File[]) => void>();

/** Files queued by drag-drop; the Filmstrip's upload affordance reads these. */
export function queueUploads(files: File[]) {
  pendingUploads = [...pendingUploads, ...files];
  for (const l of uploadListeners) l(pendingUploads);
}
export function takePendingUploads(): File[] {
  const f = pendingUploads;
  pendingUploads = [];
  return f;
}
export function onPendingUploads(cb: (files: File[]) => void): () => void {
  uploadListeners.add(cb);
  return () => uploadListeners.delete(cb);
}

// ------------------------------------------------------------------- pickers

export async function pickFolderDialog(title: string): Promise<string | null> {
  const roots = (await api<{ roots: { path: string; name: string; semantic?: string }[] }>('fs/roots')).roots;
  if (!roots.length) {
    window.alert(`${title}\n\nNo authorized photo roots. Ask the administrator to grant one (fnOS app authorization) or set SPEKTRALAB_PHOTOS_ROOTS.`);
    return null;
  }
  return browseDialog(title, roots.map((r) => ({ path: r.path, name: r.semantic ?? r.name })), 'folder');
}

export async function pickFileDialog(title: string): Promise<string[]> {
  // Local files: upload to the inbox and return their NAS paths.
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.3fr,.ari,.arw,.bay,.cr2,.cr3,.crw,.dcr,.dng,.erf,.fff,.iiq,.k25,.kdc,.mef,.mos,.mrw,.nef,.nrw,.orf,.pef,.raf,.raw,.rwl,.sr2,.srf,.srw,.x3f,.tif,.tiff,.jpg,.jpeg,.png';
  const chosen = await new Promise<File[]>((res) => {
    input.onchange = () => res(Array.from(input.files ?? []));
    input.click();
  });
  if (!chosen.length) return [];
  const paths: string[] = [];
  for (const f of chosen) {
    const r = await uploadToInbox(f);
    paths.push(r.path);
  }
  return paths;
}

function browseDialog(title: string, roots: { path: string; name: string }[], mode: 'folder' | 'file'): Promise<string | null> {
  return new Promise((res) => {
    const wrap = document.createElement('div');
    wrap.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:99999';
    const box = document.createElement('div');
    box.style.cssText = 'background:var(--bg,#1c1c1e);color:var(--fg,#eee);border-radius:10px;min-width:420px;max-width:640px;max-height:70vh;display:flex;flex-direction:column;padding:14px;box-shadow:0 10px 40px rgba(0,0,0,.5)';
    const head = document.createElement('div');
    head.textContent = title;
    head.style.cssText = 'font-weight:600;margin-bottom:10px';
    const list = document.createElement('div');
    list.style.cssText = 'flex:1;overflow:auto;border:1px solid rgba(255,255,255,.12);border-radius:6px';
    const foot = document.createElement('div');
    foot.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;margin-top:10px';
    let cur = '';
    const stack: { path: string; name: string }[] = [];

    async function show(path: string | null, label?: string) {
      list.textContent = '';
      if (path === null) {
        for (const r of roots) addRow(r.path, r.name, true);
        cur = '';
        return;
      }
      cur = path;
      const j = (await fetch(url(`fs/list?path=${encodeURIComponent(path)}`)).then((r) => r.json())) as DirListing & { error?: { message: string } };
      if (!j.ok) {
        const err = document.createElement('div');
        err.textContent = j.error?.message ?? 'cannot read';
        err.style.cssText = 'padding:10px;opacity:.7';
        list.appendChild(err);
        return;
      }
      if (stack.length) {
        const up = document.createElement('div');
        up.textContent = '↗ ..';
        up.style.cssText = rowCss;
        up.onclick = () => {
          stack.pop();
          const prev = stack[stack.length - 1];
          show(prev ? prev.path : null, prev?.name);
        };
        list.appendChild(up);
      }
      for (const d of j.dirs) addRow(d.path, d.name, true);
      if (mode === 'folder') {
        const pick = document.createElement('div');
        pick.textContent = `✔ ${label ?? cur}`;
        pick.style.cssText = rowCss + 'opacity:.85';
        pick.onclick = () => done(cur);
        list.appendChild(pick);
      } else {
        for (const im of j.images) addRow(im.path, im.name, false, () => done(im.path));
      }
    }

    function addRow(path: string, name: string, isDir: boolean, onOpen?: () => void) {
      const el = document.createElement('div');
      el.textContent = (isDir ? '📁 ' : '🖼 ') + name;
      el.style.cssText = rowCss;
      el.onclick = () => {
        if (onOpen) return onOpen();
        stack.push({ path: cur, name });
        void show(path, name);
      };
      list.appendChild(el);
    }

    function done(path: string | null) {
      wrap.remove();
      res(path);
    }
    const cancel = document.createElement('button');
    cancel.textContent = 'Cancel';
    cancel.onclick = () => done(null);
    const ok = document.createElement('button');
    ok.textContent = mode === 'folder' ? 'Choose this folder' : 'Close';
    ok.onclick = () => done(mode === 'folder' ? cur : null);
    for (const b of [cancel, ok]) {
      b.style.cssText = 'padding:4px 14px;border-radius:6px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06);color:inherit;cursor:pointer';
    }
    foot.append(cancel, ok);
    box.append(head, list, foot);
    wrap.appendChild(box);
    document.body.appendChild(wrap);
    void show(null);
  });
}

const rowCss = 'padding:6px 10px;cursor:pointer;border-radius:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
