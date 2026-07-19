ARG ADDON_BASE_IMAGE=ghcr.io/home-assistant/base:3.24@sha256:94ff231402a5e7ad2a82e261ad5fa4ffae7d7bb095c3febb2edbdf309c9b6aca
FROM ${ADDON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/

RUN apk add --no-cache \
    dbus \
    dnsmasq \
    iproute2 \
    networkmanager \
    networkmanager-cli \
    py3-dbus \
    python3

COPY rootfs /
COPY integration/networkmanager/nm.conf /etc/NetworkManager/NetworkManager.conf
COPY integration/networkmanager/entrypoint.sh /integration/entrypoint.sh
COPY integration/networkmanager/nmcli_harness.py /integration/nmcli_harness.py
COPY integration/networkmanager/test_live_nm.py /integration/test_live_nm.py

RUN chmod 0755 /integration/entrypoint.sh

ENTRYPOINT ["/integration/entrypoint.sh"]
