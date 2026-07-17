from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from rootfs.app.addon_options import read_options, set_enabled_option


class AddonOptionsTests(unittest.TestCase):
    def test_set_enabled_preserves_all_other_options(self) -> None:
        captured: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "auto_disable_minutes": 30,
                        "hotspot_password": "secret",
                    }
                ),
                encoding="utf-8",
            )

            error = set_enabled_option(
                False,
                token="token",
                options_path=path,
                urlopen=lambda request, **kwargs: captured.append(request),
            )

        self.assertIsNone(error)
        self.assertEqual(len(captured), 1)
        payload = json.loads(captured[0].data.decode("utf-8"))["options"]
        self.assertEqual(
            payload,
            {
                "enabled": False,
                "auto_disable_minutes": 30,
                "hotspot_password": "secret",
            },
        )
        self.assertEqual(
            captured[0].get_header("Authorization"),
            "Bearer token",
        )

    def test_missing_options_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"

            error = set_enabled_option(
                False,
                token="token",
                options_path=path,
                urlopen=lambda request, **kwargs: object(),
            )

        self.assertIn("options are unavailable", error or "")

    def test_read_options_rejects_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text("[]", encoding="utf-8")
            self.assertIsNone(read_options(path))


if __name__ == "__main__":
    unittest.main()
