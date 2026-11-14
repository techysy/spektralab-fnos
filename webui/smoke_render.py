#!/usr/bin/env python3
# smoke_render.py -- end-to-end check through the bridge: hello -> open a test
# image -> render (live) -> set_params (print-side) -> reprint -> export.
# The test image must already sit inside an authorized root (upload it with
# the /api/fs/upload/* triple, or bind-mount webui/testdata as /photos).
#
#   python3 webui/smoke_render.py [--base http://127.0.0.1:8080] [path]
import json
import struct
import sys
import urllib.request

BASE = 'http://127.0.0.1:8080'
for i, a in enumerate(sys.argv):
    if a == '--base':
        BASE = sys.argv[i + 1]


def rpc(method, params, payload=b'', timeout=600):
    header = json.dumps({'id': 1, 'method': method, 'params': params}).encode()
    frame = struct.pack('<II', len(header), len(payload)) + header + payload
    r = urllib.request.urlopen(
        urllib.request.Request(BASE + '/api/rpc', frame, {'Content-Type': 'application/octet-stream'}),
        timeout=timeout,
    )
    buf = r.read()
    hl, pl = struct.unpack('<II', buf[:8])
    reply = json.loads(buf[8:8 + hl])
    if not reply.get('ok'):
        raise SystemExit(f'{method} failed: {reply}')
    return reply.get('result', {}), buf[8 + hl:8 + hl + pl]


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else '/photos/smoke.tif'
    if any(a == '--base' for a in sys.argv):
        path = sys.argv[sys.argv.index('--base') + 2] if len(sys.argv) > sys.argv.index('--base') + 2 else path

    hello, _ = rpc('hello', {}, timeout=120)
    b = hello.get('backend', {})
    print(f"hello: device={b.get('device_name')} available={b.get('available')}")
    assert b.get('available'), b.get('error')

    opened, _ = rpc('open', {'path': path}, timeout=600)
    sid = opened['session']
    print(f"open: session={sid} {opened['width']}x{opened['height']} kind={opened.get('kind')}")

    r1, px1 = rpc('render', {'session': sid, 'tier': 'live', 'format': 'rgba8', 'display': 'srgb'}, timeout=900)
    print(f"render live: {r1['image']['width']}x{r1['image']['height']} bytes={len(px1)} timings={r1.get('timings_ms')}")

    rpc('set_params', {'session': sid, 'delta': {'print_exposure': 0.5}}, timeout=120)
    r3, px3 = rpc('render', {'session': sid, 'tier': 'live', 'reprint': True, 'format': 'rgba8', 'display': 'srgb'}, timeout=900)
    print(f"reprint: reprinted={r3.get('reprinted')} negative_cached={r3.get('negative_was_cached')} bytes={len(px3)}")
    assert len(px3) == len(px1)
    assert px3[:2048] != px1[:2048], 'print_exposure delta produced identical pixels -- params did not move'

    exp, _ = rpc('export_image', {'session': sid, 'path': '/data/smoke-export.jpeg', 'format': 'jpeg', 'color_space': 'sRGB', 'overwrite': True}, timeout=900)
    print(f"export: {exp['path']} {exp['width']}x{exp['height']} bytes={exp['bytes']}")
    rpc('close', {'session': sid}, timeout=60)
    print('SMOKE RENDER PASS')
