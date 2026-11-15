import json, struct, time, urllib.request, sys

BASE = 'http://127.0.0.1:8777'
PATH = sys.argv[1] if len(sys.argv) > 1 else '/photos/约拍/2017/新都桥老实人摄影/A7M2 yu_shiyang/合照/DSC03283.ARW'


def rpc(method, params, payload=b'', timeout=900):
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
probe, _ = rpc('probe', {'path': PATH}, timeout=300)
md = probe.get('metadata', {})
print('probe: {}x{} kind={} camera={} lens={}'.format(probe['width'], probe['height'], probe['kind'], md.get('make') + ' ' + (md.get('model') or ''), md.get('lens')))

opened, _ = rpc('open', {'path': PATH}, timeout=900)
sid = opened['session']
print('open: {}x{} kind={} wb_as_shot={} timings={} wall={:.1f}s'.format(opened['width'], opened['height'], opened.get('kind'), opened.get('metadata', {}).get('as_shot'), opened.get('timings_ms'), time.time() - t0))

t1 = time.time()
r1, px = rpc('render', {'session': sid, 'tier': 'live', 'format': 'rgba8', 'display': 'srgb'}, timeout=900)
print('render live: {}x{} bytes={} timings={} wall={:.1f}s'.format(r1['image']['width'], r1['image']['height'], len(px), r1.get('timings_ms'), time.time() - t1))

t2 = time.time()
r2, px2 = rpc('render', {'session': sid, 'tier': 'preview', 'format': 'rgba8', 'display': 'srgb'}, timeout=900)
print('render preview: {}x{} timings={} wall={:.1f}s'.format(r2['image']['width'], r2['image']['height'], r2.get('timings_ms'), time.time() - t2))

t3 = time.time()
r3, px3 = rpc('render', {'session': sid, 'tier': 'full', 'format': 'rgba8', 'display': 'srgb'}, timeout=1800)
print('render full: {}x{} timings={} wall={:.1f}s'.format(r3['image']['width'], r3['image']['height'], r3.get('timings_ms'), time.time() - t3))

exp, _ = rpc('export_image', {'session': sid, 'path': '/data/arw-export.tiff16', 'format': 'tiff16', 'color_space': 'prophoto', 'overwrite': True}, timeout=1800)
print('export: {} {}x{} {} bytes'.format(exp['path'], exp['width'], exp['height'], exp['bytes']))

rpc('close', {'session': sid})
print('RAW RENDER PASS')
