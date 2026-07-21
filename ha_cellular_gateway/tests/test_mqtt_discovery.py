from __future__ import annotations

import unittest

from rootfs.app import mqtt_discovery
from rootfs.app.mqtt_discovery import (
    AVAILABILITY_TOPIC,
    STATE_TOPIC,
    build_discovery_payload,
    build_state_payload,
)
from test_support.mqtt_fixtures import STATUS

EXPECTED_COMPONENTS = {
    "gateway_state",
    "health",
    "mobile_connection",
    "active_connection",
    "upstream_pairing_state",
    "downstream_interface",
    "public_ip",
    "upstream_healthy",
    "downstream_present",
    "rules_installed",
    "dnsmasq_running",
}

REMOVED_COMPONENTS = {"enabled"}


class DiscoveryPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = build_discovery_payload()
        self.cmps = self.payload["cmps"]

    def test_device_and_origin(self) -> None:
        self.assertEqual(self.payload["dev"]["name"], "HAOS Mobile WAN")
        self.assertEqual(self.payload["dev"]["identifiers"], ["haos_mobile_wan"])
        self.assertEqual(self.payload["dev"]["manufacturer"], "teh-hippo")
        self.assertEqual(self.payload["o"]["name"], "HAOS Mobile WAN")

    def test_availability_matches_lwt_topic(self) -> None:
        availability = self.payload["availability"][0]
        self.assertEqual(availability["topic"], AVAILABILITY_TOPIC)
        self.assertEqual(availability["payload_available"], "online")
        self.assertEqual(availability["payload_not_available"], "offline")

    def test_every_entity_reproduced(self) -> None:
        self.assertEqual(set(self.cmps), EXPECTED_COMPONENTS | REMOVED_COMPONENTS)

    def test_removed_enabled_entity_is_tombstoned(self) -> None:
        self.assertEqual(self.cmps["enabled"], {"platform": "binary_sensor"})

    def test_components_are_status_only(self) -> None:
        for key, comp in self.cmps.items():
            self.assertIn(comp["platform"], {"sensor", "binary_sensor"}, key)
            self.assertNotIn("command_topic", comp, key)

    def test_platforms_and_unique_ids(self) -> None:
        platforms = {key: comp["platform"] for key, comp in self.cmps.items()}
        self.assertEqual(platforms["gateway_state"], "sensor")
        self.assertEqual(platforms["health"], "sensor")
        self.assertEqual(platforms["mobile_connection"], "sensor")
        self.assertEqual(platforms["active_connection"], "sensor")
        self.assertEqual(platforms["upstream_healthy"], "binary_sensor")
        for key, comp in self.cmps.items():
            if key in REMOVED_COMPONENTS:
                continue
            self.assertEqual(comp["unique_id"], f"haos_mobile_wan_{key}")

    def test_enum_options_and_device_class(self) -> None:
        gateway_state = self.cmps["gateway_state"]
        self.assertEqual(gateway_state["device_class"], "enum")
        self.assertEqual(
            gateway_state["options"],
            [
                "Waiting for iPhone",
                "Waiting for hotspot",
                "Waiting",
                "Waiting for USB device",
                "Connecting",
                "Connected",
                "Error",
            ],
        )
        self.assertEqual(
            self.cmps["health"]["options"],
            ["OK", "Attention needed"],
        )
        self.assertEqual(
            self.cmps["active_connection"]["options"],
            [
                "Wi-Fi hotspot",
                "USB (iPhone)",
                "USB (generic)",
                "Not connected",
            ],
        )
        self.assertEqual(
            self.cmps["mobile_connection"]["options"],
            [
                "Wi-Fi hotspot",
                "USB (iPhone)",
                "USB (iPhone), Wi-Fi fallback",
                "USB (generic)",
                "USB (generic), Wi-Fi fallback",
            ],
        )
        pairing = self.cmps["upstream_pairing_state"]
        self.assertEqual(len(pairing["options"]), 17)
        self.assertIn("Waiting for device", pairing["options"])
        self.assertIn("Waiting for Personal Hotspot", pairing["options"])
        self.assertIn("Waiting for USB tethering", pairing["options"])
        self.assertIn("Ready", pairing["options"])
        self.assertNotIn("waiting_for_device", pairing["options"])

    def test_binary_sensor_device_classes(self) -> None:
        self.assertEqual(self.cmps["upstream_healthy"]["device_class"], "connectivity")
        self.assertEqual(self.cmps["rules_installed"]["device_class"], "running")
        self.assertEqual(self.cmps["dnsmasq_running"]["device_class"], "running")
        self.assertNotIn("device_class", self.cmps["downstream_present"])

    def test_entity_categories_and_enabled_default(self) -> None:
        self.assertEqual(self.cmps["gateway_state"]["entity_category"], "diagnostic")
        self.assertNotIn("enabled_by_default", self.cmps["gateway_state"])
        self.assertNotIn("enabled_by_default", self.cmps["mobile_connection"])
        self.assertNotIn("enabled_by_default", self.cmps["health"])
        self.assertNotIn(
            "enabled_by_default",
            self.cmps["upstream_pairing_state"],
        )
        self.assertNotIn("enabled_by_default", self.cmps["public_ip"])

    def test_health_and_gateway_state_attributes(self) -> None:
        health = self.cmps["health"]
        self.assertEqual(health["json_attributes_topic"], STATE_TOPIC)
        self.assertIn("health_issues", health["json_attributes_template"])
        self.assertIn("networkmanager", health["json_attributes_template"])
        gateway = self.cmps["gateway_state"]
        self.assertEqual(gateway["json_attributes_topic"], STATE_TOPIC)
        self.assertIn("auto_disable_at", gateway["json_attributes_template"])
        self.assertIn("upstream_carrier", gateway["json_attributes_template"])

    def test_state_topic_shared_by_stateful_components(self) -> None:
        for key in ("gateway_state", "upstream_healthy", "dnsmasq_running"):
            self.assertEqual(self.cmps[key]["state_topic"], STATE_TOPIC)


class StatePayloadTests(unittest.TestCase):
    def test_only_known_fields_are_published(self) -> None:
        payload = build_state_payload(dict(STATUS))
        self.assertEqual(set(payload), set(mqtt_discovery.STATE_FIELDS))
        self.assertIsNone(payload["active_connection"])
        self.assertEqual(payload["health"], "healthy")
        self.assertEqual(payload["health_issues"], [])
        self.assertNotIn("ignored_extra_field", payload)
        self.assertNotIn("last_error", payload)
        self.assertNotIn("safety_errors", payload)


if __name__ == "__main__":
    unittest.main()
