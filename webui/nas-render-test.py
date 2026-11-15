import json, struct, time, urllib.request

BASE = 'http://127.0.0.1:8777'


def rpc(method, params, payload=b'', timeout=600):
    header = json.dumps({'id': 1, 'method': method, 'params': params}).encode()
    frame = struct.pack('<II', len(header), len(payload)) + header + payload
    r = urllib.request.urlopen(urllib.request.Request(BASE + '/api/rpc', frame, {'Content-Type': 'application/octet-stream'}), timeout=timeout)
    buf = r.read()
    hl, pl = struct.unpack('<II', buf[:8])
    reply = json.loads(buf[8:8 + hl])
    if not reply.get('ok'):
        raise SystemExit(method + ' FAILED: ' + json.dumps(reply))
    return reply.get('result', {}), buf[8 + hl:8 + hl + pl]


hello, _ = rpc('hello', {})
print('device:', hello['backend']['device_name'])
t0 = time.time()
opened, _ = rpc('open', {'path': '/photos/6.28 6.29/IMG_1598.jpg'}, timeout=600)
sid = opened['session']
w, h = opened['width'], opened['height']
print('open: {}x{} timings={} total={:.1f}s'.format(w, h, opened.get('timings_ms'), time.time() - t0))
t1 = time.time()
r1, px = rpc('render', {'session': sid, 'tier': 'live', 'format': 'rgba8', 'display': 'srgb'}, timeout=900)
print('render live: {}x{} bytes={} timings={} wall={:.1f}s'.format(r1['image']['width'], r1['image']['height'], len(px), r1.get('timings_ms'), time.time() - t1))
t2 = time.time()
r2, px2 = rpc('render', {'session': sid, 'tier': 'preview', 'format': 'rgba8', 'display': 'srgb'}, timeout=900)
print('render preview: {}x{} timings={} wall={:.1f}s'.format(r2['image']['width'], r2['image']['height'], r2.get('timings_ms'), time.time() - t2))
rpc('close', {'session': sid})
print('GPU RENDER PASS')
