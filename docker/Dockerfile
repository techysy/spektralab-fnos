# fnOS runtime image for the SpektraLab engine host.
#
# spektralab-host is a headless stdio engine (binary-frame JSON-RPC, see
# upstream desktop/HOST-PROTOCOL.md). The image carries everything needed to
# render on a GPU-less NAS: Mesa's lavapipe (software Vulkan) from the distro
# matching the builder's glibc baseline (debian:12, glibc 2.36 -- fnOS's own
# baseline).
#
# Build (from the repository root; the context IS the staged bundle):
#   docker build -t spektralab-fnos:<tag> -f docker/Dockerfile build/host-linux-x64
# Run:
#   docker run -i --rm spektralab-fnos:<tag>
# The host speaks the protocol in upstream desktop/HOST-PROTOCOL.md on
# stdin/stdout.
FROM debian:12

RUN echo 'deb https://mirrors.ustc.edu.cn/debian bookworm main' > /etc/apt/sources.list \
 && echo 'deb https://mirrors.ustc.edu.cn/debian bookworm-updates main' >> /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        libvulkan1 mesa-vulkan-drivers python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY ./ /opt/spektralab/

ENV PATH="/opt/spektralab:${PATH}" \
    SPEKTRALAB_RESOURCES=/opt/spektralab/engine

WORKDIR /opt/spektralab
ENTRYPOINT ["/opt/spektralab/spektralab-host"]
CMD ["--resources", "/opt/spektralab/engine"]
