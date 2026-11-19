#!/usr/bin/env bash
# build.sh -- the spektralab-fnos deliverable, end to end, on any
# Docker-capable host. Self-contained: clones upstream SpektraLab at the
# pinned commit, builds the engine host in a debian:12 container (fnOS's
# glibc baseline), verifies, assembles the runtime image, smokes it, and
# packages dist/.
#
#   bash build.sh [--skip-build]
#
# Overridables (env):
#   SPEKTRALAB_UPSTREAM   git URL to clone (default: the upstream GitHub repo)
#   SPEKTRALAB_FNOS_TAG   image tag (default: VERSION file's value)
#
# Outputs (dist/):
#   spektralab-fnos-<version>.tar.gz   docker image (docker load -i ...)
#   spektralab-fnos-host-linux-x64-<version>.tar.gz   bare host bundle
#   SHA256SUMS
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
version="$(tr -d ' \r\n' < VERSION)"
image_tag="${SPEKTRALAB_FNOS_TAG:-$version}"
upstream_url="${SPEKTRALAB_UPSTREAM:-https://github.com/JamesQiu2005/SpektraLab.git}"
pin="$(tr -d ' \r\n' < UPSTREAM_PIN)"
dist="$here/dist"
MSYS_NO_PATHCONV="${MSYS_NO_PATHCONV:-1}"
export MSYS_NO_PATHCONV

# 1) upstream source at the pinned commit
if [ ! -d upstream/.git ]; then
  echo "==> cloning upstream ($upstream_url)"
  git -c core.autocrlf=false clone --quiet "$upstream_url" upstream
fi
actual="$(git -C upstream rev-parse HEAD)"
if [ "$actual" != "$pin" ]; then
  echo "==> upstream is at $actual, checking out pin $pin"
  git -C upstream fetch --quiet origin "$pin" 2>/dev/null || true
  git -C upstream checkout --quiet --detach "$pin"
  actual="$(git -C upstream rev-parse HEAD)"
  [ "$actual" = "$pin" ] || { echo "FAIL: cannot reach pin $pin" >&2; exit 1; }
fi
echo "==> upstream pinned at ${pin:0:12} (commit date: $(git -C upstream log -1 --format=%cs))"

# 2) dependency seed (optional; the container re-verifies everything)
mkdir -p upstream/build/deps
if [ -f deps-seed/LibRaw-0.22.2.zip ] && [ ! -f upstream/build/deps/LibRaw-0.22.2.zip ]; then
  cp deps-seed/LibRaw-0.22.2.zip upstream/build/deps/
  echo "==> seeded LibRaw 0.22.2 archive from deps-seed/"
fi

# 3) build + test in debian:12
if [ "${1:-}" != "--skip-build" ]; then
  docker run --rm -v "$here/upstream":/src -w /src debian:12 bash -c "
    set -e
    sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends \
      build-essential cmake ninja-build glslang-tools python3 git \
      mesa-vulkan-drivers vulkan-tools libvulkan1 ca-certificates binutils
    # Upstream blobs carry CRLF (committed from Windows): on Linux, bash
    # reads them as 'pipefail\r'. Normalize every script before running.
    find engine -name '*.sh' -exec sed -i 's/\r\$//' {} +
    # Upstream 2.4.x Linux link regression: pipeline.cpp's node_edr calls
    # Pipeline::overscan_params_block, defined in overscan.cpp -- compiled
    # only in the APPLE branch of the spektralab_pipeline target. The
    # non-Apple engine stops linking (undefined reference). Overscan is
    # refused on this path (set_overscan_frame fails, overscan_.valid stays
    # false), so node_edr never reaches the call: a symbol-only stub keeps
    # the linker happy. Idempotent; auto-skips once upstream fixes it.
    if grep -q 'overscan_params_block' engine/src/pipeline/pipeline.cpp \\
       && ! grep -q 'void Pipeline::overscan_params_block' engine/src/pipeline/windows_unported.cpp \\
       && ! grep -q 'void Pipeline::overscan_params_block' engine/src/pipeline/overscan.cpp; then
      cat >> engine/src/pipeline/windows_unported.cpp <<'STUB'

// dsh-fnos style local patch (2026-11-19): 2.4.x upstream Linux link
// regression -- node_edr (pipeline.cpp) references
// Pipeline::overscan_params_block, defined in overscan.cpp, which the
// spektralab_pipeline target compiles only on APPLE. Overscan is refused on
// the non-Apple path (set_overscan_frame fails, overscan_.valid stays
// false), so node_edr never reaches the call; the stub exists for the
// linker. Drop once upstream compiles overscan.cpp off macOS too.
void Pipeline::overscan_params_block(std::vector<float>& P) const {
    P.clear();
}
STUB
      echo "overscan_params_block stub appended to windows_unported.cpp"
    fi
    bash engine/build-linux.sh --test
    # glibc gate: fnOS is Debian 12 (glibc 2.36); refuse anything higher.
    max=\$(readelf -V build/host-linux-x64/spektralab-host \
      | grep -oE 'GLIBC_[0-9.]+' | sort -Vu | tail -1)
    echo \"highest GLIBC symbol requirement: \$max\"
    maxnum=\$(printf '%s' \"\$max\" | sed 's/GLIBC_//' | awk -F. '{printf \"%d%03d\", \$1, \$2}')
    if [ \"\$maxnum\" -gt 2036 ]; then
      echo \"FAIL: glibc gate (fnOS = 2.36, binary needs \$max)\" >&2
      exit 1
    fi
    echo 'glibc gate passed'
  "
fi

# 4) runtime image + in-image protocol smoke
docker build -t "spektralab-fnos:$image_tag" -f docker/Dockerfile upstream/build/host-linux-x64
docker run -i --rm --entrypoint python3 \
  -v "$here/docker/smoke_hello.py":/opt/smoke.py:ro \
  "spektralab-fnos:$image_tag" \
  /opt/smoke.py --host /opt/spektralab/spektralab-host --resources /opt/spektralab/engine

# 5) artifacts
# naming: spektralab-fnos-<version>-docker-headless.tar.gz (docker image)
# (the bare host bundle ships only inside the fpk / payload artifact -- not
# published to the Release: fnOS users have no use for it without the bridge)
mkdir -p "$dist"
docker save "spektralab-fnos:$image_tag" | gzip > "$dist/spektralab-fnos-$version-docker-headless.tar.gz"
cp docker/Dockerfile "$dist/Dockerfile.txt"
( cd "$dist" && sha256sum "spektralab-fnos-$version-docker-headless.tar.gz" > SHA256SUMS )
echo "==> fnOS artifacts in $dist:"
ls -la "$dist"
cat "$dist/SHA256SUMS"
