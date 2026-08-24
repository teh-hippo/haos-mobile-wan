ARG ADDON_BASE_IMAGE=ghcr.io/home-assistant/base:3.24@sha256:93ef607824e3f27e868f11b10938283a98bf880ed57bcf8eaa81c6c2d521f6f5
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
COPY integration/networkmanager/live_constants.py /integration/live_constants.py
COPY integration/networkmanager/live_tracing.py /integration/live_tracing.py
COPY integration/networkmanager/live_dbus.py /integration/live_dbus.py
COPY integration/networkmanager/live_link.py /integration/live_link.py
COPY integration/networkmanager/live_scenario_inert.py /integration/live_scenario_inert.py
COPY integration/networkmanager/live_scenario_production.py /integration/live_scenario_production.py
COPY integration/networkmanager/live_scenario_custody.py /integration/live_scenario_custody.py
COPY integration/networkmanager/live_scenario_wifi_secret.py /integration/live_scenario_wifi_secret.py
COPY integration/networkmanager/test_live_nm.py /integration/test_live_nm.py

RUN chmod 0755 /integration/entrypoint.sh

ENTRYPOINT ["/integration/entrypoint.sh"]
