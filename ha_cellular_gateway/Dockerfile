FROM ghcr.io/home-assistant/base:3.24@sha256:8fde4170393bdf7a121ea4d6e34b417e1d0b90125948459f9f9f70cdf5d77c16

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/

RUN apk upgrade --no-cache \
    && apk add --no-cache \
    curl \
    dnsmasq \
    iproute2 \
    iptables \
    libimobiledevice-progs \
    networkmanager-cli \
    py3-dbus \
    py3-paho-mqtt \
    python3 \
    usbmuxd \
    && command -v idevice_id >/dev/null \
    && command -v idevicepair >/dev/null \
    && command -v nmcli >/dev/null \
    && python3 -c "import paho.mqtt.client" \
    && python3 -c "import dbus" \
    && rm -f /usr/bin/tempio

COPY rootfs /

WORKDIR /

RUN mkdir -p /data /var/lib \
    && ln -snf /data/lockdown /var/lib/lockdown \
    && chmod 0755 \
    /app/main.py

ENTRYPOINT ["/usr/bin/python3", "/app/main.py"]
CMD []
