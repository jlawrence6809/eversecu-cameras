#!/usr/bin/env python3
"""Watch an RTSP stream and save evidence frames for canine candidates."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import cv2
import torch
from dotenv import load_dotenv
from torchvision.models.detection import (
    SSDLite320_MobileNet_V3_Large_Weights,
    ssdlite320_mobilenet_v3_large,
)

LOGGER = logging.getLogger("coyote-watch")
MODEL_NAME = "ssdlite320_mobilenet_v3_large_coco"


@dataclass(frozen=True)
class Settings:
    host: str
    username: str
    password: str
    camera_name: str
    interval_seconds: float
    confidence: float
    cooldown_seconds: float
    retention_days: int
    output_dir: Path
    stream: str

    @classmethod
    def from_environment(cls) -> Settings:
        host = os.environ.get("CAMERA_HOST", "").strip()
        username = os.environ.get("CAMERA_USERNAME", "admin")
        password = load_camera_password(username)
        if not host:
            raise ValueError("CAMERA_HOST is required")

        settings = cls(
            host=host,
            username=username,
            password=password,
            camera_name=os.environ.get("CAMERA_NAME", "yard"),
            interval_seconds=float(os.environ.get("DETECTION_INTERVAL_SECONDS", "1.0")),
            confidence=float(os.environ.get("DETECTION_CONFIDENCE", "0.35")),
            cooldown_seconds=float(os.environ.get("EVENT_COOLDOWN_SECONDS", "30")),
            retention_days=int(os.environ.get("EVENT_RETENTION_DAYS", "14")),
            output_dir=Path(os.environ.get("EVENT_OUTPUT_DIR", "events")).expanduser(),
            stream=os.environ.get("CAMERA_STREAM", "av0_1"),
        )
        if settings.interval_seconds <= 0:
            raise ValueError("DETECTION_INTERVAL_SECONDS must be positive")
        if not 0 < settings.confidence <= 1:
            raise ValueError("DETECTION_CONFIDENCE must be between 0 and 1")
        if settings.cooldown_seconds < 0:
            raise ValueError("EVENT_COOLDOWN_SECONDS cannot be negative")
        if settings.retention_days < 1:
            raise ValueError("EVENT_RETENTION_DAYS must be at least 1")
        return settings

    def rtsp_url(self) -> str:
        username = quote(self.username, safe="")
        password = quote(self.password, safe="")
        return f"rtsp://{username}:{password}@{self.host}:10554/tcp/{self.stream}"


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]


def load_camera_password(username: str) -> str:
    password = os.environ.get("CAMERA_PASSWORD", "")
    if password:
        return password

    service = os.environ.get(
        "CAMERA_KEYCHAIN_SERVICE", "eversecu-coyote-camera"
    ).strip()
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-w",
                "-a",
                username,
                "-s",
                service,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("could not read the camera password from Keychain") from error
    password = result.stdout.rstrip("\n")
    if result.returncode != 0 or not password:
        raise ValueError(
            "camera password is missing; set CAMERA_PASSWORD or add the "
            f"Keychain item {service!r} for account {username!r}"
        )
    return password


class CanineDetector:
    def __init__(self, confidence: float) -> None:
        LOGGER.info("loading %s", MODEL_NAME)
        self.weights = SSDLite320_MobileNet_V3_Large_Weights.DEFAULT
        self.categories = self.weights.meta["categories"]
        self.preprocess = self.weights.transforms()
        self.model = ssdlite320_mobilenet_v3_large(weights=self.weights)
        self.model.eval()
        self.confidence = confidence
        LOGGER.info("model ready on CPU")

    def predict(self, frame: cv2.typing.MatLike) -> list[Detection]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self.preprocess(torch.from_numpy(rgb).permute(2, 0, 1))
        with torch.inference_mode():
            result = self.model([image])[0]

        detections = []
        for label_id, score, box in zip(
            result["labels"].tolist(),
            result["scores"].tolist(),
            result["boxes"].tolist(),
            strict=True,
        ):
            if score < self.confidence:
                break
            label = self.categories[label_id]
            if label != "dog":
                continue
            x1, y1, x2, y2 = (round(value) for value in box)
            detections.append(Detection(label, score, (x1, y1, x2, y2)))
        return detections


def annotate(frame: cv2.typing.MatLike, detections: list[Detection]) -> None:
    for detection in detections:
        x1, y1, x2, y2 = detection.box
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 190, 255), 2)
        text = f"canine candidate {detection.confidence:.0%}"
        cv2.putText(
            frame,
            text,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 190, 255),
            2,
            cv2.LINE_AA,
        )


def save_event(
    frame: cv2.typing.MatLike,
    detections: list[Detection],
    settings: Settings,
) -> Path:
    occurred_at = datetime.now(UTC)
    day_dir = settings.output_dir / occurred_at.astimezone().strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{occurred_at.astimezone().strftime('%Y%m%d-%H%M%S')}-canine"
    image_path = day_dir / f"{stem}.jpg"
    metadata_path = day_dir / f"{stem}.json"

    annotated = frame.copy()
    annotate(annotated, detections)
    if not cv2.imwrite(str(image_path), annotated, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise OSError(f"failed to write {image_path}")

    metadata = {
        "occurred_at": occurred_at.isoformat(),
        "camera": settings.camera_name,
        "model": MODEL_NAME,
        "detections": [
            {
                "label": detection.label,
                "confidence": round(detection.confidence, 6),
                "box": list(detection.box),
            }
            for detection in detections
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return image_path


def prune_events(output_dir: Path, retention_days: int) -> int:
    if not output_dir.exists():
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed = 0
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if modified < cutoff:
            path.unlink()
            removed += 1
    for path in sorted(output_dir.rglob("*"), reverse=True):
        if path.is_dir():
            with suppress(OSError):
                path.rmdir()
    return removed


def open_camera(settings: Settings) -> cv2.VideoCapture:
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    capture = cv2.VideoCapture(settings.rtsp_url(), cv2.CAP_FFMPEG)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def run(settings: Settings, once: bool) -> int:
    detector = CanineDetector(settings.confidence)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    last_inference = 0.0
    last_event = float("-inf")
    last_prune = float("-inf")
    failures = 0

    while not stopping:
        LOGGER.info("connecting to camera %s", settings.camera_name)
        capture = open_camera(settings)
        if not capture.isOpened():
            LOGGER.error("camera connection failed; retrying in 5 seconds")
            capture.release()
            time.sleep(5)
            continue

        LOGGER.info("camera stream connected")
        while not stopping:
            ok, frame = capture.read()
            if not ok:
                failures += 1
                if failures >= 10:
                    LOGGER.warning("camera stream lost; reconnecting")
                    break
                continue
            failures = 0

            now = time.monotonic()
            if now - last_inference < settings.interval_seconds:
                continue
            last_inference = now

            detections = detector.predict(frame)
            if detections:
                best = max(detection.confidence for detection in detections)
                LOGGER.info("canine candidate detected at %.1f%%", best * 100)
                if now - last_event >= settings.cooldown_seconds:
                    path = save_event(frame, detections, settings)
                    LOGGER.info("saved event %s", path)
                    last_event = now

            if now - last_prune >= 3600:
                removed = prune_events(settings.output_dir, settings.retention_days)
                if removed:
                    LOGGER.info("pruned %d expired event files", removed)
                last_prune = now

            if once:
                capture.release()
                return 0

        capture.release()
        if not stopping:
            time.sleep(2)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name(".env"),
        help="environment file (default: detector/.env)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run inference on one fresh frame and exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(args.config)
    settings = Settings.from_environment()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return run(settings, args.once)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"detector failed: {error}") from error
