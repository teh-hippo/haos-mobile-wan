from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from rootfs.app.addon_options import read_options, update_options


class AddonOptionsTests(unittest.TestCase):
    def test_update_options_posts_payload_with_auth(self) -> None:
        captured: list[urllib.request.Request] = []

        error = update_options(
            {"mobile_connection": "USB (iPhone)", "auto_disable_minutes": 30},
            label="options-migration",
            token="token",
            urlopen=lambda request, **kwargs: captured.append(request),
        )

        self.assertIsNone(error)
        self.assertEqual(len(captured), 1)
        payload = json.loads(captured[0].data.decode("utf-8"))["options"]
        self.assertEqual(
            payload,
            {"mobile_connection": "USB (iPhone)", "auto_disable_minutes": 30},
        )
        self.assertEqual(
            captured[0].get_header("Authorization"),
            "Bearer token",
        )

    def test_update_options_requires_supervisor_token(self) -> None:
        error = update_options(
            {"auto_disable_minutes": 30},
            label="options-migration",
            token="",
            urlopen=lambda request, **kwargs: object(),
        )

        self.assertIn("Supervisor token is unavailable", error or "")

    def test_read_options_rejects_non_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text("[]", encoding="utf-8")
            self.assertIsNone(read_options(path))


if __name__ == "__main__":
    unittest.main()
