#!/usr/bin/env python3
"""Install the camera health watchdog as a per-user macOS launch agent."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.jlawrence6809.eversecu-coyote-watchdog"


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one launchctl command."""
    return subprocess.run(command, check=check, text=True)


def parse_args() -> argparse.Namespace:
    """Parse installer arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", required=True, help="destination agent JID")
    return parser.parse_args()


def main() -> int:
    """Write, load, and start the watchdog launch agent."""
    args = parse_args()
    detector_dir = Path(__file__).resolve().parent
    python = detector_dir / ".venv/bin/python"
    watchdog = detector_dir / "watch_connection.py"
    agent_xmpp = Path.home() / ".local/bin/agent-xmpp"
    xmpp_config = Path.home() / ".config/agent-xmpp-cli/config.toml"
    required = (python, watchdog, agent_xmpp, xmpp_config)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"required watchdog files are missing: {', '.join(missing)}")

    log_dir = Path.home() / "Library/Logs/eversecu-coyote-detector"
    log_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = Path.home() / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agent_dir / f"{LABEL}.plist"
    health_file = detector_dir / "state/health.json"
    state_file = detector_dir / "state/watchdog.json"

    configuration = {
        "Label": LABEL,
        "ProgramArguments": [
            str(python),
            str(watchdog),
            "--health-file",
            str(health_file),
            "--state-file",
            str(state_file),
            "--stale-seconds",
            "300",
            "--recipient",
            args.recipient,
            "--agent-xmpp",
            str(agent_xmpp),
            "--config",
            str(xmpp_config),
            "--restart-service",
            "com.jlawrence6809.eversecu-coyote-detector",
        ],
        "RunAtLoad": True,
        "StartInterval": 60,
        "StandardOutPath": str(log_dir / "watchdog-stdout.log"),
        "StandardErrorPath": str(log_dir / "watchdog-stderr.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
    }
    with plist_path.open("wb") as plist_file:
        plistlib.dump(configuration, plist_file, sort_keys=True)
    plist_path.chmod(0o644)

    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    run("launchctl", "bootout", domain, str(plist_path), check=False)
    run("launchctl", "enable", service)
    run("launchctl", "bootstrap", domain, str(plist_path))
    run("launchctl", "kickstart", "-k", service)
    print(f"installed and started {LABEL}")
    print(f"recipient: {args.recipient}")
    print(f"logs: {log_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
