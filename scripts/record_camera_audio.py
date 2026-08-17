#!/usr/bin/env python3
"""Interactively record correctly framed audio from an O-KAM/EVERSECU camera."""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BLOCK_SIZE = 164
HEADER_SIZE = 4
HEADER_PREFIX = bytes((0x00, 0x10))
PAYLOAD_SIZE = BLOCK_SIZE - HEADER_SIZE
SAMPLE_RATE = 8000
BLOCKS_PER_SECOND = SAMPLE_RATE // PAYLOAD_SIZE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="camera IPv4 address or hostname")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--rtsp-port", type=int, default=10554)
    parser.add_argument("--stream", default="av0_1")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--countdown", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("samples/camera-microphone.wav"),
    )
    return parser.parse_args()


def read_exact(stream: object, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def main() -> int:
    args = parse_args()
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")

    password = os.environ.get("CAMERA_PASSWORD") or getpass.getpass("Camera password: ")
    url = (
        f"rtsp://{args.username}:{password}@{args.host}:{args.rtsp_port}"
        f"/tcp/{args.stream}"
    )
    command = [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        url,
        "-map",
        "0:a:0",
        "-c:a",
        "copy",
        "-f",
        "alaw",
        "pipe:1",
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    if process.stdout is None:
        raise SystemExit("failed to open FFmpeg audio output")

    ready = threading.Event()
    recording = threading.Event()
    complete = threading.Event()
    errors: list[str] = []
    payloads: list[bytes] = []
    target_blocks = round(args.duration * BLOCKS_PER_SECOND)

    def receive_audio() -> None:
        try:
            while len(payloads) < target_blocks:
                block = read_exact(process.stdout, BLOCK_SIZE)
                if len(block) != BLOCK_SIZE:
                    raise RuntimeError("RTSP audio stream ended unexpectedly")
                if block[: len(HEADER_PREFIX)] != HEADER_PREFIX:
                    actual = block[:HEADER_SIZE].hex(" ")
                    raise RuntimeError(f"unexpected private audio header: {actual}")
                ready.set()
                if recording.is_set():
                    payloads.append(block[HEADER_SIZE:])
            complete.set()
        except Exception as error:  # noqa: BLE001 - forward receiver thread failures
            errors.append(str(error))
            ready.set()
            complete.set()

    receiver = threading.Thread(target=receive_audio, daemon=True)
    receiver.start()

    try:
        print("Connecting to the camera microphone...", flush=True)
        if not ready.wait(timeout=15):
            raise RuntimeError("timed out waiting for RTSP audio")
        if errors:
            raise RuntimeError(errors[0])

        input("Stream connected and warmed up. Press Enter when you are ready: ")
        for remaining in range(args.countdown, 0, -1):
            print(f"{remaining}...", flush=True)
            time.sleep(1)
        print(f"RECORDING NOW for {args.duration:g} seconds — speak/clap!", flush=True)
        recording.set()

        if not complete.wait(timeout=args.duration + 5):
            raise RuntimeError("timed out while recording audio")
        if errors:
            raise RuntimeError(errors[0])
        print("RECORDING COMPLETE", flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    raw_audio = b"".join(payloads)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    decode = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "alaw",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        "-c:a",
        "pcm_s16le",
        str(args.output),
    ]
    subprocess.run(decode, input=raw_audio, check=True)
    print(f"Saved {len(payloads) / BLOCKS_PER_SECOND:.2f} seconds to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:  # noqa: BLE001 - present a concise CLI error
        print(f"recording failed: {error}", file=sys.stderr)
        raise SystemExit(1)
