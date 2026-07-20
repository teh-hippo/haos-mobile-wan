from __future__ import annotations

import unittest

from rootfs.app.status_model import derive_gateway_state, derive_health


def issue(
    issue_id: str,
    message: str,
    *,
    transient: bool,
    blocking: bool = True,
) -> dict[str, object]:
    return {
        "id": issue_id,
        "message": message,
        "transient": transient,
        "blocking": blocking,
    }


class StatusModelTests(unittest.TestCase):
    def test_state_precedence(self) -> None:
        fault = [issue("fault", "Broken", transient=False)]
        waiting = [
            issue(
                "upstream_waiting_for_device",
                "Waiting",
                transient=True,
            )
        ]
        connecting = [
            issue(
                "upstream_waiting_for_profile",
                "Connecting",
                transient=True,
            )
        ]

        self.assertEqual(
            derive_gateway_state(False, fault),
            "error",
        )
        self.assertEqual(
            derive_gateway_state(True, []),
            "connected",
        )
        self.assertEqual(
            derive_gateway_state(
                True,
                [
                    issue(
                        "fallback",
                        "Fallback unavailable",
                        transient=False,
                        blocking=False,
                    )
                ],
            ),
            "connected",
        )
        self.assertEqual(
            derive_gateway_state(False, waiting),
            "waiting",
        )
        self.assertEqual(
            derive_gateway_state(False, connecting),
            "connecting",
        )

    def test_health_ignores_waiting_and_deduplicates_actionable_issues(self) -> None:
        state, messages = derive_health(
            [
                issue("waiting", "Waiting", transient=True),
                issue("fault-one", "Broken", transient=False),
                issue("fault-two", "Broken", transient=False),
            ]
        )

        self.assertEqual(state, "attention")
        self.assertEqual(messages, ["Broken"])
        self.assertEqual(
            derive_health([issue("waiting", "Waiting", transient=True)]),
            ("healthy", []),
        )
        self.assertEqual(
            derive_health(
                [
                    issue(
                        "fallback",
                        "Fallback unavailable",
                        transient=False,
                        blocking=False,
                    )
                ]
            ),
            ("attention", ["Fallback unavailable"]),
        )


if __name__ == "__main__":
    unittest.main()
