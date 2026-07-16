FROM ghcr.io/home-assistant/base:3.24

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/

RUN apk add --no-cache \
    curl \
    dnsmasq \
    iproute2 \
    iptables \
    libimobiledevice-progs \
    networkmanager-cli \
    python3 \
    usbmuxd \
    && command -v idevice_id >/dev/null \
    && command -v idevicepair >/dev/null \
    && command -v nmcli >/dev/null

COPY rootfs /

WORKDIR /

RUN mkdir -p /data /var/lib \
    && ln -snf /data/lockdown /var/lib/lockdown \
    && chmod 0755 \
    /app/main.py

ENTRYPOINT ["/usr/bin/python3", "/app/main.py"]
CMD []
