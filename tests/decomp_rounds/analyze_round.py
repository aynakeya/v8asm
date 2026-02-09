#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


def score_text(text: str) -> dict[str, int]:
    return {
        "accu_lines": len(re.findall(r"^\s*ACCU\s*=", text, flags=re.M)),
        "reg_refs": len(re.findall(r"\br\d+\b", text)),
        "goto_comments": len(re.findall(r"//\s*goto\s+offset_", text)),
        "raw_goto": len(re.findall(r"\bgoto\s+offset_", text)),
        "unknown_comments": len(re.findall(r"//\s*0x[0-9a-f]+\s+@", text)),
        "holes": len(re.findall(r"\bHOLE\b", text)),
        "functions": len(re.findall(r"^\s*function\s+", text, flags=re.M)),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: analyze_round.py <out_dir>", file=sys.stderr)
        return 1
    out_dir = Path(sys.argv[1])
    if not out_dir.exists():
        print(f"Missing out dir: {out_dir}", file=sys.stderr)
        return 1

    case_dirs = sorted([p for p in out_dir.iterdir() if p.is_dir()])
    print("# Decompile Round Summary")
    print("")
    print("| case | mode | accu_lines | reg_refs | goto_comments | raw_goto | holes |")
    print("|---|---:|---:|---:|---:|---:|---:|")

    for case_dir in case_dirs:
        case = case_dir.name
        for mode in ("v8asm", "bytenode"):
            dec = case_dir / f"{case}.{mode}.dec.l4.js"
            if not dec.exists():
                print(f"| {case} | {mode} | n/a | n/a | n/a | n/a | n/a |")
                continue
            text = dec.read_text(encoding="utf-8", errors="ignore")
            s = score_text(text)
            print(
                f"| {case} | {mode} | {s['accu_lines']} | {s['reg_refs']} | "
                f"{s['goto_comments']} | {s['raw_goto']} | {s['holes']} |"
            )

    print("")
    print("## Quick Inspection Targets")
    print("- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.")
    print("- Any non-zero `raw_goto` indicates structurer fallback/regression.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
