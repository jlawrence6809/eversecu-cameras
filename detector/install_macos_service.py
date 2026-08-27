#!/usr/bin/env python3
"""Install and start coyote-watch as a per-user macOS launch agent."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.jlawrence6809.eversecu-coyote-detector"


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True)


def main() -> int:
    detector_dir = Path(__file__).resolve().parent
    python = detector_dir / ".venv/bin/python"
    detector = detector_dir / "coyote_watch.py"
    config = detector_dir / ".env"
    if not python.is_file():
        raise SystemExit("virtual environment missing; run `uv sync` first")
    if not config.is_file():
        raise SystemExit("detector/.env is missing")

    log_dir = Path.home() / "Library/Logs/eversecu-coyote-detector"
    log_dir.mkdir(parents=True, exist_ok=True)
    agent_dir = Path.home() / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agent_dir / f"{LABEL}.plist"

    configuration = {
        "Label": LABEL,
        "ProgramArguments": [
            str(python),
            str(detector),
            "--config",
            str(config),
        ],
        "WorkingDirectory": str(detector_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(log_dir / "stdout.log"),
        "StandardErrorPath": str(log_dir / "stderr.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }
    with plist_path.open("wb") as plist_file:
        plistlib.dump(configuration, plist_file, sort_keys=True)
    plist_path.chmod(0o644)

    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    run("launchctl", "bootout", domain, str(plist_path), check=False)
    run("launchctl", "bootstrap", domain, str(plist_path))
    run("launchctl", "enable", service)
    run("launchctl", "kickstart", "-k", service)
    print(f"installed and started {LABEL}")
    print(f"logs: {log_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
