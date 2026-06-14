#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


HEADER_FIELD_RE = re.compile(
    r"^\s*(magic|version_hash|flags_hash|read_only_snapshot_checksum|payload_length):\s+.*$",
    flags=re.M,
)
HEADER_FIELD_ALIASES = {
    "read_only_snapshot_checksum": "ro_snapshot",
}


def score_text(text: str) -> dict[str, int]:
    return {
        "accu_lines": len(re.findall(r"^\s*ACCU\s*=", text, flags=re.M)),
        "reg_refs": len(re.findall(r"\br\d+\b", text)),
        "goto_comments": len(re.findall(r"//\s*goto\s+offset_", text)),
        "raw_goto": len(re.findall(r"\bgoto\s+offset_", text)),
        "unknown_comments": len(re.findall(r"//\s*0x[0-9a-f]+\s+@", text)),
        "undefined_fallbacks": len(re.findall(r"<undefined: segmentfault", text)),
        "holes": len(re.findall(r"\bHOLE\b", text)),
        "functions": len(re.findall(r"^\s*function\s+", text, flags=re.M)),
    }


def parse_header_diagnostics(text: str) -> dict[str, str]:
    mismatches: list[str] = []
    ro_snapshot = "n/a"
    parsed_any = False

    for match in HEADER_FIELD_RE.finditer(text):
        parsed_any = True
        field = match.group(1)
        label = HEADER_FIELD_ALIASES.get(field, field)
        line = match.group(0)
        is_mismatch = line.rstrip().endswith(" mismatch")
        if field == "read_only_snapshot_checksum":
            ro_snapshot = "mismatch" if is_mismatch else "ok"
        if is_mismatch:
            mismatches.append(label)

    if not parsed_any:
        return {"header_mismatch": "n/a", "ro_snapshot": "n/a"}
    return {
        "header_mismatch": ",".join(mismatches) if mismatches else "ok",
        "ro_snapshot": ro_snapshot,
    }


def read_mode_header_diagnostics(case_dir: Path, case: str, mode: str) -> dict[str, str]:
    for suffix in ("checkversion.txt", "disasm.err"):
        path = case_dir / f"{case}.{mode}.{suffix}"
        if not path.exists():
            continue
        diagnostics = parse_header_diagnostics(
            path.read_text(encoding="utf-8", errors="ignore")
        )
        if diagnostics["header_mismatch"] != "n/a":
            return diagnostics
    return {"header_mismatch": "n/a", "ro_snapshot": "n/a"}


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
    metadata = out_dir / "metadata.md"
    if metadata.exists():
        print(metadata.read_text(encoding="utf-8", errors="ignore").rstrip())
        print("")
    print("| case | mode | header_mismatch | ro_snapshot | accu_lines | reg_refs | goto_comments | raw_goto | unknown | undefined_fallbacks | holes |")
    print("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    for case_dir in case_dirs:
        case = case_dir.name
        for mode in ("v8asm", "bytenode"):
            header = read_mode_header_diagnostics(case_dir, case, mode)
            dec = case_dir / f"{case}.{mode}.dec.l4.js"
            if not dec.exists():
                print(
                    f"| {case} | {mode} | {header['header_mismatch']} | "
                    f"{header['ro_snapshot']} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
                )
                continue
            text = dec.read_text(encoding="utf-8", errors="ignore")
            s = score_text(text)
            print(
                f"| {case} | {mode} | {header['header_mismatch']} | "
                f"{header['ro_snapshot']} | {s['accu_lines']} | {s['reg_refs']} | "
                f"{s['goto_comments']} | {s['raw_goto']} | {s['unknown_comments']} | "
                f"{s['undefined_fallbacks']} | {s['holes']} |"
            )

    print("")
    print("## Quick Inspection Targets")
    print("- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.")
    print("- Any non-zero `raw_goto` indicates structurer fallback/regression.")
    print("- Non-zero `unknown` usually means translator opcode coverage is missing.")
    print("- Non-zero `undefined_fallbacks` with `ro_snapshot=mismatch` points at V8/embedder snapshot object recovery, not Python translation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
