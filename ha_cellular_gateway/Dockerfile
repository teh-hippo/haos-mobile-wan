FROM ghcr.io/home-assistant/base:3.24@sha256:58422480a299b16b6ea376c2167463206d430619ed02b40cd687c8bd6875519e

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
