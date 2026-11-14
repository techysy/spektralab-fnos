# fnos_trim.py -- client for the fnOS (trim) application open API, backend side.
#
# The open API is POST http://localhost/api/v1/trimapp reached ONLY through the
# unix socket /var/run/trim_open_gateway_apiscope.socket, authenticated with the
# TRIM_API_TOKEN the system injects into the app's environment.  See
# https://developer.fnnas.com/api/overview/ (调用方式 / 授权与文件).
#
# Used by the bridge only when both the socket and the token exist (fnOS app
# mode).  Every call is a plain HTTP POST over a hand-rolled socket request --
# no third-party dependencies.

import json
import os

SOCKET = '/var/run/trim_open_gateway_apiscope.socket'


class TrimError(Exception):
    def __init__(self, code, message):
        super().__init__(f'trim api error {code}: {message}')
        self.code = code
        self.message = message


class TrimAPI:
    def __init__(self, socket_path=SOCKET, token=None, app_name=None):
        self.socket_path = socket_path
        self.token = token if token is not None else os.environ.get('TRIM_API_TOKEN', '')
        self.app_name = app_name or os.environ.get('TRIM_APPNAME', 'spektralab-fnos')
        self._req_id = 0

    # -- transport

    def call(self, req, data=None):
        self._req_id += 1
        body = json.dumps({
            'reqId': str(self._req_id),
            'req': req,
            'appName': self.app_name,
            'data': data or {},
        }).encode('utf-8')
        head = (
            'POST /api/v1/trimapp HTTP/1.1\r\n'
            f'Host: localhost\r\n'
            f'Content-Type: application/json\r\n'
            f'Content-Length: {len(body)}\r\n'
            f'Authorization: Bearer {self.token}\r\n'
            f'Connection: close\r\n\r\n'
        ).encode('ascii')
        import socket as _s
        s = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
        s.settimeout(15)
        try:
            s.connect(self.socket_path)
            s.sendall(head + body)
            chunks = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        finally:
            s.close()
        raw = b''.join(chunks)
        sep = raw.find(b'\r\n\r\n')
        if sep < 0:
            raise TrimError(-1, 'no HTTP response from trim gateway')
        payload = raw[sep + 4:]
        # A length-delimited response may arrive as one chunk; a connection-close
        # one is already complete.  Either way the body is JSON.
        try:
            reply = json.loads(payload.decode('utf-8'))
        except Exception:
            # chunked transfer: de-chunk before parsing
            text = payload.decode('utf-8', 'replace')
            out = []
            while True:
                eol = text.find('\r\n')
                if eol < 0:
                    break
                try:
                    n = int(text[:eol].split(b';')[0] if isinstance(text[:eol], bytes) else text[:eol].split(';')[0], 16)
                except ValueError:
                    break
                out.append(text[eol + 2:eol + 2 + n])
                text = text[eol + 2 + n + 2:]
            reply = json.loads(''.join(out) or '{}')
        code = reply.get('code')
        if code != 0:
            raise TrimError(code, reply.get('msg') or 'trim api call failed')
        return reply.get('data')

    # -- the file capabilities the bridge needs
    #    (scope trim.file.sharedAccess / trim.file.userAccess / trim.file.userAcl / trim.file.path)

    def shared_roots(self):
        d = self.call('trim.file.getSharedAccessibleFolders')
        return list(d.get('paths') or [])

    def user_roots(self, uid):
        d = self.call('trim.file.getUserAccessibleFolders', {'uid': uid})
        return list(d.get('paths') or [])

    def check_user_acl(self, uid, path):
        d = self.call('trim.file.checkUserACL', {'uid': uid, 'path': path})
        items = d if isinstance(d, list) else []
        for it in items:
            if it.get('path') == path:
                return {'readable': bool(it.get('readable')), 'writable': bool(it.get('writable')), 'deletable': bool(it.get('deletable'))}
        return {'readable': False, 'writable': False, 'deletable': False}

    def convert_path(self, path, language='zh-CN'):
        try:
            d = self.call('trim.file.convertPath', {'path': [path], 'language': language})
            for it in d.get('result') or []:
                if it.get('path') == path:
                    return it.get('semanticPath') or path
        except Exception:
            pass
        return path

    # -- bridge policy

    def accessible_roots(self):
        """Photo roots the app may touch: shared grants + every known user's grants.

        The bridge serves several fnOS users (the gateway sends each request's
        uid), so the union is kept for path validation; per-user visibility is
        enforced with checkUserACL at request time, which is the pattern the
        authorization docs prescribe.
        """
        roots = []
        seen = set()
        for p in self.shared_roots():
            if p not in seen:
                seen.add(p)
                roots.append(p)
        for uid in self.known_uids():
            try:
                for p in self.user_roots(uid):
                    if p not in seen:
                        seen.add(p)
                        roots.append(p)
            except Exception:
                continue
        env = [os.path.abspath(p) for p in os.environ.get('SPEKTRALAB_PHOTOS_ROOTS', '').split(';') if p.strip()]
        for p in env:
            if p not in seen:
                seen.add(p)
                roots.append(p)
        return roots

    def known_uids(self):
        """The uid to query user grants for.  The app user's own uid is the one
        identity the backend can rely on; other users' grants arrive through the
        per-request ACL check instead."""
        uid = os.environ.get('TRIM_UID')
        return [int(uid)] if uid and uid.isdigit() else []
