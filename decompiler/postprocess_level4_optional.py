from __future__ import annotations

import re
from typing import List, Optional, Tuple

from postprocess_level4_common import _extract_indent, _find_block_end


def recover_optional_chains(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        recovered = _try_recover_optional_chain(lines, i)
        if recovered is not None:
            replacement, next_i = recovered
            out.append(replacement)
            i = next_i
            continue
        out.append(lines[i])
        i += 1
    return out


def _try_recover_optional_chain(lines: List[str], start: int) -> Optional[Tuple[str, int]]:
    if start + 2 >= len(lines):
        return None
    s0 = lines[start].strip()
    s1 = lines[start + 1].strip()
    m_base = re.match(r"^ACCU\s*=\s*(.+)$", s0)
    m_reg = re.match(r"^(r\d+)\s*=\s*(.+)$", s1)
    if not m_base or not m_reg:
        return None
    base = m_base.group(1).strip()
    reg, reg_value = m_reg.groups()
    if base != reg_value.strip() or "ACCU" in base:
        return None

    parsed = _parse_optional_guard(lines, start + 2, reg, base)
    if parsed is None:
        return None
    expr, next_i = parsed
    return f"{_extract_indent(lines[start])}ACCU = {expr}", next_i


def _parse_optional_guard(
    lines: List[str], guard_idx: int, reg: str, expr: str
) -> Optional[Tuple[str, int]]:
    if guard_idx >= len(lines) or lines[guard_idx].strip() != "if (!(isNullish(ACCU))) {":
        return None

    then_end = _find_block_end(lines, guard_idx)
    if then_end is None or then_end + 3 >= len(lines):
        return None
    if lines[then_end + 1].strip() != "else {":
        return None
    else_end = _find_block_end(lines, then_end + 1)
    if else_end is None:
        return None
    else_body = [line.strip() for line in lines[then_end + 2 : else_end] if line.strip()]
    if else_body != ["ACCU = undefined"]:
        return None

    body_start = guard_idx + 1
    if body_start >= then_end:
        return None
    read = _match_reg_read(lines[body_start].strip(), reg)
    if read is None:
        return None
    next_expr = _append_optional_access(expr, read)

    if body_start + 1 == then_end:
        return next_expr, else_end + 1

    if body_start + 2 <= then_end:
        store = lines[body_start + 1].strip()
        if store == f"{reg} = {read}":
            nested = _parse_optional_guard(lines, body_start + 2, reg, next_expr)
            if nested is not None and nested[1] == then_end:
                return nested[0], else_end + 1

    return None


def _match_reg_read(line: str, reg: str) -> Optional[str]:
    match = re.match(r"^ACCU\s*=\s*(.+)$", line)
    if not match:
        return None
    read = match.group(1).strip()
    if read.startswith(f"{reg}.") or read.startswith(f"{reg}["):
        return read
    return None


def _append_optional_access(expr: str, read: str) -> str:
    dot = re.match(r"^r\d+\.([A-Za-z_$][A-Za-z0-9_$]*)$", read)
    if dot:
        return f"{expr}?.{dot.group(1)}"
    keyed = re.match(r"^r\d+\[(.+)\]$", read)
    if keyed:
        return f"{expr}?.[{keyed.group(1).strip()}]"
    return f"{expr}?.[{read}]"
