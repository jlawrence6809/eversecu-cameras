#!/usr/bin/env python3
"""Remove the private four-byte header from each O-KAM RTSP audio block."""

from __future__ import annotations

import argparse
from pathlib import Path

BLOCK_SIZE = 164
HEADER_SIZE = 4
HEADER_PREFIX = bytes((0x00, 0x10))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="raw A-law data copied from RTSP")
    parser.add_argument("output", type=Path, help="header-free raw A-law output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.input.read_bytes()
    complete_size = len(source) - (len(source) % BLOCK_SIZE)
    if complete_size == 0:
        raise SystemExit("input contains no complete 164-byte audio blocks")

    trailing = len(source) - complete_size
    payloads = []
    for offset in range(0, complete_size, BLOCK_SIZE):
        block = source[offset : offset + BLOCK_SIZE]
        if block[: len(HEADER_PREFIX)] != HEADER_PREFIX:
            actual = block[:HEADER_SIZE].hex(" ")
            raise SystemExit(f"unexpected header at byte {offset}: {actual}")
        payloads.append(block[HEADER_SIZE:])

    args.output.write_bytes(b"".join(payloads))
    print(
        f"stripped {complete_size // BLOCK_SIZE} blocks; "
        f"wrote {sum(map(len, payloads))} A-law bytes; "
        f"ignored {trailing} trailing bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
