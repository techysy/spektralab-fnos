#!/usr/bin/env bash
# build-webui.sh -- the WebUI frontend bundle, from the upstream Tauri frontend
# with a thin overlay (no UI rewrite):
#
#   1. copy upstream desktop/ -> webui/frontend/app (gitignored, build scratch)
#   2. apply the overlay patches (main.tsx boot gate, platform/host injection,
#      Tauri imports stripped from the patched files only)
#   3. `npm ci` with the upstream lockfile, then `vite build` -> webui/frontend/dist
#
# The overlay principle: never edit upstream UI components; add new modules and
# patch only the seams (main.tsx, platform/index.ts, host/client.ts, package.json
# build hooks).  Upstream stays the source of truth for everything visual.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
desktop="$root/upstream/desktop"
app="$here/app"
overlay="$here/overlay"

if [ ! -d "$desktop/src" ]; then
  echo "FAIL: upstream desktop not found at $desktop (run build.sh first or clone the upstream pin)" >&2
  exit 1
fi

echo "==> staging upstream desktop -> frontend/app"
rm -rf "$app"
mkdir -p "$app"
cp -r "$desktop"/. "$app"/
rm -rf "$app/src-tauri" "$app/dist" "$app/node_modules" 2>/dev/null || true
# the mock host stays: browserShim imports it and the vite build resolves it

# Windows-native python receives the MSYS path form; give it a Windows one.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) app="$(cygpath -w "$app")" ;;
esac

echo "==> applying overlay"
cp "$overlay/src/boot-bridge.ts" "$app/src/boot-bridge.ts"
cp "$overlay/src/host/bridgeTransport.ts" "$app/src/host/bridgeTransport.ts"
cp "$overlay/src/host/bridgeFileUpload.ts" "$app/src/host/bridgeFileUpload.ts"
cp "$overlay/src/platform/bridgePlatform.ts" "$app/src/platform/bridgePlatform.ts"

# main.tsx: import the bridge gate FIRST so the transport/platform factories see it
python - "$app" <<'PY'
import re, sys, io
app = sys.argv[1]

def patch(path, subs):
    p = app + '/' + path
    s = io.open(p, encoding='utf-8').read()
    for old, new, count in subs:
        if old not in s:
            raise SystemExit(f'patch failed ({path}): pattern not found: {old[:60]!r}')
        s = s.replace(old, new) if count == -1 else s.replace(old, new, count)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print(f'    patched {path}')

# 1) main.tsx -- boot the bridge probe before anything reads platform()
patch('src/main.tsx', [
    ("import { StrictMode } from 'react';",
     "import './boot-bridge';\nimport { StrictMode } from 'react';", 1),
])

# 2) host/transport.ts -- allow the 'bridge' transport kind
patch('src/host/transport.ts', [
    ("readonly kind: 'tauri' | 'browser';",
     "readonly kind: 'tauri' | 'browser' | 'bridge';", 1),
])

# 3) host/client.ts -- pick the bridge transport when the page is bridge-served
patch('src/host/client.ts', [
    ("import { browserTransport } from './browserShim';",
     "import { browserTransport } from './browserShim';\nimport { bridgeTransport } from './bridgeTransport';\n\ndeclare global {\n  interface Window { __SPK_BRIDGE__?: boolean }\n}", 1),
    ("export function host(): Host {\n  if (!instance) instance = new Host(inTauri() ? tauriTransport() : browserTransport());\n  return instance;\n}",
     "export function host(): Host {\n  if (!instance) instance = new Host(inTauri() ? tauriTransport() : (window.__SPK_BRIDGE__ ? bridgeTransport() : browserTransport()));\n  return instance;\n}", 1),
])

# 4) platform/index.ts -- same branch for the OS surface
patch('src/platform/index.ts', [
    ("import { browserPlatform } from './browser';",
     "import { browserPlatform } from './browser';\nimport { bridgePlatform } from './bridgePlatform';\n\ndeclare global {\n  interface Window { __SPK_BRIDGE__?: boolean }\n}", 1),
    ("readonly kind: 'tauri' | 'browser';",
     "readonly kind: 'tauri' | 'browser' | 'bridge';", 1),
    ("export function platform(): Platform {\n  if (!instance) instance = inTauri() ? tauriPlatform() : browserPlatform();\n  return instance;\n}",
     "export function platform(): Platform {\n  if (!instance) instance = inTauri() ? tauriPlatform() : (window.__SPK_BRIDGE__ ? bridgePlatform() : browserPlatform());\n  return instance;\n}", 1),
])

# 5) package.json -- vite-only build (no tauri predev asset copy: the bridge
#    serves StockCatalog.json from the engine resources instead)
patch('package.json', [
    ('"predev:web": "node scripts/copy-assets.mjs",',
     '"predev:web": "node scripts/copy-assets.mjs",\n    "build:fnos": "vite build --outDir ../../bridge/www --emptyOutDir",', 1),
])

print('overlay applied')
PY

echo "==> npm ci (upstream lockfile)"
cd "$app"
npm ci --no-audit --no-fund 2>&1 | tail -2

echo "==> assets from engine resources (one source of truth)"
mkdir -p public/assets
# StockCatalog + film covers come from the upstream mac resources; licenses from desktop
res="$root/upstream/modern_UI/Spektrafilm/Spektrafilm/Resources"
node scripts/copy-assets.mjs 2>/dev/null || {
  cp "$res/StockCatalog.json" public/assets/
  cp -r "$res/FilmCovers" public/assets/FilmCovers
  mkdir -p public/assets/licenses
  for f in "$res"/Licenses/*.txt; do cp "$f" public/assets/licenses/; done
}

echo "==> vite build"
npx vite build --base ./ --outDir "$here/dist" --emptyOutDir

echo "==> frontend bundle at $here/dist"
ls -la "$here/dist" | head -8
