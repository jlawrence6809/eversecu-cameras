"""Tests for camera connection watchdog decisions."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from watch_connection import assess_health, load_alert_active, run, save_alert_state


class WatchConnectionTests(unittest.TestCase):
    """Exercise stale-frame assessment and alert deduplication."""

    def test_recent_frame_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 9, 7, tzinfo=UTC)
            path = Path(directory) / "health.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "streaming",
                        "last_frame_at": (now - timedelta(seconds=10)).isoformat(),
                    }
                )
            )
            assessment = assess_health(path, 300, now)
            self.assertTrue(assessment.healthy)

    def test_stale_frame_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 9, 7, tzinfo=UTC)
            path = Path(directory) / "health.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "retrying",
                        "last_frame_at": (now - timedelta(minutes=6)).isoformat(),
                    }
                )
            )
            assessment = assess_health(path, 300, now)
            self.assertFalse(assessment.healthy)
            self.assertIn("6.0 minutes", assessment.detail)

    def test_alert_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchdog.json"
            self.assertFalse(load_alert_active(path))
            save_alert_state(path, True)
            self.assertTrue(load_alert_active(path))
            save_alert_state(path, False)
            self.assertFalse(load_alert_active(path))

    @patch("watch_connection.send_dm")
    def test_failure_alert_is_sent_only_once(self, send_dm_mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                health_file=root / "missing-health.json",
                state_file=root / "watchdog.json",
                stale_seconds=300,
                recipient="camera-agent@example.test",
                agent_xmpp=root / "agent-xmpp",
                config=root / "config.toml",
                restart_service=None,
            )
            now = datetime(2026, 9, 7, tzinfo=UTC)

            run(args, now)
            run(args, now)

            send_dm_mock.assert_called_once()
            self.assertTrue(load_alert_active(args.state_file))

    @patch("watch_connection.send_dm")
    def test_recovery_alert_clears_active_failure(self, send_dm_mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            health_file = root / "health.json"
            now = datetime(2026, 9, 7, tzinfo=UTC)
            health_file.write_text(
                json.dumps(
                    {
                        "status": "streaming",
                        "last_frame_at": now.isoformat(),
                    }
                )
            )
            state_file = root / "watchdog.json"
            save_alert_state(state_file, True)
            args = Namespace(
                health_file=health_file,
                state_file=state_file,
                stale_seconds=300,
                recipient="camera-agent@example.test",
                agent_xmpp=root / "agent-xmpp",
                config=root / "config.toml",
                restart_service=None,
            )

            run(args, now)

            send_dm_mock.assert_called_once()
            self.assertFalse(load_alert_active(state_file))

    @patch("watch_connection.send_dm")
    @patch("watch_connection.restart_launch_agent")
    def test_new_failure_requests_one_service_restart(
        self,
        restart_mock,
        send_dm_mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                health_file=root / "missing-health.json",
                state_file=root / "watchdog.json",
                stale_seconds=300,
                recipient="camera-agent@example.test",
                agent_xmpp=root / "agent-xmpp",
                config=root / "config.toml",
                restart_service="example.camera-detector",
            )

            run(args, datetime(2026, 9, 7, tzinfo=UTC))

            restart_mock.assert_called_once_with("example.camera-detector")
            self.assertIn("clean process restart", send_dm_mock.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
