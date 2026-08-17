#!/usr/bin/env python3
"""Read-only ONVIF and RTSP probe for the EVERSECU/O-KAM cameras."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from typing import Any

from onvif import ONVIFCamera


def plain(value: Any) -> Any:
    """Convert zeep objects into JSON-friendly values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): plain(item)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    values = getattr(value, "__values__", None)
    if values is not None:
        return plain(values)
    return str(value)


def ffprobe_stream(url: str) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if not executable:
        return {"error": "ffprobe is not installed"}
    command = [
        executable,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-show_entries",
        "stream=index,codec_name,codec_type,width,height,sample_rate,channels,avg_frame_rate",
        "-of",
        "json",
        url,
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=12
        )
        return json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "ffprobe timed out after 12 seconds"}
    except subprocess.CalledProcessError as error:
        # Do not return stderr because some ffprobe versions include the URL and password.
        return {"error": f"ffprobe exited with status {error.returncode}"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="camera IP address or hostname")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--onvif-port", type=int, default=10080)
    parser.add_argument("--rtsp-port", type=int, default=10554)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = os.environ.get("CAMERA_PASSWORD") or getpass.getpass("Camera password: ")
    camera = ONVIFCamera(args.host, args.onvif_port, args.username, password)
    device = camera.create_devicemgmt_service()
    media = camera.create_media_service()
    imaging = camera.create_imaging_service()
    ptz = camera.create_ptz_service()

    profiles = media.GetProfiles()
    profile_rows = []
    for profile in profiles:
        video = getattr(profile, "VideoEncoderConfiguration", None)
        audio = getattr(profile, "AudioEncoderConfiguration", None)
        profile_rows.append(
            {
                "token": profile.token,
                "video": plain(video),
                "audio": plain(audio),
                "ptz_configuration": plain(getattr(profile, "PTZConfiguration", None)),
            }
        )

    video_source_token = profiles[0].VideoSourceConfiguration.SourceToken
    report = {
        "device": plain(device.GetDeviceInformation()),
        "network_interfaces": plain(device.GetNetworkInterfaces()),
        "profiles": profile_rows,
        "imaging_settings": plain(
            imaging.GetImagingSettings({"VideoSourceToken": video_source_token})
        ),
        "imaging_options": plain(
            imaging.GetOptions({"VideoSourceToken": video_source_token})
        ),
        "ptz_status": plain(ptz.GetStatus({"ProfileToken": profiles[0].token})),
        "rtsp": {},
    }

    for label, path in (("main", "av0_0"), ("sub", "av0_1")):
        url = (
            f"rtsp://{args.username}:{password}@{args.host}:{args.rtsp_port}/tcp/{path}"
        )
        report["rtsp"][label] = ffprobe_stream(url)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:  # noqa: BLE001 - present a concise CLI error
        print(f"probe failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
