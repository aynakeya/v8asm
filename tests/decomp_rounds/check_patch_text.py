#!/usr/bin/env python3
"""Static checks for v8asm patch invariants.

This catches patch-level regressions before the expensive V8 build matrix:

- metadata commands (`version` and `build-args`) must return before V8 startup
  data is initialized, so sibling snapshots cannot pollute their output;
- build-args must expose `v8_enable_static_roots`, because snapshot startup
  format mismatches show up as `fixed_offset` checks;
- startup snapshot recovery diagnostics must write to stderr, not disassembly
  stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH_DIR = ROOT / "v8patch"


def added_or_plain_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
        else:
            lines.append(line)
    return lines


def first_line(lines: list[str], needle: str) -> int | None:
    for index, line in enumerate(lines, 1):
        if needle in line:
            return index
    return None


def check_patch(path: Path) -> list[str]:
    lines = added_or_plain_lines(path)
    problems: list[str] = []
    init = first_line(lines, "InitializeExternalStartupData")
    version = first_line(lines, 'strcmp(cmd, "version") == 0')
    build_args = first_line(lines, 'strcmp(cmd, "build-args") == 0')
    if not init:
        problems.append("missing InitializeExternalStartupData")
    if not version or not build_args:
        problems.append("missing version/build-args command blocks")
    if init and version and version > init:
        problems.append("version command is handled after V8 startup-data init")
    if init and build_args and build_args > init:
        problems.append("build-args command is handled after V8 startup-data init")
    if not first_line(lines, "v8_enable_static_roots"):
        problems.append("build-args does not print v8_enable_static_roots")

    for index, line in enumerate(lines, 1):
        if "using snapshot external reference table size" not in line:
            continue
        window = "\n".join(lines[max(0, index - 6) : index + 2])
        if "stderr" not in window:
            problems.append(
                f"external-reference table diagnostic near line {index} is not on stderr"
            )
    for index, line in enumerate(lines, 1):
        if "ignored %d startup external reference alias mismatches" not in line:
            continue
        window = "\n".join(lines[max(0, index - 4) : index + 2])
        if "stderr" not in window:
            problems.append(
                f"external-reference alias diagnostic near line {index} is not on stderr"
            )
    return problems


def main() -> int:
    paths = sorted(PATCH_DIR.glob("*.patch")) + [PATCH_DIR / "main.cc"]
    failed = False
    for path in paths:
        problems = check_patch(path)
        print(f"{path.relative_to(ROOT)}: {'ok' if not problems else 'fail'}")
        for problem in problems:
            print(f"  - {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
