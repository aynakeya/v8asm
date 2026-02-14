#!/usr/bin/env python3
"""Extract raw bytecode bytes from v8asm disasm text.

Input format: lines containing "@ <offset> : <hex bytes> <mnemonic> ..."
Output: dense binary blob ordered by increasing instruction offset.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

LINE_RE = re.compile(r"@\s*(\d+)\s*:\s*([0-9a-f]{2}(?:\s+[0-9a-f]{2})*)", re.IGNORECASE)


def parse_dump(text: str) -> bytes:
    by_offset: dict[int, bytes] = {}
    max_end = 0
    for line in text.splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        off = int(m.group(1))
        raw = bytes(int(x, 16) for x in m.group(2).split())
        by_offset[off] = raw
        max_end = max(max_end, off + len(raw))

    if not by_offset:
        return b""

    blob = bytearray(b"\x00" * max_end)
    for off, raw in by_offset.items():
        blob[off : off + len(raw)] = raw
    return bytes(blob)


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract V8 bytecode blob from disasm text")
    ap.add_argument("input", help="v8asm disasm text file")
    ap.add_argument("-o", "--output", required=True, help="output .bin path")
    args = ap.parse_args()

    src = Path(args.input)
    out = Path(args.output)

    blob = parse_dump(src.read_text(encoding="utf-8", errors="ignore"))
    out.write_bytes(blob)
    print(f"wrote {len(blob)} bytes -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
