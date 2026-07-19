#!/usr/bin/env bash
set -euo pipefail

: "${QEMU_OVERLAY:?}"
: "${QEMU_SEED:?}"
: "${QEMU_SSH_PORT:?}"
: "${QEMU_SERIAL_LOG:?}"
: "${QEMU_STDERR_LOG:?}"

exec qemu-system-x86_64 \
  -name haos-mobile-wan-wifi-lab \
  -machine accel=kvm \
  -cpu host \
  -smp 4 \
  -m 4096 \
  -display none \
  -monitor none \
  -serial "file:${QEMU_SERIAL_LOG}" \
  -drive "if=virtio,format=qcow2,file=${QEMU_OVERLAY}" \
  -drive "if=virtio,format=raw,readonly=on,file=${QEMU_SEED}" \
  -netdev "user,id=mgmt,hostfwd=tcp:127.0.0.1:${QEMU_SSH_PORT}-:22" \
  -device virtio-net-pci,netdev=mgmt \
  -netdev user,id=usbwan,net=10.42.0.0/24,dhcpstart=10.42.0.15 \
  -device qemu-xhci,id=xhci \
  -device usb-net,id=generic-usb,netdev=usbwan,bus=xhci.0 \
  2>"${QEMU_STDERR_LOG}"
