#!/usr/bin/env python3
"""Control O-KAM lights, siren, and humanoid tracking over local UDP/P2P.

The supported commands have been bench tested against an EVERSECU/O-KAM
camera. The client does not contact an O-KAM cloud service and does not need
the camera's ONVIF/RTSP administrator password.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import time
from urllib.parse import quote

P2P_PORT = 32108
P2P_KEY = b"vstarcam2019"

# VStarcam's proprietary substitution table and cipher were documented by
# Brown Fine Security under the MIT license. See THIRD_PARTY_NOTICES.md.
P2P_TABLE = bytes.fromhex(
    "7c9ce84a13dedcb22f2123e4307b3d8cbc0b270c3cf79ae7087196009785efc1"
    "1fc4dba1c2ebd901faba3b05b81587832872d18b5ad6da9358feaacc6e1bf0a3"
    "88ab43c00db545384f502266207f075b14981d9ba72ab9a8cbf1fc4947063eb1"
    "0e043a945eee541134dd4df9ecc7c9e3781a6f706ba4bda95dd5f8e5bb26af42"
    "37d8e1020aae5f1cc573094e6924906d12b319ad748a2940f52dbea559e0f479"
    "d24bce8982488425c6912ba2fb8fe9a6b09e3f65f603312eac0f952c5ced39b7"
    "336c567eb4a0fd7a815351868d9f77ff6a80dfe2bf10d775645776f355cdd0c8"
    "18e6364162cf99f2324c67606192cad3ea637d16b68ed46835c3529d46441e17"
)


class ProtocolError(RuntimeError):
    """The camera did not complete or understand a P2P exchange."""


class P2PCipher:
    def __init__(self, key: bytes = P2P_KEY) -> None:
        self.key = [0, 0, 0, 0]
        for value in key[:21]:
            self.key[0] = (self.key[0] + value) & 0xFF
            self.key[1] = (self.key[1] - value) & 0xFF
            self.key[2] = (self.key[2] + value // 3) & 0xFF
            self.key[3] ^= value

    def decrypt(self, ciphertext: bytes) -> bytes:
        plaintext = bytearray()
        for index, value in enumerate(ciphertext):
            previous = 0 if index == 0 else ciphertext[index - 1]
            lookup = P2P_TABLE[(previous + self.key[previous & 3]) & 0xFF]
            plaintext.append(value ^ lookup)
        return bytes(plaintext)

    def encrypt(self, plaintext: bytes) -> bytes:
        ciphertext = bytearray()
        previous = 0
        for value in plaintext:
            lookup = P2P_TABLE[(previous + self.key[previous & 3]) & 0xFF]
            encrypted = value ^ lookup
            ciphertext.append(encrypted)
            previous = encrypted
        return bytes(ciphertext)


class OkamP2PClient:
    def __init__(self, host: str, timeout: float = 10.0, attempts: int = 3) -> None:
        self.host = host
        self.timeout = timeout
        self.attempts = attempts
        self.cipher = P2PCipher()

    @staticmethod
    def _control_frame(request: bytes, sequence: int = 0) -> bytes:
        inner = b"\xd1\x00" + sequence.to_bytes(2, "big")
        inner += b"\x01\x0a\x00\x00" + len(request).to_bytes(4, "little") + request
        return b"\xf1\xd0" + len(inner).to_bytes(2, "big") + inner

    @staticmethod
    def _control_ack(sequence: bytes) -> bytes:
        return b"\xf1\xd1\x00\x06\xd1\x00\x00\x01" + sequence

    def request(self, request: bytes) -> str:
        errors = []
        for attempt in range(1, self.attempts + 1):
            try:
                return self._request_once(request)
            except ProtocolError as error:
                errors.append(str(error))
                if attempt < self.attempts:
                    time.sleep(0.5)
        raise ProtocolError(
            f"camera did not respond after {self.attempts} session attempts: {errors[-1]}"
        )

    def _request_once(self, request: bytes) -> str:
        discovery = self.cipher.encrypt(b"\xf1\x30\x00\x00")
        alive = self.cipher.encrypt(b"\xf1\xe0\x00\x00")
        channel_open = self.cipher.encrypt(b"\xf1\xd1\x00\x06\xd1\x07\x00\x01\xaa\xaa")
        command = self.cipher.encrypt(self._control_frame(request))

        peer: tuple[str, int] | None = None
        last_command = 0.0
        deadline = time.monotonic() + self.timeout

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(0.25)
            client.sendto(discovery, (self.host, P2P_PORT))

            while time.monotonic() < deadline:
                try:
                    packet, address = client.recvfrom(65535)
                    plaintext = self.cipher.decrypt(packet)
                    packet_type = plaintext[:2]

                    if packet_type == b"\xf1\x41":
                        peer = address
                        client.sendto(packet, peer)
                    elif packet_type in (b"\xf1\x42", b"\xf1\x43"):
                        peer = address
                        if time.monotonic() - last_command > 0.35:
                            client.sendto(alive, peer)
                            client.sendto(channel_open, peer)
                            client.sendto(command, peer)
                            last_command = time.monotonic()
                    elif packet_type == b"\xf1\xd0" and plaintext[4:6] == b"\xd1\x00":
                        sequence = plaintext[6:8]
                        client.sendto(
                            self.cipher.encrypt(self._control_ack(sequence)), address
                        )
                        body = plaintext[16:].decode("latin-1", errors="replace")
                        if "result=" in body:
                            return body
                except TimeoutError:
                    if peer and time.monotonic() - last_command > 0.55:
                        client.sendto(alive, peer)
                        client.sendto(channel_open, peer)
                        client.sendto(command, peer)
                        last_command = time.monotonic()

        raise ProtocolError(
            f"camera did not return a control response within {self.timeout:g} seconds"
        )


def authenticated_request(path: str, args: argparse.Namespace) -> bytes:
    if not path.endswith("&"):
        path += "&"
    fields = (
        ("loginuse", args.login_user),
        ("userId", args.user_id),
        ("loginpas", args.login_pass),
        ("user", args.device_user),
        ("pwd", args.p2p_password),
    )
    query = "".join(f"{name}={quote(value, safe='')}&" for name, value in fields)
    return f"GET /{path}{query}".encode("ascii")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="camera IPv4 address or hostname")
    parser.add_argument(
        "action",
        choices=(
            "on",
            "off",
            "status",
            "ir-off",
            "ir-on",
            "ir-auto",
            "siren-on",
            "siren-off",
            "track-on",
            "track-off",
            "track-status",
        ),
        help=(
            "white spotlight action (on/off/status) or infrared night-mode "
            "action (ir-off/ir-on/ir-auto) or siren action "
            "(siren-on/siren-off) or humanoid tracking action "
            "(track-on/track-off/track-status)"
        ),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--user-id", default=os.environ.get("OKAM_USER_ID", "0"))
    parser.add_argument("--login-pass", default=os.environ.get("OKAM_LOGIN_PASS", ""))
    parser.add_argument("--login-user", default="admin")
    parser.add_argument("--device-user", default="admin")
    parser.add_argument(
        "--p2p-password", default=os.environ.get("OKAM_P2P_PASSWORD", "888888")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "status":
        path = "trans_cmd_string.cgi?cmd=2109&command=2&"
    elif args.action in ("on", "off"):
        light = 1 if args.action == "on" else 0
        path = f"trans_cmd_string.cgi?cmd=2109&command=0&light={light}&"
    elif args.action.startswith("ir-"):
        ircut = {"ir-off": 0, "ir-on": 1, "ir-auto": 2}[args.action]
        path = f"camera_control.cgi?param=14&value={ircut}&"
    elif args.action.startswith("siren-"):
        siren = 1 if args.action == "siren-on" else 0
        path = f"trans_cmd_string.cgi?cmd=2109&command=0&siren={siren}&"
    elif args.action == "track-status":
        path = "trans_cmd_string.cgi?cmd=2127&command=1&"
    else:
        enable = 1 if args.action == "track-on" else 0
        path = f"trans_cmd_string.cgi?cmd=2127&command=0&enable={enable}&"

    client = OkamP2PClient(args.host, args.timeout, args.attempts)
    response = client.request(authenticated_request(path, args))
    compact = " ".join(line.strip() for line in response.splitlines() if line.strip())
    print(compact)

    if 'result="ok"' not in response:
        raise ProtocolError("camera response did not report success")
    if args.action in ("on", "off"):
        expected = "1" if args.action == "on" else "0"
        match = re.search(r"lightStatus=(\d+)", response)
        if not match or match.group(1) != expected:
            raise ProtocolError(f"camera did not confirm lightStatus={expected}")
    elif args.action.startswith("ir-"):
        expected = {"ir-off": "0", "ir-on": "1", "ir-auto": "2"}[args.action]
        readback = client.request(authenticated_request("get_camera_params.cgi?", args))
        compact = " ".join(
            line.strip() for line in readback.splitlines() if line.strip()
        )
        print(compact)
        match = re.search(r"\bircut=(\d+)", readback)
        if not match or match.group(1) != expected:
            raise ProtocolError(f"camera did not confirm ircut={expected}")
    elif args.action.startswith("siren-"):
        expected = "1" if args.action == "siren-on" else "0"
        match = re.search(r"\bsirenStatus=(\d+)", response)
        if not match or match.group(1) != expected:
            raise ProtocolError(f"camera did not confirm sirenStatus={expected}")
    elif args.action.startswith("track-"):
        readback = client.request(
            authenticated_request("trans_cmd_string.cgi?cmd=2127&command=1&", args)
        )
        compact = " ".join(
            line.strip() for line in readback.splitlines() if line.strip()
        )
        if args.action != "track-status":
            print(compact)
        match = re.search(r"\benable=(\d+)", readback)
        if not match:
            raise ProtocolError("camera did not report humanoid tracking state")
        if args.action != "track-status":
            expected = "1" if args.action == "track-on" else "0"
            if match.group(1) != expected:
                raise ProtocolError(
                    f"camera did not confirm tracking enable={expected}"
                )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ProtocolError) as error:
        print(f"P2P control failed: {error}", file=sys.stderr)
        raise SystemExit(1)
