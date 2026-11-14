#!/usr/bin/env python3
# bridge.py -- SpektraLab fnOS bridge: an HTTP front for the stdio engine host.
#
# The engine host (spektralab-host) speaks the upstream HOST-PROTOCOL on
# stdin/stdout: binary frames of [u32 LE header_len][u32 LE payload_len]
# [JSON header][binary payload], one request at a time on its worker thread
# (cancel / ping / shutdown are answered on the reader thread).
#
# The bridge keeps that framing byte-for-byte over HTTP:
#   POST /api/rpc      request body IS a protocol frame; response body IS one.
#   GET  /api/events   SSE: the host's event frames (progress), one JSON per data line.
#   GET  /api/hello    {ok, hello} -- the host's cached hello (also the frontend's
#                      bridge-detection probe).
# plus the OS-facing calls the Tauri core would have made: file listing,
# sidecars, settings stores -- every photo path clamped to authorized roots
# (fnOS trim API + ACL when running as an fnOS app, env-configured roots
# otherwise).
#
# Only the Python standard library is used: the runtime image already carries
# python3, and an fnOS app should not need a package manager.
#
# Endpoints (all JSON unless noted):
#   GET  /                  static files from www/ (SPA fallback to index.html)
#   GET  /api/hello
#   POST /api/rpc
#   GET  /api/events        (SSE)
#   POST /api/host/restart
#   GET  /api/diagnostics
#   GET  /api/appinfo
#   GET  /api/fs/roots
#   GET  /api/fs/list?path=
#   GET  /api/fs/exists?path=
#   POST /api/fs/mkdir      {path}
#   GET  /api/fs/sidecar?path=
#   PUT  /api/fs/sidecar    {path, sidecar}
#   GET  /api/store/<area>/<name>
#   PUT  /api/store/<area>/<name>
#
# Env:
#   SPEKTRALAB_HOST_BIN     host binary           (default /opt/spektralab/spektralab-host)
#   SPEKTRALAB_RESOURCES    engine resources dir  (default /opt/spektralab/engine)
#   SPEKTRALAB_WWW          static UI dir         (default ./www beside this file)
#   SPEKTRALAB_FNOS_DATA    stores/logs dir       (default ./data beside this file)
#   SPEKTRALAB_PHOTOS_ROOTS authorized photo roots, ';'-separated
#                           (default: none -- only data dir is writable)
#   SPEKTRALAB_FNOS_PORT    HTTP port             (default 8080; 0 = disabled)
#   SPEKTRALAB_FNOS_SOCKET  unix socket path to ALSO listen on (fnOS unified gateway)
#   SPEKTRALAB_FNOS_UID     fallback user uid when no gateway header (default none)
#
# As an fnOS app (trim gateway present + TRIM_API_TOKEN set) the photo roots
# come from TRIM_DATA_ACCESSIBLE_PATHS / the trim backend API, every request's
# user comes from the gateway's X-Trim-Userid header, and listing/reading/
# writing is gated per user through trim.file.checkUserACL.  See fnos_trim.py.

import base64
import json
import os
import re
import secrets
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

IMAGE_EXTENSIONS = {
    # RAW (LibRaw)
    '3fr', 'ari', 'arw', 'bay', 'cr2', 'cr3', 'crw', 'dcr', 'dng', 'erf', 'fff', 'iiq', 'k25', 'kdc', 'mef',
    'mos', 'mrw', 'nef', 'nrw', 'orf', 'pef', 'raf', 'raw', 'rwl', 'sr2', 'srf', 'srw', 'x3f',
    # rasters
    'tif', 'tiff', 'jpg', 'jpeg', 'png',
}

MIME = {
    '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
    '.mjs': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff': 'font/woff',
    '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8', '.webp': 'image/webp',
}

HOST_BIN = os.environ.get('SPEKTRALAB_HOST_BIN', '/opt/spektralab/spektralab-host')
RESOURCES = os.environ.get('SPEKTRALAB_RESOURCES', '/opt/spektralab/engine')
WWW = os.environ.get('SPEKTRALAB_WWW', os.path.join(HERE, 'www'))
DATA_DIR = os.environ.get('SPEKTRALAB_FNOS_DATA', os.path.join(HERE, 'data'))
STORE_DIR = os.path.join(DATA_DIR, 'store')
PORT = int(os.environ.get('SPEKTRALAB_FNOS_PORT', '8080') or '0')
UNIX_SOCKET = os.environ.get('SPEKTRALAB_FNOS_SOCKET', '')
FALLBACK_UID = os.environ.get('SPEKTRALAB_FNOS_UID', '')

# GPU: the engine is Vulkan. With an iGPU passed into the container
# (--device /dev/dri, render/video group), Mesa's ANV enumerates it and the
# host picks it with --device <index> (0-based in the Vulkan device list).
# SPEKTRALAB_DEVICE=0 selects the first; unset means "whatever Vulkan orders
# first" -- on GPU-less boxes that is lavapipe, which is still correct.
DEVICE_INDEX = os.environ.get('SPEKTRALAB_DEVICE', '').strip()


def dri_available():
    return os.path.isdir('/dev/dri') and any(
        f.startswith('renderD') for f in (os.listdir('/dev/dri') if os.path.isdir('/dev/dri') else [])
    )

TRIM_SOCKET = '/var/run/trim_open_gateway_apiscope.socket'
FNOS_MODE = os.path.exists(TRIM_SOCKET) and bool(os.environ.get('TRIM_API_TOKEN'))

trim = None
if FNOS_MODE:
    try:
        import fnos_trim
        trim = fnos_trim.TrimAPI()
    except Exception as e:  # fnOS API down must not take the bridge down
        print(f'bridge: trim API unavailable ({e}); roots fall back to env', file=sys.stderr)
        trim = None


def env_roots():
    raw = os.environ.get('SPEKTRALAB_PHOTOS_ROOTS', '')
    return [os.path.abspath(p) for p in raw.split(';') if p.strip()]


# ----------------------------------------------------------------- host process

class HostDown(Exception):
    pass


class HostProcess:
    """One spektralab-host child; thread-safe framed requests + event fan-out."""

    def __init__(self):
        self.lock = threading.Lock()          # guards spawn/stop and the next two
        self.write_lock = threading.Lock()    # one writer to the child's stdin at a time
        self.pending = {}                     # id -> queue.Queue
        self.subscribers = set()              # SSE queues for event frames
        self.logbuf = []                      # stderr tail for /api/diagnostics
        self.proc = None
        self.next_id = 1
        self.hello = None
        self.spawn()

    # -- lifecycle

    def spawn(self):
        with self.lock:
            self._spawn_locked()

    def _spawn_locked(self):
        env = dict(os.environ)
        env.setdefault('SPEKTRALAB_RESOURCES', RESOURCES)
        cmd = [HOST_BIN, '--resources', RESOURCES, '--log-level', 'info']
        if DEVICE_INDEX != '':
            cmd += ['--device', DEVICE_INDEX]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        self.pending.clear()
        self.hello = None
        threading.Thread(target=self._reader, daemon=True, name='host-stdout').start()
        threading.Thread(target=self._stderr, daemon=True, name='host-stderr').start()
        try:
            self.hello = self.request('hello', {}, timeout_s=60)[0]
        except Exception as e:
            self.note(f'hello after spawn failed: {e}')

    def stop(self):
        with self.lock:
            p, self.proc = self.proc, None
        if p:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def restart(self):
        self.stop()
        self.spawn()
        return {'ok': True, 'hello': self.hello}

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    # -- plumbing

    def note(self, line):
        self.logbuf.append(f'{time.strftime("%H:%M:%S")} {line}')
        del self.logbuf[:-300]

    def _stderr(self):
        p = self.proc
        if not p:
            return
        for raw in p.stderr:
            self.note(raw.decode('utf-8', 'replace').rstrip())

    def _reader(self):
        p = self.proc
        if not p:
            return
        try:
            while True:
                head = p.stdout.read(8)
                if len(head) < 8:
                    break
                hlen, plen = struct.unpack('<II', head)
                header = p.stdout.read(hlen)
                payload = p.stdout.read(plen) if plen else b''
                if len(header) < hlen or (plen and len(payload) < plen):
                    break
                msg = json.loads(header.decode('utf-8'))
                if 'event' in msg:
                    for q in tuple(self.subscribers):
                        q.append(msg)
                else:
                    q = self.pending.pop(msg.get('id'), None)
                    if q is not None:
                        q.put((msg, payload))
        except Exception as e:
            self.note(f'reader died: {e}')
        self.note('host stdout closed')

    def subscribe(self):
        q = []
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    # -- requests

    def request(self, method, params, payload=b'', timeout_s=1800):
        if not self.alive():
            raise HostDown('engine host is not running')
        with self.write_lock:
            if not self.alive():
                raise HostDown('engine host is not running')
            rid = self.next_id
            self.next_id = (self.next_id + 1) % 2**31
            header = json.dumps({'id': rid, 'method': method, 'params': params}, ensure_ascii=False).encode('utf-8')
            from queue import Queue, Empty
            q: Queue = Queue()
            self.pending[rid] = q
            try:
                self.proc.stdin.write(struct.pack('<II', len(header), len(payload)))
                self.proc.stdin.write(header)
                if payload:
                    self.proc.stdin.write(payload)
                self.proc.stdin.flush()
            except Exception as e:
                self.pending.pop(rid, None)
                raise HostDown(f'engine host write failed: {e}')
        try:
            msg, rpayload = q.get(timeout=timeout_s)
        except Empty:
            self.pending.pop(rid, None)
            raise HostDown(f'engine host timeout on {method}')
        if not msg.get('ok'):
            err = msg.get('error') or {}
            raise HostError(method, err.get('code', 'internal'), err.get('message', 'host error'))
        return msg.get('result') or {}, rpayload


class HostError(Exception):
    def __init__(self, method, code, message):
        super().__init__(f'{method}: {code}: {message}')
        self.method = method
        self.code = code
        self.message = message


HOST = None  # set in main()


# ----------------------------------------------------------------- path policy

def user_uid(handler):
    v = handler.headers.get('X-Trim-Userid')
    if v and v.isdigit():
        return int(v)
    return int(FALLBACK_UID) if FALLBACK_UID.isdigit() else None


def is_admin(handler):
    return handler.headers.get('X-Trim-Isadmin', '').lower() == 'true'


def photo_roots():
    """Authorized photo roots, most-specific first: fnOS trim API, else env.

    The bridge's own data dir (upload inbox, exports) is always allowed: it is
    app-controlled storage, not user photo space.
    """
    roots = [os.path.realpath(DATA_DIR)]
    if trim is not None:
        try:
            roots += trim.accessible_roots()
        except Exception as e:
            print(f'bridge: trim roots query failed: {e}', file=sys.stderr)
    roots += env_roots()
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def under_root(path, roots):
    rp = os.path.realpath(path)
    for r in roots:
        rr = os.path.realpath(r)
        if rp == rr or rp.startswith(rr + os.sep):
            return rp
    return None


def check_photo_path(handler, raw, need='read'):
    """Validate a client-supplied photo path; returns the resolved realpath.

    need: 'read' | 'write'.  In fnOS mode also checks the current user's ACL
    (trim.file.checkUserACL) -- a shared grant to the app never overrides the
    user's own permissions.
    """
    roots = photo_roots()
    rp = under_root(raw, roots)
    if not rp:
        raise ApiError(403, 'path is outside the authorized roots')
    if trim is not None and not is_admin(handler):
        uid = user_uid(handler)
        if uid is None:
            raise ApiError(403, 'no user context')
        acl = trim.check_user_acl(uid, rp)
        key = {'read': 'readable', 'write': 'writable'}[need]
        if not acl.get(key):
            raise ApiError(403, f'path is not {key} for this user')
    return rp


def sidecar_path(image_real):
    base, ext = os.path.splitext(image_real)
    return f'{base}.spektra.json' if ext else f'{image_real}.spektra.json'


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ------------------------------------------------------------------- upload inbox
# "Open from my computer": the browser uploads a file into DATA_DIR/inbox
# (always writable, inside the data dir), and the stored path -- an authorized
# root -- flows through open/render/export as any NAS-resident photograph.
# Chunked: init -> chunk* -> finish.

INBOX = os.path.join(DATA_DIR, 'inbox')
uploads = {}          # id -> {'path': partial path, 'size': declared, 'got': bytes, 'name': original}
uploads_lock = threading.Lock()


def _inbox_root():
    os.makedirs(INBOX, exist_ok=True)
    return INBOX


def upload_init(name, size):
    safe = re.sub(r'[^\w.\- ()\[\]]+', '_', os.path.basename(name or 'photo')) or 'photo'
    stem, ext = os.path.splitext(safe)
    ext = ext if ext.lower().lstrip('.') in IMAGE_EXTENSIONS else '.bin'
    uid = f'{time.strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(4)}'
    final = os.path.join(_inbox_root(), f'{stem}_{uid}{ext}')
    partial = final + '.partial'
    with uploads_lock:
        uploads[uid] = {'path': partial, 'final': final, 'size': int(size or 0), 'got': 0, 'name': safe}
    return uid, final


def upload_chunk(uid, offset, data):
    with uploads_lock:
        u = uploads.get(uid)
    if not u:
        raise ApiError(404, 'unknown upload id')
    if int(offset) != u['got']:
        raise ApiError(409, f'offset mismatch: expected {u["got"]}, got {offset}')
    with open(u['path'], 'ab') as f:
        f.write(data)
    u['got'] += len(data)
    return u['got']


def upload_finish(uid):
    with uploads_lock:
        u = uploads.pop(uid, None)
    if not u:
        raise ApiError(404, 'unknown upload id')
    if u['size'] and u['got'] != u['size']:
        raise ApiError(409, f'incomplete upload: {u["got"]}/{u["size"]}')
    os.replace(u['path'], u['final'])
    return u['final']


# ----------------------------------------------------------------- HTTP server

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'spektralab-fnos-bridge'

    def log_message(self, fmt, *args):  # noisy at info level; keep the tail clean
        pass

    # -- helpers

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return b''
        if n > 512 * 2**20:
            raise ApiError(413, 'request body too large')
        return self.rfile.read(n)

    def api(self, fn):
        try:
            return fn()
        except ApiError as e:
            self.send_json({'ok': False, 'error': {'code': 'forbidden' if e.status == 403 else 'bad_request', 'message': e.message}}, e.status)
        except HostError as e:
            self.send_json({'ok': False, 'error': {'code': e.code, 'message': e.message}}, 502)
        except HostDown as e:
            self.send_json({'ok': False, 'error': {'code': 'host_exited', 'message': str(e)}}, 503)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self.send_json({'ok': False, 'error': {'code': 'internal', 'message': str(e)}}, 500)

    # -- dispatch

    def do_GET(self):
        self.api(lambda: self._get())

    def do_POST(self):
        self.api(lambda: self._post())

    def do_PUT(self):
        self.api(lambda: self._put())

    def _get(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        p = u.path
        if p == '/api/hello':
            hello = HOST.hello or {}
            self.send_json({'ok': True, 'mode': 'fnos' if FNOS_MODE else 'standalone', 'hello': hello})
        elif p == '/api/appinfo':
            hello = HOST.hello or {}
            self.send_json({
                'ok': True,
                'version': os.environ.get('SPEKTRALAB_FNOS_VERSION', ''),
                'mode': 'fnos' if FNOS_MODE else 'standalone',
                'data_dir': DATA_DIR,
                'backend_available': bool(hello.get('backend', {}).get('available')),
                'gpu': {
                    'dri_available': dri_available(),
                    'device': DEVICE_INDEX or None,
                    'active_device': hello.get('backend', {}).get('device_name') or None,
                },
            })
        elif p == '/api/fs/roots':
            lang = q.get('lang') or (self.headers.get('Accept-Language') or '')[:8] or 'zh-CN'
            out = []
            for r in photo_roots():
                item = {'path': r, 'name': os.path.basename(r.rstrip('/\\')) or r, 'writable': True}
                if trim is not None:
                    item['semantic'] = trim.convert_path(r, lang)
                out.append(item)
            self.send_json({'ok': True, 'roots': out})
        elif p == '/api/fs/list':
            rp = check_photo_path(self, q.get('path', ''), 'read')
            dirs, images = [], []
            try:
                with os.scandir(rp) as it:
                    for e in it:
                        if e.name.startswith('.'):
                            continue
                        try:
                            st = e.stat()
                        except OSError:
                            continue
                        if e.is_dir(follow_symlinks=False):
                            dirs.append({'path': e.path, 'name': e.name})
                        elif e.is_file(follow_symlinks=False) and e.name.rsplit('.', 1)[-1].lower() in IMAGE_EXTENSIONS:
                            images.append({'path': e.path, 'name': e.name, 'size': st.st_size, 'mtime_ms': int(st.st_mtime * 1000)})
            except PermissionError:
                raise ApiError(403, 'directory is not readable')
            except FileNotFoundError:
                raise ApiError(404, 'directory does not exist')
            dirs.sort(key=lambda d: d['name'].lower())
            images.sort(key=lambda i: i['name'].lower())
            self.send_json({'ok': True, 'path': rp, 'dirs': dirs, 'images': images})
        elif p == '/api/fs/exists':
            rp = check_photo_path(self, q.get('path', ''), 'read')
            self.send_json({'ok': True, 'exists': os.path.exists(rp)})
        elif p == '/api/fs/sidecar':
            img = check_photo_path(self, q.get('path', ''), 'read')
            sp = sidecar_path(img)
            if os.path.isfile(sp):
                try:
                    with open(sp, encoding='utf-8') as f:
                        self.send_json({'ok': True, 'sidecar': json.load(f), 'sidecar_path': sp})
                except Exception:
                    self.send_json({'ok': True, 'sidecar': None, 'sidecar_path': sp})
            else:
                self.send_json({'ok': True, 'sidecar': None, 'sidecar_path': sp})
        elif p == '/api/events':
            self._sse()
        elif p == '/api/diagnostics':
            self.send_json({'ok': True, 'alive': HOST.alive(), 'log': list(HOST.logbuf[-120:])})
        elif p.startswith('/api/store/'):
            parts = p.split('/')[3:]
            if len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', x) for x in parts):
                raise ApiError(400, 'bad store key')
            fp = os.path.join(STORE_DIR, *parts + ['.json'])
            if os.path.isfile(fp):
                try:
                    with open(fp, encoding='utf-8') as f:
                        self.send_json({'ok': True, 'value': json.load(f)})
                except Exception:
                    self.send_json({'ok': True, 'value': None})
            else:
                self.send_json({'ok': True, 'value': None})
        elif not p.startswith('/api/'):
            self._static(p)
        else:
            self.send_json({'ok': False, 'error': {'code': 'not_found', 'message': p}}, 404)

    def _post(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        if p == '/api/rpc':
            self._rpc()
        elif p == '/api/host/restart':
            self.send_json(HOST.restart())
        elif p == '/api/fs/upload/init':
            body = json.loads(self.read_body() or b'{}')
            uid, final = upload_init(body.get('name', 'photo'), body.get('size', 0))
            self.send_json({'ok': True, 'upload_id': uid, 'path': final})
        elif p == '/api/fs/upload/chunk':
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            data = self.read_body()
            got = upload_chunk(qs.get('id', ''), int(qs.get('offset', '0') or 0), data)
            self.send_json({'ok': True, 'received': got})
        elif p == '/api/fs/upload/finish':
            body = json.loads(self.read_body() or b'{}')
            final = upload_finish(body.get('id', ''))
            self.send_json({'ok': True, 'path': final})
        elif p == '/api/fs/mkdir':
            body = json.loads(self.read_body() or b'{}')
            rp = check_photo_path(self, body.get('path', ''), 'write')
            os.makedirs(rp, exist_ok=True)
            self.send_json({'ok': True, 'path': rp})
        elif p.startswith('/api/store/'):
            parts = p.split('/')[3:]
            if len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', x) for x in parts):
                raise ApiError(400, 'bad store key')
            body = json.loads(self.read_body() or b'null')
            d = os.path.join(STORE_DIR, parts[0])
            os.makedirs(d, exist_ok=True)
            fp = os.path.join(d, parts[1] + '.json')
            tmp = fp + '.partial'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(body, f, ensure_ascii=False)
            os.replace(tmp, fp)
            self.send_json({'ok': True})
        else:
            self.send_json({'ok': False, 'error': {'code': 'not_found', 'message': p}}, 404)

    def _put(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/fs/sidecar':
            body = json.loads(self.read_body() or b'{}')
            img = check_photo_path(self, body.get('path', ''), 'read')
            sp = sidecar_path(img)
            if trim is not None and not is_admin(self):
                uid = user_uid(self)
                acl = trim.check_user_acl(uid, os.path.dirname(img))
                if not acl.get('writable'):
                    raise ApiError(403, 'directory is not writable for this user')
            data = json.dumps(body.get('sidecar'), ensure_ascii=False, indent=2).encode('utf-8')
            tmp = f'{sp}.partial-{os.getpid()}'
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, sp)
            self.send_json({'ok': True, 'sidecar_path': sp})
        else:
            self.send_json({'ok': False, 'error': {'code': 'not_found', 'message': u.path}}, 404)

    # -- the protocol pipe

    def _rpc(self):
        body = self.read_body()
        if len(body) < 8:
            raise ApiError(400, 'body is not a protocol frame')
        hlen, plen = struct.unpack('<II', body[:8])
        if len(body) < 8 + hlen + plen:
            raise ApiError(400, 'truncated protocol frame')
        try:
            header = json.loads(body[8:8 + hlen].decode('utf-8'))
        except Exception:
            raise ApiError(400, 'bad frame header')
        method = header.get('method', '')
        params = header.get('params') or {}
        payload = body[8 + hlen:8 + hlen + plen]

        self._gate_method(method, params, payload)
        result, rpayload = HOST.request(method, params, payload)
        rheader = json.dumps({'id': header.get('id'), 'ok': True, 'result': result}, ensure_ascii=False).encode('utf-8')
        out = struct.pack('<II', len(rheader), len(rpayload)) + rheader + rpayload
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(out)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(out)

    def _gate_method(self, method, params, payload):
        """Clamp every path the protocol can touch to the authorized roots."""
        if method in ('open', 'probe', 'thumbnail', 'redecode'):
            check_photo_path(self, str(params.get('path', '')), 'read')
        if method == 'write_image':
            check_photo_path(self, str(params.get('path', '')), 'write')
            sp = params.get('source_path')
            if sp:
                check_photo_path(self, str(sp), 'read')
        if method in ('export_image', 'export_cube', 'export_di'):
            check_photo_path(self, str(params.get('path', '')), 'write')

    # -- events

    def _sse(self):
        q = HOST.subscribe()
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b': bridge\n\n')
            self.wfile.flush()
            last = time.time()
            while True:
                if q:
                    msg = q.pop(0)
                    data = json.dumps(msg, ensure_ascii=False).encode('utf-8')
                    self.wfile.write(b'data: ' + data + b'\n\n')
                    self.wfile.flush()
                    last = time.time()
                elif time.time() - last > 15:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                    last = time.time()
                else:
                    time.sleep(0.15)
                if not HOST.alive() and not q:
                    self.wfile.write(b'data: {"event":"host_down"}\n\n')
                    self.wfile.flush()
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            HOST.unsubscribe(q)

    # -- static

    def _static(self, p):
        if p == '/':
            p = '/index.html'
        fp = os.path.realpath(os.path.join(WWW, p.lstrip('/')))
        if not fp.startswith(os.path.realpath(WWW) + os.sep) and fp != os.path.realpath(WWW):
            self.send_json({'ok': False, 'error': {'code': 'forbidden'}}, 403)
            return
        if not os.path.isfile(fp):
            if p.startswith('/api/') or '.' in os.path.basename(p):
                self.send_json({'ok': False, 'error': {'code': 'not_found'}}, 404)
                return
            fp = os.path.join(WWW, 'index.html')  # SPA fallback
            if not os.path.isfile(fp):
                self.send_json({'ok': False, 'error': {'code': 'not_found', 'message': 'www/ is not built'}}, 404)
                return
        ext = os.path.splitext(fp)[1].lower()
        with open(fp, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', MIME.get(ext, 'application/octet-stream'))
        self.send_header('Content-Length', str(len(data)))
        if ext in ('.html', '.js', '.css', '.json'):
            self.send_header('Cache-Control', 'no-cache')
        else:
            self.send_header('Cache-Control', 'max-age=3600')
        self.end_headers()
        self.wfile.write(data)


class UnixHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        os.chmod(self.server_address, 0o660)


class TcpHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global HOST
    os.makedirs(STORE_DIR, exist_ok=True)
    HOST = HostProcess()
    servers = []
    if PORT:
        servers.append(TcpHTTPServer(('0.0.0.0', PORT), Handler))
        print(f'bridge: http on 0.0.0.0:{PORT} (fnos={FNOS_MODE})')
    if UNIX_SOCKET:
        try:
            os.unlink(UNIX_SOCKET)
        except FileNotFoundError:
            pass
        os.makedirs(os.path.dirname(UNIX_SOCKET) or '.', exist_ok=True)
        servers.append(UnixHTTPServer(UNIX_SOCKET, Handler))
        print(f'bridge: unix socket {UNIX_SOCKET} (fnos={FNOS_MODE})')
    if not servers:
        print('bridge: nothing to listen on (set SPEKTRALAB_FNOS_PORT or SPEKTRALAB_FNOS_SOCKET)', file=sys.stderr)
        sys.exit(1)
    try:
        for s in servers[1:]:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        HOST.stop()


if __name__ == '__main__':
    main()
