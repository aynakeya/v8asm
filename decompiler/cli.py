from __future__ import annotations

import argparse
from pathlib import Path

from .core import decompile_file


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        prog="decompiler", description="V8 bytecode decompiler"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(root / "samples" / "main.d8.jsc.txt"),
        help="path to a structured JSON or legacy text disassembly",
    )
    parser.add_argument(
        "--linear",
        action="store_true",
        help="Emit bytecode-aligned diagnostic output instead of source recovery",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Emit a lightweight JS runtime prelude to make pseudo code easier to run",
    )
    args = parser.parse_args()
    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"{path} does not exist")
    print(decompile_file(path, linear=args.linear, runtime=args.runtime))
