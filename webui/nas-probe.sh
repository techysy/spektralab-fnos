#!/usr/bin/env bash
# nas-probe.sh -- GPU sanity check on the NAS: does the engine see the iGPU?
set -e
python3 - <<'PY'
import json, struct
h = json.dumps({"id": 1, "method": "hello", "params": {}}).encode()
open("/tmp/spk-hello.bin", "wb").write(struct.pack("<II", len(h), 0) + h)
PY
echo "hello frame ready; probing engine with /dev/dri passthrough:"
docker run -i --rm --device /dev/dri --entrypoint sh \
  -v /tmp/spk-hello.bin:/tmp/hello.bin:ro \
  spektralab-fnos:webui-0.1.0 \
  -c "cat /tmp/hello.bin | /opt/spektralab/spektralab-host --resources /opt/spektralab/engine 2>/dev/null" | head -c 700
echo
echo "--- without passthrough (lavapipe baseline):"
docker run -i --rm --entrypoint sh \
  -v /tmp/spk-hello.bin:/tmp/hello.bin:ro \
  spektralab-fnos:webui-0.1.0 \
  -c "cat /tmp/hello.bin | /opt/spektralab/spektralab-host --resources /opt/spektralab/engine 2>/dev/null" | head -c 400
echo
