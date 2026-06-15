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
UNRESOLVED_OBJECT_CHUNK_OFFSET_RE = re.compile(
    r"object_chunk_offset=(0x[0-9a-fA-F]+)"
)
CURRENT_RO_OBJECT_RE = re.compile(
    r"current_ro_object=\[(0x[0-9a-fA-F]+),(0x[0-9a-fA-F]+)\) "
    r"delta=(0x[0-9a-fA-F]+) hit=([a-z]+)"
)
FUNCTION_RE = re.compile(r"^function\s+([A-Za-z_$][A-Za-z0-9_$]*|bytecode_[0-9a-fA-F]+)\(")
CONSTANT_POOL_ENTRY_RE = re.compile(r"^\s*//\s+\[(\d+)\]\s+=\s+(.+)$")
UNDEFINED_PLACEHOLDER_RE = re.compile(r"<undefined: segmentfault[^>]*>")


class UnresolvedDiagnostics(TypedDict):
    unresolved_objects: int
    unresolved_suffixes: list[str]
    object_chunk_offsets: list[str]
    current_ro_objects: list[str]


class ConstantPoolEntry(TypedDict):
    function_ordinal: int
    function_name: str
    index: int
    value: str


class PlaceholderNameHint(TypedDict):
    case: str
    function_name: str
    constant_index: int
    object_chunk_offsets: list[str]
    placeholder: str
    self_value: str


class PlaceholderOffsetSummary(TypedDict):
    object_chunk_offset: str
    self_values: list[str]
    cases: list[str]
    current_ro_objects: list[str]


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


def count_raw_gotos(text: str) -> int:
    return len(
        re.findall(
            r"^\s*(?:if \(.+\)\s+)?goto\s+offset_",
            text,
            flags=re.M,
        )
    )


def score_text(text: str) -> dict[str, int]:
    return {
        "accu_lines": len(re.findall(r"^\s*ACCU\s*=", text, flags=re.M)),
        "reg_refs": len(re.findall(r"\br\d+\b", text)),
        "goto_comments": len(re.findall(r"//\s*goto\s+offset_", text)),
        "raw_goto": count_raw_gotos(text),
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


def unresolved_object_chunk_offsets(text: str) -> set[str]:
    offsets: set[str] = set()
    for match in UNRESOLVED_OBJECT_CHUNK_OFFSET_RE.finditer(text):
        offsets.add(f"0x{int(match.group(1), 16):x}")
    return offsets


def unresolved_current_ro_objects(text: str) -> set[str]:
    objects: set[str] = set()
    for match in CURRENT_RO_OBJECT_RE.finditer(text):
        start = f"0x{int(match.group(1), 16):x}"
        end = f"0x{int(match.group(2), 16):x}"
        delta = f"0x{int(match.group(3), 16):x}"
        hit = match.group(4)
        objects.add(f"{hit}+{delta}@[{start},{end})")
    return objects


def current_ro_objects_by_chunk_offset(text: str) -> dict[str, set[str]]:
    objects: dict[str, set[str]] = {}
    for line in text.splitlines():
        offsets = sorted(unresolved_object_chunk_offsets(line))
        if not offsets:
            continue
        current_ro_objects = sorted(unresolved_current_ro_objects(line))
        if not current_ro_objects:
            continue
        for offset in offsets:
            objects.setdefault(offset, set()).update(current_ro_objects)
    return objects


def parse_constant_pool_entries(text: str) -> dict[tuple[int, int], ConstantPoolEntry]:
    entries: dict[tuple[int, int], ConstantPoolEntry] = {}
    function_ordinal = -1
    function_name = "<module>"

    for line in text.splitlines():
        stripped = line.strip()
        function_match = FUNCTION_RE.match(stripped)
        if function_match:
            function_ordinal += 1
            function_name = function_match.group(1)
            continue

        entry_match = CONSTANT_POOL_ENTRY_RE.match(line)
        if not entry_match or function_ordinal < 0:
            continue
        index = int(entry_match.group(1))
        entries[(function_ordinal, index)] = {
            "function_ordinal": function_ordinal,
            "function_name": function_name,
            "index": index,
            "value": entry_match.group(2).strip(),
        }
    return entries


def infer_placeholder_name_hints(case_dir: Path, case: str) -> list[PlaceholderNameHint]:
    v8asm_dec = case_dir / f"{case}.v8asm.dec.l4.js"
    bytenode_dec = case_dir / f"{case}.bytenode.dec.l4.js"
    if not v8asm_dec.exists() or not bytenode_dec.exists():
        return []

    v8_entries = parse_constant_pool_entries(
        v8asm_dec.read_text(encoding="utf-8", errors="ignore")
    )
    v8_entries_by_name_index: dict[tuple[str, int], ConstantPoolEntry | None] = {}
    for entry in v8_entries.values():
        key = (entry["function_name"], entry["index"])
        if key in v8_entries_by_name_index:
            v8_entries_by_name_index[key] = None
        else:
            v8_entries_by_name_index[key] = entry

    bytenode_entries = parse_constant_pool_entries(
        bytenode_dec.read_text(encoding="utf-8", errors="ignore")
    )
    hints: list[PlaceholderNameHint] = []
    seen: set[tuple[int, int, str]] = set()

    for key, bytenode_entry in sorted(bytenode_entries.items()):
        placeholder_match = UNDEFINED_PLACEHOLDER_RE.search(bytenode_entry["value"])
        if not placeholder_match:
            continue
        v8_entry = v8_entries.get(key)
        if not v8_entry:
            v8_entry = v8_entries_by_name_index.get(
                (bytenode_entry["function_name"], bytenode_entry["index"])
            )
        if not v8_entry or UNDEFINED_PLACEHOLDER_RE.search(v8_entry["value"]):
            continue
        placeholder = placeholder_match.group(0)
        seen_key = (key[0], key[1], placeholder)
        if seen_key in seen:
            continue
        seen.add(seen_key)
        offsets = sorted(unresolved_object_chunk_offsets(placeholder))
        hints.append(
            {
                "case": case,
                "function_name": bytenode_entry["function_name"],
                "constant_index": bytenode_entry["index"],
                "object_chunk_offsets": offsets,
                "placeholder": placeholder,
                "self_value": v8_entry["value"],
            }
        )

    return hints


def summarize_placeholder_offsets(
    hints: list[PlaceholderNameHint],
    current_ro_by_offset: dict[str, set[str]],
) -> list[PlaceholderOffsetSummary]:
    grouped: dict[str, dict[str, set[str]]] = {}
    for hint in hints:
        for offset in hint["object_chunk_offsets"]:
            entry = grouped.setdefault(
                offset,
                {"self_values": set(), "cases": set(), "current_ro_objects": set()},
            )
            entry["self_values"].add(hint["self_value"])
            entry["cases"].add(hint["case"])
            entry["current_ro_objects"].update(current_ro_by_offset.get(offset, set()))

    return [
        {
            "object_chunk_offset": offset,
            "self_values": sorted(values["self_values"]),
            "cases": sorted(values["cases"]),
            "current_ro_objects": sorted(values["current_ro_objects"]),
        }
        for offset, values in sorted(
            grouped.items(), key=lambda item: int(item[0], 16)
        )
    ]


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
        return {
            "unresolved_objects": 0,
            "unresolved_suffixes": [],
            "object_chunk_offsets": [],
            "current_ro_objects": [],
        }
    text = path.read_text(encoding="utf-8", errors="ignore")
    suffixes = sorted(unresolved_object_suffixes(text))
    return {
        "unresolved_objects": len(unresolved_object_addresses(text)),
        "unresolved_suffixes": suffixes,
        "object_chunk_offsets": sorted(unresolved_object_chunk_offsets(text)),
        "current_ro_objects": sorted(unresolved_current_ro_objects(text)),
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
    unresolved_rows: list[tuple[str, str, list[str], list[str], list[str]]] = []
    placeholder_hints: list[PlaceholderNameHint] = []
    current_ro_by_offset: dict[str, set[str]] = {}
    for case_dir in case_dirs:
        case = case_dir.name
        placeholder_hints.extend(infer_placeholder_name_hints(case_dir, case))
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
            object_chunk_offsets = list(unresolved["object_chunk_offsets"])
            current_ro_objects = list(unresolved["current_ro_objects"])
            disasm_path = case_dir / f"{case}.{mode}.disasm.txt"
            if disasm_path.exists():
                for offset, objects in current_ro_objects_by_chunk_offset(
                    disasm_path.read_text(encoding="utf-8", errors="ignore")
                ).items():
                    current_ro_by_offset.setdefault(offset, set()).update(objects)
            if suffixes:
                unresolved_rows.append(
                    (case, mode, suffixes, object_chunk_offsets, current_ro_objects)
                )
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
        print("| case | mode | suffixes | object_chunk_offsets | current_ro_objects |")
        print("|---|---:|---|---|---|")
        for (
            case,
            mode,
            suffixes,
            object_chunk_offsets,
            current_ro_objects,
        ) in unresolved_rows:
            offsets = ",".join(object_chunk_offsets) if object_chunk_offsets else "n/a"
            current = ",".join(current_ro_objects) if current_ro_objects else "n/a"
            print(
                f"| {case} | {mode} | `{','.join(suffixes)}` | `{offsets}` | "
                f"`{current}` |"
            )

    if placeholder_hints:
        print("")
        print("## Bytenode Placeholder Name Hints")
        print("")
        print("| case | function | cp_index | object_chunk_offsets | bytenode_placeholder | self_cache_value |")
        print("|---|---|---:|---|---|---|")
        for hint in placeholder_hints:
            offsets = (
                ",".join(hint["object_chunk_offsets"])
                if hint["object_chunk_offsets"]
                else "n/a"
            )
            print(
                f"| {hint['case']} | {hint['function_name']} | "
                f"{hint['constant_index']} | `{offsets}` | "
                f"`{hint['placeholder']}` | `{hint['self_value']}` |"
            )

        placeholder_summaries = summarize_placeholder_offsets(
            placeholder_hints, current_ro_by_offset
        )
        if placeholder_summaries:
            print("")
            print("## Bytenode Placeholder Offset Summary")
            print("")
            print("| object_chunk_offset | self_cache_values | cases | current_ro_objects |")
            print("|---:|---|---|---|")
            for summary in placeholder_summaries:
                values = ",".join(summary["self_values"])
                cases = ",".join(summary["cases"])
                current = (
                    ",".join(summary["current_ro_objects"])
                    if summary["current_ro_objects"]
                    else "n/a"
                )
                print(
                    f"| `{summary['object_chunk_offset']}` | `{values}` | "
                    f"`{cases}` | `{current}` |"
                )

    print("")
    print("## Quick Inspection Targets")
    print("- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.")
    print("- Any non-zero `raw_goto` indicates structurer fallback/regression.")
    print("- Non-zero `unknown` usually means translator opcode coverage is missing.")
    print(
        "- Non-zero `undefined_fallbacks` with `ro_snapshot=mismatch` points at "
        "V8/embedder snapshot object recovery, not Python translation."
    )
    print(
        "- Non-zero `unresolved_objects` counts unique object-print failures in "
        "the disasm, before Python decompilation; `object_chunk_offsets` and "
        "`current_ro_objects` are printed by newer v8asm builds."
    )
    print(
        "- `Bytenode Placeholder Name Hints` compares bytenode constant-pool "
        "placeholders with the same case's self-cache constant pool. Treat it "
        "as a root-cause aid for snapshot/RO-heap recovery, not as a Python "
        "name substitution source."
    )
    print(
        "- `Bytenode Placeholder Offset Summary` groups those hints by "
        "`object_chunk_offset`, which is the most stable locator for V8-side "
        "read-only heap investigation."
    )
    if failure_count:
        print("")
        print("## Failures")
        print(f"- {failure_count} mode(s) failed before a usable decompile output.")
        return 0 if allow_failures else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
