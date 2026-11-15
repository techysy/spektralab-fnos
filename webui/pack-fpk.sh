#!/usr/bin/env bash
# pack-fpk.sh -- assemble the fnOS app package (fpk) layout next to the image.
#
# fnpack (https://developer.fnnas.com/docs/cli/fnpack/) validates and packs a
# project directory: manifest, config/{privilege,resource}, cmd/*, wizard/,
# app/{ui,docker}.  This script stages webui/fpk plus the built WebUI image
# tar into webui/fpk-dist/{appname}/ and (when fnpack is on PATH) runs
# `fnpack build`; otherwise it prints the layout for manual packing on a
# machine that has fnpack.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
version="$(tr -d ' \r\n' < "$root/VERSION")"
stage="$here/fpk-dist/spektralab-fnos"
dist="$root/dist"

rm -rf "$here/fpk-dist"
mkdir -p "$stage"
cp -r "$here/fpk/." "$stage/"
# Desktop-entry variant: window (fnOS unified-gateway iframe, the default
# config) or tab (browser new tab over the service port).  Two fpk files ship
# per release; same appname and data dir, install one over the other to
# switch.  FPK_VARIANT=tab selects the tab entry.
variant="${FPK_VARIANT:-window}"
case "$variant" in
  tab)
    cp "$here/fpk/app/ui/config.tab" "$stage/app/ui/config"
    sed -i 's/^desc=/desc=【标签页版】/' "$stage/manifest"
    ;;
  window)
    sed -i 's/^desc=/desc=【窗口版】/' "$stage/manifest"
    ;;
  *) echo "unknown FPK_VARIANT '$variant'" >&2; exit 1 ;;
esac
# wizard/install must be a NON-EMPTY JSON form file: the app center's wizard
# parser nil-derefs on an empty array (code 10111). webui/fpk/wizard/install
# carries one tips step; keep it as-is here, never overwrite it.

# the docker image travels inside the package (fnOS loads it in
# install_callback; a registry pull is the alternative once published)
img="$dist/spektralab-fnos-webui-$version.tar.gz"
[ -f "$img" ] || { echo "FAIL: $img missing -- run webui/build-webui.sh first" >&2; exit 1; }
cp "$img" "$stage/app/docker/spektralab-fnos.tar.gz"

# the wizard stays empty for now (no install-time questions yet)


if command -v fnpack > /dev/null 2>&1; then
  (cd "$stage" && fnpack build)
  echo "==> fpk at $stage/../"
  ls -la "$here/fpk-dist"
else
  echo "==> staged fpk project at $stage (fnpack not on PATH)"
  echo "    pack it with fnpack:  cd $stage && fnpack build"
fi
