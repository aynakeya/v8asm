from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import calculate_version_hash, find_version, parse_cached_data_hash


def _range(value: str) -> tuple[int, int]:
    try:
        start_text, end_text = value.split(":", 1)
        start, end = int(start_text, 0), int(end_text, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "range must use START:END with an exclusive END"
        ) from exc
    if start < 0 or end <= start:
        raise argparse.ArgumentTypeError("range must be non-negative and non-empty")
    return start, end


def _hash(value: str) -> int:
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "hash must be an integer such as 0x2b2c7714"
        ) from exc
    if not 0 <= parsed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("hash must fit in uint32")
    return parsed


def _version(value: str) -> tuple[int, int, int, int]:
    try:
        parts = tuple(map(int, value.split(".")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("version must contain four integers") from exc
    if len(parts) != 4 or any(part < 0 for part in parts):
        raise argparse.ArgumentTypeError("version must use MAJOR.MINOR.BUILD.PATCH")
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="checkversion",
        description="Find a V8 version from a cached-data version hash",
    )
    parser.add_argument(
        "input", nargs="?", type=Path, help="V8 .jsc cached-data file"
    )
    parser.add_argument("--hash", dest="target_hash", type=_hash)
    parser.add_argument(
        "--calculate",
        type=_version,
        metavar="VERSION",
        help="calculate a MAJOR.MINOR.BUILD.PATCH hash without searching",
    )
    parser.add_argument(
        "--major-range", type=_range, default=(0, 20), metavar="START:END"
    )
    parser.add_argument(
        "--minor-range", type=_range, default=(0, 20), metavar="START:END"
    )
    parser.add_argument(
        "--build-range", type=_range, default=(0, 500), metavar="START:END"
    )
    parser.add_argument(
        "--patch-range", type=_range, default=(0, 200), metavar="START:END"
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="worker processes (default: at most 4)",
    )
    args = parser.parse_args()

    if args.calculate is not None:
        if args.input is not None or args.target_hash is not None:
            parser.error("--calculate cannot be combined with an input file or --hash")
        value = calculate_version_hash(*args.calculate)
        print(f"version: {'.'.join(map(str, args.calculate))}")
        print(f"version_hash: 0x{value:08x}")
        return 0

    if (args.input is None) == (args.target_hash is None):
        parser.error("provide exactly one input file or --hash")
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    try:
        target_hash = (
            parse_cached_data_hash(args.input)
            if args.input is not None
            else args.target_hash
        )
        result = find_version(
            target_hash,
            major_range=args.major_range,
            minor_range=args.minor_range,
            build_range=args.build_range,
            patch_range=args.patch_range,
            jobs=args.jobs,
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"checkversion: {exc}\n")

    print(f"version_hash: 0x{target_hash:08x}")
    if result is None:
        print("version: not found")
        return 1
    print(f"version: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
