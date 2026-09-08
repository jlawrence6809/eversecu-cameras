"""Tests for detector health persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from connection_health import HealthReporter


class HealthReporterTests(unittest.TestCase):
    """Exercise health transitions written for the watchdog."""

    def test_failure_then_frame_records_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "health.json"
            reporter = HealthReporter(path, "yard", "192.0.2.10", 0)

            reporter.starting()
            reporter.failed()
            failed = json.loads(path.read_text())
            self.assertEqual(failed["status"], "retrying")
            self.assertEqual(failed["consecutive_failures"], 1)
            self.assertIsNotNone(failed["failure_started_at"])

            reporter.frame_received()
            recovered = json.loads(path.read_text())
            self.assertEqual(recovered["status"], "streaming")
            self.assertEqual(recovered["consecutive_failures"], 0)
            self.assertIsNone(recovered["failure_started_at"])
            self.assertIsNotNone(recovered["last_frame_at"])


if __name__ == "__main__":
    unittest.main()
