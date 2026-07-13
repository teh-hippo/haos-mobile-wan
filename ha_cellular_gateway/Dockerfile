FROM ghcr.io/home-assistant/aarch64-base:3.22

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

ENV PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache \
    curl \
    dnsmasq \
    iproute2 \
    iptables \
    python3

COPY rootfs /

RUN chmod 0755 \
    /app/main.py \
    /etc/services.d/ha-cellular-gateway/run
