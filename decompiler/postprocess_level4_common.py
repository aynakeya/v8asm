from __future__ import annotations

import re
from typing import Dict, List, Optional

def _find_block_end(lines: List[str], start: int) -> Optional[int]:
    depth = 0
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip()
        if stripped.endswith("{"):
            depth += 1
        if stripped == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None

def _extract_indent(line: str) -> str:
    stripped = line.lstrip()
    return line[: len(line) - len(stripped)]

def _compact_compound_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("ACCU = ") and i + 2 < len(lines):
            expr = s[len("ACCU = ") :]
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            s3 = lines[i + 3].strip() if i + 3 < len(lines) else ""
            m = re.match(r"^ACCU = \((r\d+) \+ ACCU\)$", s1)
            if not m:
                m = re.match(r"^ACCU = \(ACCU \+ (r\d+)\)$", s1)
            if m and s2 == f"{m.group(1)} = ACCU":
                indent = _extract_indent(lines[i + 2])
                out.append(f"{indent}{m.group(1)} += {expr}")
                i += 3
                continue
            if (
                m
                and re.match(r"^r\d+ = " + re.escape(m.group(1)) + r"$", s2)
                and s3 == f"{m.group(1)} = ACCU"
            ):
                indent = _extract_indent(lines[i + 3])
                out.append(f"{indent}{m.group(1)} += {expr}")
                i += 4
                continue
            m2 = re.match(r"^ACCU = \(ACCU \+ ([-+]?\d+)\)$", s1)
            if m2 and re.match(r"^r\d+ = ACCU$", s2):
                dst = s2.split("=", 1)[0].strip()
                if expr == dst:
                    indent = _extract_indent(lines[i + 2])
                    out.append(f"{indent}{dst} += {m2.group(1)}")
                    i += 3
                    continue

        if out and out[-1].strip() == s and s.startswith("ACCU = "):
            i += 1
            continue

        out.append(lines[i])
        i += 1
    return out

def _drop_unused_reg_assignments(lines: List[str]) -> List[str]:
    usage = _count_reg_uses(lines)
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^(r\d+)\s*=\s*(.+)$", stripped)
        if m and usage.get(m.group(1), 0) == 0:
            continue
        out.append(line)
    return out

def _count_reg_uses(lines: List[str]) -> Dict[str, int]:
    usage: Dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        assign = re.match(r"^(r\d+)\s*=", stripped)
        lhs = assign.group(1) if assign else None
        for reg in re.findall(r"\br\d+\b", stripped):
            if reg == lhs and stripped.startswith(f"{reg} ="):
                continue
            usage[reg] = usage.get(reg, 0) + 1
    return usage
