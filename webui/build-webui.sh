#!/usr/bin/env bash
# build-webui.sh -- the WebUI deliverable, end to end, on any Docker-capable
# host (extends build.sh, which must have produced the engine bundle first):
#
#   bash webui/build-webui.sh
#
# Steps:
#   1. frontend: upstream desktop + overlay -> webui/frontend/dist (build-webui.sh)
#   2. image:    webui/docker/Dockerfile.webui (engine bundle + bridge + www)
#   3. smoke:    hello over the bridge's /api/rpc + static UI + fs API
#   4. dist/:    webui image tar.gz (fnOS docker load / compose), SHA256SUMS
#
# Outputs (dist/):
#   spektralab-fnos-webui-<version>.tar.gz
#   SHA256SUMS.webui
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
cd "$root"
version="$(tr -d ' \r\n' < VERSION)"
image_tag="webui-${SPEKTRALAB_FNOS_TAG:-$version}"
engine_bundle="$root/upstream/build/host-linux-x64"
dist="$root/dist"
MSYS_NO_PATHCONV="${MSYS_NO_PATHCONV:-1}"
export MSYS_NO_PATHCONV

[ -f "$engine_bundle/spektralab-host" ] || { echo "FAIL: engine bundle missing ($engine_bundle) -- run bash build.sh first" >&2; exit 1; }

# 1) frontend
bash "$here/frontend/build-webui.sh"

# 2) image (bridge context: bridge sources; engine context: staged host bundle)
# MSYS converts POSIX paths for native Windows tools; docker's -f needs the
# Windows form, and the build contexts need POSIX-mapped Windows paths too.
dockerfile="$here/docker/Dockerfile.webui"
if command -v cygpath > /dev/null 2>&1; then
  dockerfile="$(cygpath -w "$dockerfile")"
  engine_bundle="$(cygpath -w "$engine_bundle")"
  webui_ctx="$(cygpath -w "$here")"
  root_ctx="$(cygpath -w "$root")"
else
  webui_ctx="$here"
  root_ctx="$root"
fi
docker build -t "spektralab-fnos:$image_tag" \
  -f "$dockerfile" \
  --build-context "engine=$engine_bundle" \
  --build-context "webui=$webui_ctx" \
  "$root_ctx"

# 3) smoke: the bridge answers hello through /api/rpc, serves the UI, lists roots
smoke_id="$(docker run -d --rm -p 18080:8080 \
  -e SPEKTRALAB_FNOS_PORT=8080 \
  "spektralab-fnos:$image_tag")"
trap 'docker rm -f "$smoke_id" > /dev/null 2>&1 || true' EXIT
sleep 4
python - "$smoke_id" <<'PY'
import json, socket, struct, sys, urllib.request
tid = sys.argv[1]
base = 'http://127.0.0.1:18080'

# hello via the bridge RPC (protocol frame in, protocol frame out)
header = json.dumps({'id': 1, 'method': 'hello', 'params': {}}).encode()
frame = struct.pack('<II', len(header), 0) + header
r = urllib.request.urlopen(urllib.request.Request(base + '/api/rpc', frame, {'Content-Type': 'application/octet-stream'}), timeout=60)
buf = r.read()
hlen, plen = struct.unpack('<II', buf[:8])
reply = json.loads(buf[8:8 + hlen])
assert reply['ok'] is True, reply
backend = reply['result'].get('backend', {})
assert backend.get('available') is True, f"backend unavailable: {backend.get('error')}"
print(f"smoke: hello ok, device={backend.get('device_name')}, methods={len(reply['result'].get('methods') or [])}")

# static UI
ui = urllib.request.urlopen(base + '/', timeout=10)
assert b'<div id="root">' in ui.read(), 'index.html is the built app'

# fs API (empty roots: the env default /photos mount does not exist yet)
roots = json.loads(urllib.request.urlopen(base + '/api/fs/roots', timeout=10).read())
assert roots['ok'] is True
print(f"smoke: ui ok, fs ok, roots={len(roots['roots'])}, mode={json.loads(urllib.request.urlopen(base + '/api/appinfo').read())['mode']}")
print('WEBUI SMOKE PASS')
PY
docker rm -f "$smoke_id" > /dev/null 2>&1 || true
trap - EXIT

# 4) artifacts
mkdir -p "$dist"
docker save "spektralab-fnos:$image_tag" | gzip > "$dist/spektralab-fnos-webui-$version.tar.gz"
( cd "$dist" && sha256sum "spektralab-fnos-webui-$version.tar.gz" > SHA256SUMS.webui )
echo "==> WebUI artifacts in $dist:"
ls -la "$dist" | grep webui
cat "$dist/SHA256SUMS.webui"
