#!/usr/bin/env python3
"""One-roundtrip hello over the host protocol (HOST-PROTOCOL.md §1).

Reads one request line's JSON from argv-less stdin usage is not supported;
instead it dials the host as a subprocess with --resources, sends `hello`,
prints the parsed result as JSON, and exits 0 only when the frame roundtrips.

    python3 smoke_hello.py --host /opt/spektralab/spektralab-host \
        --resources /opt/spektralab/engine
"""
import json
import struct
import subprocess
import sys

args = sys.argv[1:]
try:
    host = args[args.index("--host") + 1]
    resources = args[args.index("--resources") + 1]
except (ValueError, IndexError):
    sys.exit("usage: smoke_hello.py --host <exe> --resources <dir>")

proc = subprocess.Popen(
    [host, "--resources", resources],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
)


def send(obj, payload=b""):
    header = json.dumps(obj, separators=(",", ":")).encode()
    proc.stdin.write(struct.pack("<II", len(header), len(payload)))
    proc.stdin.write(header + payload)
    proc.stdin.flush()


def recv():
    raw = proc.stdout.read(8)
    if len(raw) != 8:
        sys.exit("no frame header; host died early")
    hlen, plen = struct.unpack("<II", raw)
    return json.loads(proc.stdout.read(hlen)), proc.stdout.read(plen)


send({"id": 1, "method": "hello", "params": {}})
header, _ = recv()
proc.stdin.close()
proc.wait(timeout=30)

if not header.get("ok"):
    sys.exit(f"hello failed: {header.get('error')}")
result = header["result"]
print(json.dumps({
    "protocol": result.get("protocol"),
    "host_version": result.get("host_version"),
    "backend": result.get("backend"),
    "methods": len(result.get("methods", [])),
}, ensure_ascii=False))
sys.exit(0)
