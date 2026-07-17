from __future__ import annotations

import argparse
import sys

from .disassembler import disassemble_file


def _offset(value: str) -> int:
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer offset") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("offset must be non-negative")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="disassembler",
        description="Disassemble V8 cached bytecode without loading V8",
    )
    parser.add_argument("input")
    parser.add_argument("--version", help="override V8 version-hash detection")
    parser.add_argument(
        "--runtime-variant",
        help="override the profile runtime-ID variant (for example legacy or leaptiering)",
    )
    parser.add_argument(
        "--snapshot-blob",
        help="resolve read-only strings from a matching V8 startup snapshot",
    )
    parser.add_argument(
        "--payload-offset",
        type=_offset,
        help=(
            "bypass the cached-data header and parse a raw serializer payload "
            "at this file offset; requires --version"
        ),
    )
    args = parser.parse_args()
    try:
        sys.stdout.write(
            disassemble_file(
                args.input,
                args.version,
                args.runtime_variant,
                args.snapshot_blob,
                args.payload_offset,
            )
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"disassembler: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
