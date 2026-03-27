#!/usr/bin/env python3
"""Extract one V8 BytecodeArray blob from v8asm disasm text.

The input may contain multiple BytecodeArray sections. By default this script
extracts the last one, which is usually the user function instead of the
wrapper/init bytecode.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

LINE_RE = re.compile(r"@\s*(\d+)\s*:\s*([0-9a-f]{2}(?:\s+[0-9a-f]{2})*)", re.IGNORECASE)
BYTECODE_ARRAY_RE = re.compile(r"^\s*0x[0-9a-f]+:\s+\[BytecodeArray\]", re.IGNORECASE)
NAME_RE = re.compile(r"-\s+name:\s+.*#([^>\s]+)")


class BytecodeBlock:
    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self.by_offset: dict[int, bytes] = {}
        self.max_end = 0

    def add_line(self, off: int, raw: bytes) -> None:
        self.by_offset[off] = raw
        self.max_end = max(self.max_end, off + len(raw))

    def to_blob(self) -> bytes:
        blob = bytearray(b"\x00" * self.max_end)
        for off, raw in self.by_offset.items():
            blob[off : off + len(raw)] = raw
        return bytes(blob)

    @property
    def instruction_count(self) -> int:
        return len(self.by_offset)


def parse_blocks(text: str) -> list[BytecodeBlock]:
    blocks: list[BytecodeBlock] = []
    pending_name: str | None = None
    current: BytecodeBlock | None = None

    for line in text.splitlines():
        name_match = NAME_RE.search(line)
        if name_match:
            pending_name = name_match.group(1)

        if BYTECODE_ARRAY_RE.search(line):
            current = BytecodeBlock(name=pending_name)
            blocks.append(current)
            continue

        if current is None:
            continue

        m = LINE_RE.search(line)
        if not m:
            continue
        off = int(m.group(1))
        raw = bytes(int(x, 16) for x in m.group(2).split())
        current.add_line(off, raw)
    return blocks


def select_block(blocks: list[BytecodeBlock], index: int) -> BytecodeBlock:
    if not blocks:
        raise ValueError("no BytecodeArray sections found")
    if index < 0:
        index += len(blocks)
    if index < 0 or index >= len(blocks):
        raise IndexError(f"block index {index} out of range for {len(blocks)} blocks")
    return blocks[index]


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract V8 bytecode blob from disasm text")
    ap.add_argument("input", help="v8asm disasm text file")
    ap.add_argument("-o", "--output", help="output .bin path")
    ap.add_argument(
        "-i",
        "--block-index",
        type=int,
        default=-1,
        help="BytecodeArray block index to extract (default: -1, the last block)",
    )
    ap.add_argument(
        "--list-blocks",
        action="store_true",
        help="list discovered BytecodeArray blocks and exit",
    )
    args = ap.parse_args()

    src = Path(args.input)
    blocks = parse_blocks(src.read_text(encoding="utf-8", errors="ignore"))
    if args.list_blocks:
        for idx, block in enumerate(blocks):
            name = block.name or "<anonymous>"
            print(
                f"[{idx}] name={name} instructions={block.instruction_count} size={block.max_end}"
            )
        if args.output is None:
            return 0

    if args.output is None:
        ap.error("the following arguments are required: -o/--output")

    out = Path(args.output)

    block = select_block(blocks, args.block_index)
    blob = block.to_blob()
    out.write_bytes(blob)
    name = block.name or "<anonymous>"
    print(
        f"wrote {len(blob)} bytes from block {args.block_index} ({name}) -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
