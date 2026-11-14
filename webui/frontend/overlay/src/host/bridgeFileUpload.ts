// bridgeFileUpload.ts -- move a locally-picked file onto the NAS for rendering.
//
// The browser cannot hand the engine host a filesystem path; the bridge can
// only see NAS-resident files.  So "open from my computer" uploads into the
// data dir's inbox (SPEKTRALAB_FNOS_DATA/inbox), an always-writable root, and
// the upload response's path becomes the session's path everywhere downstream
// (render, export, sidecar).  Chunked so a 200 MB RAW does not need a huge
// single POST.

export interface UploadResult {
  path: string;
  name: string;
  size: number;
}

const CHUNK = 4 * 1024 * 1024;

// (the inbox endpoints live in bridge.py; see its header comment)

export async function uploadToInbox(file: File, onProgress?: (frac: number) => void): Promise<UploadResult> {
  const init = await fetch('/api/fs/upload/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: file.name, size: file.size }),
  });
  if (!init.ok) throw new Error(`upload init failed (${init.status})`);
  const { ok, upload_id, path } = (await init.json()) as { ok: boolean; upload_id: string; path: string };
  if (!ok || !upload_id) throw new Error('upload init refused');

  let offset = 0;
  while (offset < file.size || file.size === 0) {
    const slice = file.slice(offset, Math.min(offset + CHUNK, file.size));
    const buf = new Uint8Array(await slice.arrayBuffer());
    const r = await fetch(`/api/fs/upload/chunk?id=${encodeURIComponent(upload_id)}&offset=${offset}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: buf,
    });
    if (!r.ok) throw new Error(`upload chunk failed (${r.status})`);
    offset += buf.length;
    onProgress?.(file.size ? offset / file.size : 1);
    if (file.size === 0) break;
  }
  const done = await fetch('/api/fs/upload/finish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: upload_id }),
  });
  const j = (await done.json()) as { ok: boolean; path: string };
  if (!done.ok || !j.ok) throw new Error('upload finish failed');
  return { path: j.path ?? path, name: file.name, size: file.size };
}
