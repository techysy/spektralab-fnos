#!/usr/bin/env bash
# pack-fpk.sh -- stage the NATIVE fnOS app payload and (when fnpack is
# available) build the .fpk.  The app runs natively: engine host + engine
# resources + bridge + www land under app/ and fnOS runs them directly as the
# package user -- no Docker anywhere.
#
# Payload sources:
#   app/spektralab-host, app/engine/, app/licenses/   <- the staged engine
#       bundle (SPEKTRALAB_HOST_BUNDLE, default upstream/build/host-linux-x64;
#       produced by build.sh)
#   app/bridge.py, app/fnos_trim.py, app/healthcheck.py, app/www/  <- webui/
#       bridge + the built frontend (SPEKTRALAB_WWW_DIST, default
#       webui/frontend/dist; produced by webui/build-webui.sh)
#   manifest, config/, cmd/, app/ui/, wizard/                          <- webui/fpk/
#
# FPK_VARIANT=tab|window picks the desktop entry (window = unified-gateway
# iframe, the default; tab = browser new tab over the service port).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
version="$(tr -d ' \r\n' < "$root/VERSION")"
appname="$(grep -E '^appname=' "$here/fpk/manifest" | cut -d= -f2 | tr -d ' \r')"
stage="$here/fpk-dist/$appname"
dist="$root/dist"
host_bundle="${SPEKTRALAB_HOST_BUNDLE:-$root/upstream/build/host-linux-x64}"
www_dist="${SPEKTRALAB_WWW_DIST:-$here/frontend/dist}"

rm -rf "$here/fpk-dist"
mkdir -p "$stage"

# the fnOS app skeleton (manifest, config/, cmd/, app/ui/, wizard/)
cp -r "$here/fpk/." "$stage/"
rm -rf "$stage/dist"
# Desktop-entry variant: window (fnOS unified-gateway iframe, the default
# config) or tab (browser new tab over the service port).  Two fpk files ship
# per release; same appname and data dir, install one over the other to
# switch.  FPK_VARIANT=tab selects the tab entry.
variant="${FPK_VARIANT:-window}"
case "$variant" in
  tab)
    cp "$here/fpk/app/ui/config.tab" "$stage/app/ui/config"
    # strip the template's own 【…】 prefix first, then add the variant one --
    # sed-appending to a desc that already carries 【原生版】 produced
    # 【窗口版·原生】【原生版】... in the shipped fpk (0.3.0)
    sed -i -E 's/^desc=【[^】]*】/desc=/' "$stage/manifest"
    sed -i 's/^desc=/desc=【标签页版】/' "$stage/manifest"
    ;;
  window)
    sed -i -E 's/^desc=【[^】]*】/desc=/' "$stage/manifest"
    sed -i 's/^desc=/desc=【窗口版·原生】/' "$stage/manifest"
    ;;
  *) echo "unknown FPK_VARIANT '$variant'" >&2; exit 1 ;;
esac
# wizard/install must be a NON-EMPTY JSON form file: the app center's wizard
# parser nil-derefs on an empty array (code 10111). webui/fpk/wizard/install
# carries one tips step; keep it as-is here, never overwrite it.

# the native payload lives under app/ -- fnpack packs app/ into app.tgz and
# the framework applies it at the app root (APP_DIR), so app/spektralab-host
# lands at ${APP_DIR}/spektralab-host etc.
[ -f "$host_bundle/spektralab-host" ] || {
  echo "FAIL: engine bundle missing ($host_bundle) -- run build.sh first" >&2
  exit 1
}
cp "$host_bundle/spektralab-host" "$stage/app/"
cp -r "$host_bundle/engine" "$stage/app/engine"
[ -d "$host_bundle/licenses" ] && cp -r "$host_bundle/licenses" "$stage/app/licenses"

# bridge + built frontend
cp "$here/bridge/bridge.py" "$here/bridge/fnos_trim.py" "$here/bridge/healthcheck.py" "$stage/app/"
[ -f "$www_dist/index.html" ] || {
  echo "FAIL: frontend missing ($www_dist) -- run webui/frontend/build-webui.sh first" >&2
  exit 1
}
cp -r "$www_dist" "$stage/app/www"

echo "==> staged native fpk project at $stage"
du -sh "$stage"

if command -v fnpack > /dev/null 2>&1; then
  ( cd "$stage" && fnpack build )
  echo "==> fpk at $stage/../"
  ls -lh "$here/fpk-dist/$appname"/*.fpk 2>/dev/null || true
else
  echo "==> staged native fpk project at $stage (fnpack not on PATH)"
  echo "    pack it with fnpack:  cd $stage && fnpack build"
fi
