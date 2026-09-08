"""Persist detector connection health for an external watchdog."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path


def timestamp() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(UTC).isoformat()


class HealthReporter:
    """Write a small atomic health snapshot without exposing credentials."""

    def __init__(
        self,
        path: Path,
        camera: str,
        host: str,
        heartbeat_seconds: float = 15,
    ) -> None:
        self.path = path
        self.camera = camera
        self.host = host
        self.heartbeat_seconds = heartbeat_seconds
        self.last_frame_at: str | None = None
        self.failure_started_at: str | None = None
        self.consecutive_failures = 0
        self._last_write = float("-inf")

    def starting(self) -> None:
        """Record detector startup."""
        self._write("starting", force=True)

    def connecting(self) -> None:
        """Record a connection attempt."""
        self._write("connecting", force=True)

    def frame_received(self) -> None:
        """Record a decoded frame and periodically refresh the heartbeat."""
        now = timestamp()
        recovered = self.failure_started_at is not None or self.last_frame_at is None
        self.last_frame_at = now
        self.failure_started_at = None
        self.consecutive_failures = 0
        self._write("streaming", force=recovered)

    def failed(self) -> None:
        """Record a failed stream or connection attempt."""
        if self.failure_started_at is None:
            self.failure_started_at = timestamp()
        self.consecutive_failures += 1
        self._write("retrying", force=True)

    def stopped(self) -> None:
        """Record an intentional detector stop."""
        self._write("stopped", force=True)

    def _write(self, status: str, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < self.heartbeat_seconds:
            return
        payload = {
            "version": 1,
            "status": status,
            "camera": self.camera,
            "host": self.host,
            "updated_at": timestamp(),
            "last_frame_at": self.last_frame_at,
            "failure_started_at": self.failure_started_at,
            "consecutive_failures": self.consecutive_failures,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        temporary.replace(self.path)
        self._last_write = now
