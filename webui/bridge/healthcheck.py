#!/usr/bin/env python3
# healthcheck.py -- compose health probe: hit the bridge's /api/hello through
# whatever listener is configured (gateway unix socket, else TCP port).
import http.client
import os
import socket

conn = http.client.HTTPConnection('localhost', timeout=5)
sock_path = os.environ.get('SPEKTRALAB_FNOS_SOCKET', '')
if sock_path:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(sock_path)
    conn.sock = s
else:
    conn.host = '127.0.0.1'
    conn.port = int(os.environ.get('SPEKTRALAB_FNOS_PORT', '8080'))

conn.request('GET', '/api/hello')
resp = conn.getresponse()
resp.read()
raise SystemExit(0 if resp.status == 200 else 1)
