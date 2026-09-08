#!/usr/bin/env python3
"""Alert an agent conversation when detector frame health becomes stale."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LOGGER = logging.getLogger("coyote-watchdog")


@dataclass(frozen=True)
class HealthAssessment:
    """Result of evaluating one detector health snapshot."""

    healthy: bool
    detail: str


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO timestamp from a health snapshot."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def assess_health(
    health_file: Path,
    stale_seconds: float,
    now: datetime,
) -> HealthAssessment:
    """Determine whether decoded camera frames are recent enough."""
    try:
        payload = json.loads(health_file.read_text())
    except FileNotFoundError:
        return HealthAssessment(False, "the detector health file is missing")
    except (OSError, json.JSONDecodeError):
        return HealthAssessment(False, "the detector health file is unreadable")

    last_frame = parse_timestamp(payload.get("last_frame_at"))
    status = payload.get("status", "unknown")
    if last_frame is None:
        return HealthAssessment(False, f"no decoded frame is recorded (state {status})")

    age = max(0.0, (now.astimezone(UTC) - last_frame).total_seconds())
    if age > stale_seconds:
        return HealthAssessment(
            False,
            f"the last decoded frame is {age / 60:.1f} minutes old (state {status})",
        )
    return HealthAssessment(True, f"the last decoded frame is {age:.0f} seconds old")


def load_alert_active(state_file: Path) -> bool:
    """Return whether a failure alert was previously delivered."""
    try:
        payload = json.loads(state_file.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return payload.get("alert_active") is True


def save_alert_state(state_file: Path, active: bool) -> None:
    """Atomically persist alert deduplication state."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_name(f".{state_file.name}.tmp")
    payload = {
        "version": 1,
        "alert_active": active,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    temporary.replace(state_file)


def send_dm(
    executable: Path,
    config: Path,
    recipient: str,
    message: str,
) -> None:
    """Send one explicit-account XMPP DM without putting its body in argv."""
    result = subprocess.run(
        [
            str(executable),
            "--config",
            str(config),
            "dm",
            "send",
            recipient,
            "--stdin",
        ],
        input=message,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("agent-xmpp could not deliver the camera health alert")


def restart_launch_agent(label: str) -> None:
    """Request one clean restart from the macOS user service supervisor."""
    result = subprocess.run(
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/{label}",
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("launchctl could not restart the camera detector")


def run(args: argparse.Namespace, now: datetime | None = None) -> int:
    """Evaluate health and send only failure/recovery transitions."""
    assessment = assess_health(
        args.health_file,
        args.stale_seconds,
        now or datetime.now(UTC),
    )
    alert_active = load_alert_active(args.state_file)

    if not assessment.healthy and not alert_active:
        restart_note = ""
        if args.restart_service:
            try:
                restart_launch_agent(args.restart_service)
                restart_note = (
                    " The local watchdog requested one clean process restart."
                )
            except RuntimeError:
                restart_note = " The local process restart failed."
                LOGGER.exception("could not restart camera detector")
        send_dm(
            args.agent_xmpp,
            args.config,
            args.recipient,
            "Camera watchdog alert: "
            f"{assessment.detail}.{restart_note} "
            "Please inspect and restore the yard-camera "
            "detector within the existing camera-operations scope.",
        )
        save_alert_state(args.state_file, True)
        LOGGER.warning("sent camera failure alert: %s", assessment.detail)
    elif assessment.healthy and alert_active:
        send_dm(
            args.agent_xmpp,
            args.config,
            args.recipient,
            "Camera watchdog recovery: decoded yard-camera frames are current again.",
        )
        save_alert_state(args.state_file, False)
        LOGGER.info("sent camera recovery alert")
    else:
        save_alert_state(args.state_file, alert_active)
        LOGGER.info("camera health unchanged: %s", assessment.detail)
    return 0


def parse_args() -> argparse.Namespace:
    """Parse watchdog command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-file", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--stale-seconds", type=float, default=300)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--agent-xmpp", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--restart-service",
        help="macOS launch-agent label to restart once on a new failure",
    )
    return parser.parse_args()


def main() -> int:
    """Run one watchdog check."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    return run(parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"watchdog failed: {error}") from error
