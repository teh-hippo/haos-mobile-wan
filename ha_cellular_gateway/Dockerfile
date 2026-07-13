ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:3.22
FROM ${BUILD_FROM}

RUN apk add --no-cache \
    conntrack-tools \
    curl \
    dnsmasq \
    iproute2 \
    iptables \
    python3

COPY rootfs /

RUN chmod 0755 \
    /app/main.py \
    /etc/services.d/ha-cellular-gateway/run
