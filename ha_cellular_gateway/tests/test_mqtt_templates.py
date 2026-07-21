from __future__ import annotations

import asyncio
import unittest

from rootfs.app.mqtt_discovery import build_discovery_payload, build_state_payload
from test_support.mqtt_fixtures import STATUS

try:
    from jinja2 import Environment

    _JINJA: Environment | None = Environment()
except ImportError:
    _JINJA = None

_HAS_JINJA = _JINJA is not None

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.template import Template
except ImportError:
    HomeAssistant = None
    Template = None

_HAS_HOME_ASSISTANT = HomeAssistant is not None and Template is not None


def _render(template: str, value_json: dict) -> str:
    assert _JINJA is not None
    return _JINJA.from_string(template).render(value_json=value_json)


class FriendlyLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cmps = build_discovery_payload()["cmps"]

    def test_relabelled_names(self) -> None:
        self.assertEqual(self.cmps["upstream_healthy"]["name"], "Internet available")
        self.assertEqual(self.cmps["upstream_healthy"]["device_class"], "connectivity")
        self.assertEqual(self.cmps["active_connection"]["name"], "Connected via")
        self.assertEqual(self.cmps["gateway_state"]["name"], "Gateway state")
        self.assertEqual(self.cmps["mobile_connection"]["name"], "Connection method")
        self.assertEqual(self.cmps["health"]["name"], "Health")

    def test_pairing_template_embeds_friendly_mapping(self) -> None:
        template = self.cmps["upstream_pairing_state"]["value_template"]
        self.assertIn("'waiting_for_device': 'Waiting for device'", template)
        self.assertIn("'daemon_failed': 'Pairing helper failed'", template)
        self.assertIn(".get(value_json.upstream_pairing_state, 'Not active')", template)

    def test_mobile_connection_template_embeds_internal_to_label(self) -> None:
        template = self.cmps["mobile_connection"]["value_template"]
        self.assertIn(
            "'iphone_usb_wifi_fallback': 'USB (iPhone), Wi-Fi fallback'", template
        )
        self.assertIn(".get(value_json.mobile_connection,", template)

    def test_public_ip_not_connected_fallback(self) -> None:
        self.assertEqual(
            self.cmps["public_ip"]["value_template"],
            "{{ value_json.public_ip if value_json.public_ip else 'Not connected' }}",
        )

    def test_downstream_interface_not_present_fallback(self) -> None:
        self.assertEqual(
            self.cmps["downstream_interface"]["value_template"],
            "{{ value_json.downstream_interface if value_json.downstream_interface else 'Not present' }}",
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_enum_templates_render_friendly_values(self) -> None:
        pairing = self.cmps["upstream_pairing_state"]["value_template"]
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": "waiting_for_device"}),
            "Waiting for device",
        )
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": "daemon_failed"}),
            "Pairing helper failed",
        )
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": "waiting_for_hotspot"}),
            "Waiting for Personal Hotspot",
        )
        self.assertEqual(
            _render(pairing, {"upstream_pairing_state": None}), "Not active"
        )
        gateway = self.cmps["gateway_state"]["value_template"]
        self.assertEqual(
            _render(
                gateway,
                {"state": "connected", "mobile_connection": "iphone_usb"},
            ),
            "Connected",
        )
        self.assertEqual(
            _render(
                gateway,
                {"state": "waiting", "mobile_connection": "iphone_usb"},
            ),
            "Waiting for iPhone",
        )
        self.assertEqual(
            _render(
                gateway,
                {"state": "waiting", "mobile_connection": "wifi_hotspot"},
            ),
            "Waiting for hotspot",
        )
        self.assertEqual(
            _render(
                gateway,
                {
                    "state": "waiting",
                    "mobile_connection": "iphone_usb_wifi_fallback",
                },
            ),
            "Waiting",
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_mobile_connection_renders_internal_to_label(self) -> None:
        template = self.cmps["mobile_connection"]["value_template"]
        self.assertEqual(
            _render(template, {"mobile_connection": "iphone_usb_wifi_fallback"}),
            "USB (iPhone), Wi-Fi fallback",
        )
        self.assertEqual(
            _render(template, {"mobile_connection": "wifi_hotspot"}), "Wi-Fi hotspot"
        )
        self.assertEqual(
            _render(template, build_state_payload(dict(STATUS))),
            "USB (iPhone), Wi-Fi fallback",
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_active_connection_null_renders_not_connected(self) -> None:
        template = self.cmps["active_connection"]["value_template"]
        self.assertEqual(
            _render(template, {"active_connection": "wifi_hotspot"}), "Wi-Fi hotspot"
        )
        self.assertEqual(
            _render(template, {"active_connection": "iphone_usb"}), "USB (iPhone)"
        )
        self.assertEqual(
            _render(template, {"active_connection": None}), "Not connected"
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_text_fallbacks_render_for_null(self) -> None:
        public_ip = self.cmps["public_ip"]["value_template"]
        self.assertEqual(_render(public_ip, {"public_ip": None}), "Not connected")
        self.assertEqual(_render(public_ip, {"public_ip": ""}), "Not connected")
        self.assertEqual(
            _render(public_ip, {"public_ip": "203.0.113.10"}), "203.0.113.10"
        )
        interface = self.cmps["downstream_interface"]["value_template"]
        self.assertEqual(
            _render(interface, {"downstream_interface": None}), "Not present"
        )
        self.assertEqual(_render(interface, {"downstream_interface": "eth1"}), "eth1")
        health = self.cmps["health"]["value_template"]
        self.assertEqual(_render(health, {"health": "healthy"}), "OK")

    @unittest.skipUnless(
        _HAS_HOME_ASSISTANT,
        "Home Assistant is not installed",
    )
    def test_text_fallbacks_remain_text_in_home_assistant(self) -> None:
        assert HomeAssistant is not None
        assert Template is not None

        async def render() -> tuple[object, object]:
            hass = HomeAssistant("/tmp")
            interface = Template(
                self.cmps["downstream_interface"]["value_template"], hass
            ).async_render(
                {"value_json": {"downstream_interface": None}},
                parse_result=True,
            )
            public_ip = Template(
                self.cmps["public_ip"]["value_template"], hass
            ).async_render(
                {"value_json": {"public_ip": None}},
                parse_result=True,
            )
            return interface, public_ip

        self.assertEqual(
            asyncio.run(render()),
            ("Not present", "Not connected"),
        )

    @unittest.skipUnless(_HAS_JINJA, "jinja2 not installed")
    def test_gateway_state_template_has_no_disabled_option(self) -> None:
        template = self.cmps["gateway_state"]["value_template"]
        self.assertNotIn("Disabled", template)
        self.assertNotIn("disabled", template)
        self.assertEqual(_render(template, {"state": "connected"}), "Connected")


if __name__ == "__main__":
    unittest.main()
