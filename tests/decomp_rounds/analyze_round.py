#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TypedDict


HEADER_FIELD_RE = re.compile(
    r"^\s*(magic|version_hash|flags_hash|read_only_snapshot_checksum|payload_length):\s+.*$",
    flags=re.M,
)
HEADER_FIELD_ALIASES = {
    "read_only_snapshot_checksum": "ro_snapshot",
}
CRASH_SIGNATURE_RE = re.compile(
    r"Segmentation fault|SIGSEGV|SIGTRAP|Trace/breakpoint trap|core dumped|"
    r"Fatal error|FailureMessage|unreachable code|CHECK failed|DCHECK failed|"
    r"AddressSanitizer|heap-use-after-free",
    flags=re.I,
)
UNRESOLVED_OBJECT_RE = re.compile(
    r"(0x[0-9a-fA-F]+)"
    r"(?:: segmentfault(?:, disassemble stop| while discovering object, skipped)"
    r"|\s+<undefined: segmentfault)"
)


class UnresolvedDiagnostics(TypedDict):
    unresolved_objects: int
    unresolved_suffixes: list[str]


def classify_decompile_status(text: str) -> str:
    if "// input jsc not found:" in text:
        return "input_missing"
    if "// disasm failed for" in text:
        return "disasm_failed"
    if "// disasm skipped for" in text:
        return "disasm_skipped"
    if "// decompile failed for" in text:
        return "decompile_failed"
    return "ok"


def mode_has_crash_signature(case_dir: Path, case: str, mode: str) -> bool:
    for suffix in ("disasm.err", "disasm.txt", "decompile.err"):
        path = case_dir / f"{case}.{mode}.{suffix}"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if CRASH_SIGNATURE_RE.search(text):
            return True
    return False


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


def unresolved_object_addresses(text: str) -> set[str]:
    addresses: set[str] = set()
    for match in UNRESOLVED_OBJECT_RE.finditer(text):
        addresses.add(f"0x{int(match.group(1), 16):x}")
    return addresses


def unresolved_object_suffixes(text: str) -> set[str]:
    return {
        f"{int(address, 16) & 0xffff:04x}"
        for address in unresolved_object_addresses(text)
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


def read_mode_unresolved_diagnostics(
    case_dir: Path, case: str, mode: str
) -> UnresolvedDiagnostics:
    path = case_dir / f"{case}.{mode}.disasm.txt"
    if not path.exists():
        return {"unresolved_objects": 0, "unresolved_suffixes": []}
    text = path.read_text(encoding="utf-8", errors="ignore")
    suffixes = sorted(unresolved_object_suffixes(text))
    return {
        "unresolved_objects": len(unresolved_object_addresses(text)),
        "unresolved_suffixes": suffixes,
    }


def main() -> int:
    if len(sys.argv) not in (2, 3) or (
        len(sys.argv) == 3 and sys.argv[2] != "--allow-failures"
    ):
        print("Usage: analyze_round.py <out_dir> [--allow-failures]", file=sys.stderr)
        return 1
    allow_failures = len(sys.argv) == 3 and sys.argv[2] == "--allow-failures"
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
    print("| case | mode | status | header_mismatch | ro_snapshot | accu_lines | reg_refs | goto_comments | raw_goto | unknown | undefined_fallbacks | unresolved_objects | holes |")
    print("|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    failure_count = 0
    unresolved_rows: list[tuple[str, str, list[str]]] = []
    for case_dir in case_dirs:
        case = case_dir.name
        for mode in ("v8asm", "bytenode"):
            header = read_mode_header_diagnostics(case_dir, case, mode)
            unresolved = read_mode_unresolved_diagnostics(case_dir, case, mode)
            dec = case_dir / f"{case}.{mode}.dec.l4.js"
            if not dec.exists():
                failure_count += 1
                print(
                    f"| {case} | {mode} | missing_output | {header['header_mismatch']} | "
                    f"{header['ro_snapshot']} | n/a | n/a | n/a | n/a | n/a | n/a | "
                    f"{unresolved['unresolved_objects']} | n/a |"
                )
                continue
            text = dec.read_text(encoding="utf-8", errors="ignore")
            status = classify_decompile_status(text)
            if mode_has_crash_signature(case_dir, case, mode):
                status = "crash_signature"
            if status != "ok":
                failure_count += 1
            s = score_text(text)
            suffixes = list(unresolved["unresolved_suffixes"])
            if suffixes:
                unresolved_rows.append((case, mode, suffixes))
            print(
                f"| {case} | {mode} | {status} | {header['header_mismatch']} | "
                f"{header['ro_snapshot']} | {s['accu_lines']} | {s['reg_refs']} | "
                f"{s['goto_comments']} | {s['raw_goto']} | {s['unknown_comments']} | "
                f"{s['undefined_fallbacks']} | {unresolved['unresolved_objects']} | "
                f"{s['holes']} |"
            )

    if unresolved_rows:
        print("")
        print("## Unresolved Read-Only Object Suffixes")
        print("")
        print("| case | mode | suffixes |")
        print("|---|---:|---|")
        for case, mode, suffixes in unresolved_rows:
            print(f"| {case} | {mode} | `{','.join(suffixes)}` |")

    print("")
    print("## Quick Inspection Targets")
    print("- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.")
    print("- Any non-zero `raw_goto` indicates structurer fallback/regression.")
    print("- Non-zero `unknown` usually means translator opcode coverage is missing.")
    print("- Non-zero `undefined_fallbacks` with `ro_snapshot=mismatch` points at V8/embedder snapshot object recovery, not Python translation.")
    print("- Non-zero `unresolved_objects` counts unique object-print failures in the disasm, before Python decompilation.")
    if failure_count:
        print("")
        print("## Failures")
        print(f"- {failure_count} mode(s) failed before a usable decompile output.")
        return 0 if allow_failures else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
