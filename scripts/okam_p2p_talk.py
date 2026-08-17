#!/usr/bin/env python3
"""Play an audio file or a short test tone through an O-KAM camera speaker.

Audio is converted with FFmpeg to the camera's confirmed talk-back format:
mono, 16 kHz, G.711 A-law in 640-byte (40 ms) frames. The transport stays on
the LAN and uses the same O-KAM P2P identity as okam_p2p_control.py.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from okam_p2p_control import (
    P2P_PORT,
    OkamP2PClient,
    P2PCipher,
    ProtocolError,
    authenticated_request,
)

SAMPLE_RATE = 16_000
FRAME_BYTES = 640
FRAME_SECONDS = FRAME_BYTES / SAMPLE_RATE
ALAW_SILENCE = 0xD5
TALK_MEDIA_HEADER = bytes.fromhex(
    "55 aa 15 a8 08 01 00 00 00 00 00 00 00 00 00 00 "
    "80 02 00 00 00 00 00 00 00 00 00 07 00 00 00 00"
)


class TalkSession:
    """Minimal reliable-channel session for O-KAM talk-back."""

    def __init__(self, host: str, timeout: float) -> None:
        self.host = host
        self.timeout = timeout
        self.cipher = P2PCipher()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(0.25)
        self.peer: tuple[str, int] | None = None
        self.talk_ack_packets = 0

    def close(self) -> None:
        self.socket.close()

    def _send_plain(self, packet: bytes) -> None:
        if self.peer is None:
            raise ProtocolError("P2P session has no camera peer")
        self.socket.sendto(self.cipher.encrypt(packet), self.peer)

    @staticmethod
    def _channel_ack(channel: bytes, sequence: bytes) -> bytes:
        return b"\xf1\xd1\x00\x06" + channel + b"\x00\x01" + sequence

    @staticmethod
    def _data_frame(channel: int, sequence: int, body: bytes) -> bytes:
        inner = b"\xd1" + bytes([channel]) + sequence.to_bytes(2, "big") + body
        return b"\xf1\xd0" + len(inner).to_bytes(2, "big") + inner

    def connect(self) -> None:
        discovery = self.cipher.encrypt(b"\xf1\x30\x00\x00")
        self.socket.sendto(discovery, (self.host, P2P_PORT))
        deadline = time.monotonic() + self.timeout

        while time.monotonic() < deadline:
            try:
                packet, address = self.socket.recvfrom(65535)
            except TimeoutError:
                continue

            plaintext = self.cipher.decrypt(packet)
            if plaintext[:2] == b"\xf1\x41":
                self.peer = address
                self.socket.sendto(packet, address)
            elif plaintext[:2] in (b"\xf1\x42", b"\xf1\x43"):
                self.peer = address
                self._send_plain(b"\xf1\xe0\x00\x00")
                self._send_plain(b"\xf1\xd1\x00\x06\xd1\x07\x00\x01\xaa\xaa")
                return

        raise ProtocolError(
            f"camera did not establish a P2P session within {self.timeout:g} seconds"
        )

    def _handle_packet(self, packet: bytes) -> str | None:
        plaintext = self.cipher.decrypt(packet)
        if plaintext[:2] != b"\xf1\xd0" or len(plaintext) < 8:
            if plaintext[:2] == b"\xf1\xd1" and plaintext[4:6] == b"\xd1\x03":
                self.talk_ack_packets += 1
            return None

        channel = plaintext[4:6]
        self._send_plain(self._channel_ack(channel, plaintext[6:8]))
        if channel == b"\xd1\x00":
            return plaintext[16:].decode("latin-1", errors="replace")
        return None

    def request(self, request: bytes, sequence: int) -> str:
        command = OkamP2PClient._control_frame(request, sequence)
        deadline = time.monotonic() + self.timeout
        last_send = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_send >= 0.5:
                self._send_plain(command)
                last_send = now
            try:
                packet, _ = self.socket.recvfrom(65535)
            except TimeoutError:
                continue
            response = self._handle_packet(packet)
            if response is not None and "result=" in response:
                result_match = re.search(
                    r"\bresult\s*=\s*['\"]?([^'\";\r\n]+)", response
                )
                result_value = result_match.group(1).strip() if result_match else ""
                if result_value not in ("ok", "0"):
                    raise ProtocolError(
                        f"camera returned unsuccessful result {result_value!r}"
                    )
                return response

        raise ProtocolError(
            f"camera did not answer a talk-back command within {self.timeout:g} seconds"
        )

    def play(self, audio: bytes) -> None:
        frame_count = len(audio) // FRAME_BYTES
        started = time.monotonic()
        last_alive = started

        for sequence in range(frame_count):
            target = started + sequence * FRAME_SECONDS
            while True:
                remaining = target - time.monotonic()
                if remaining <= 0:
                    break
                self.socket.settimeout(min(remaining, 0.01))
                try:
                    packet, _ = self.socket.recvfrom(65535)
                except TimeoutError:
                    continue
                self._handle_packet(packet)

            if time.monotonic() - last_alive >= 10:
                self._send_plain(b"\xf1\xe0\x00\x00")
                last_alive = time.monotonic()

            payload = audio[sequence * FRAME_BYTES : (sequence + 1) * FRAME_BYTES]
            self._send_plain(self._data_frame(3, sequence, TALK_MEDIA_HEADER + payload))

        drain_deadline = time.monotonic() + 0.3
        while time.monotonic() < drain_deadline:
            self.socket.settimeout(min(0.01, drain_deadline - time.monotonic()))
            try:
                packet, _ = self.socket.recvfrom(65535)
            except TimeoutError:
                continue
            self._handle_packet(packet)


def encode_audio(args: argparse.Namespace) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ProtocolError("FFmpeg is required but was not found on PATH")

    command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    if args.file is not None:
        if not args.file.is_file():
            raise ProtocolError(f"audio file does not exist: {args.file}")
        command.extend(["-i", str(args.file)])
    else:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                (
                    f"sine=frequency={args.frequency}:sample_rate={SAMPLE_RATE}:"
                    f"duration={args.tone}"
                ),
                "-af",
                "volume=0.50",
            ]
        )
    command.extend(["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "alaw", "pipe:1"])

    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProtocolError(f"FFmpeg audio conversion failed: {detail}")
    if not result.stdout:
        raise ProtocolError("FFmpeg produced no audio")

    maximum_bytes = int(args.max_seconds * SAMPLE_RATE)
    if len(result.stdout) > maximum_bytes:
        raise ProtocolError(
            f"encoded audio exceeds the {args.max_seconds:g}-second safety limit"
        )

    pad = (-len(result.stdout)) % FRAME_BYTES
    return result.stdout + bytes([ALAW_SILENCE]) * pad


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="camera IPv4 address or hostname")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="audio file to play")
    source.add_argument(
        "--tone",
        type=float,
        metavar="SECONDS",
        help="generate a low-volume test tone of this duration",
    )
    parser.add_argument("--frequency", type=float, default=660.0)
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="encode and frame the audio without contacting the camera",
    )
    parser.add_argument("--user-id", default=os.environ.get("OKAM_USER_ID", "0"))
    parser.add_argument("--login-pass", default=os.environ.get("OKAM_LOGIN_PASS", ""))
    parser.add_argument("--login-user", default="admin")
    parser.add_argument("--device-user", default="admin")
    parser.add_argument(
        "--p2p-password", default=os.environ.get("OKAM_P2P_PASSWORD", "888888")
    )
    args = parser.parse_args()
    if args.tone is not None and not 0 < args.tone <= args.max_seconds:
        parser.error("--tone must be positive and no longer than --max-seconds")
    if not 0 < args.frequency <= 8_000:
        parser.error("--frequency must be between 0 and 8000 Hz")
    if not 0 < args.max_seconds <= 60:
        parser.error("--max-seconds must be between 0 and 60")
    return args


def main() -> int:
    args = parse_args()
    audio = encode_audio(args)
    frame_count = len(audio) // FRAME_BYTES
    duration = frame_count * FRAME_SECONDS
    if args.dry_run:
        print(
            f"prepared {frame_count} frames, {len(audio)} A-law bytes, "
            f"{duration:.3f} seconds"
        )
        return 0

    session = TalkSession(args.host, args.timeout)
    video_started = False
    stream_started = False
    try:
        session.connect()
        # Match the app's native clientLogin exchange exactly. The vendor SDK
        # invokes it twice, and the capture contains two name=admin status
        # requests before any media channels are opened.
        login_path = f"get_status.cgi?name={args.device_user}&"
        session.request(authenticated_request(login_path, args), 0)
        session.request(authenticated_request(login_path, args), 1)
        session.request(
            authenticated_request("livestream.cgi?streamid=10&substream=2&", args),
            2,
        )
        video_started = True
        session.request(authenticated_request("audiostream.cgi?streamid=7&", args), 3)
        stream_started = True
        session.play(audio)
    finally:
        if stream_started:
            try:
                session.socket.settimeout(0.25)
                session.request(
                    authenticated_request("audiostream.cgi?streamid=16&", args), 4
                )
            except (OSError, ProtocolError) as error:
                print(f"warning: audio-stop command failed: {error}", file=sys.stderr)
        if video_started:
            try:
                session.socket.settimeout(0.25)
                session.request(
                    authenticated_request(
                        "livestream.cgi?streamid=16&substream=0&", args
                    ),
                    5,
                )
            except (OSError, ProtocolError) as error:
                print(f"warning: video-stop command failed: {error}", file=sys.stderr)
        session.close()

    if session.talk_ack_packets == 0:
        raise ProtocolError("camera did not acknowledge any talk-back packets")
    print(
        f"played {duration:.3f} seconds; camera sent "
        f"{session.talk_ack_packets} talk-channel acknowledgement packets"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ProtocolError) as error:
        print(f"P2P talk-back failed: {error}", file=sys.stderr)
        raise SystemExit(1)
