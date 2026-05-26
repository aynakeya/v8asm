from __future__ import annotations

import re
from typing import List, Optional, Tuple

from postprocess_level4_common import _extract_indent


def _format_string_part(expr: str, stringify: bool) -> str:
    expr = expr.strip()
    if stringify:
        return f"String({expr})"
    return expr


def _read_accu_part(lines: List[str], start: int) -> Optional[Tuple[str, bool, int]]:
    if start >= len(lines):
        return None
    s0 = lines[start].strip()
    if s0 == "ACCU = String(ACCU)":
        return "ACCU", True, start + 1

    m_value = re.match(r"^ACCU = (.+)$", s0)
    if not m_value:
        return None
    expr = m_value.group(1).strip()
    cursor = start + 1
    stringify = False
    if cursor < len(lines) and lines[cursor].strip() == "ACCU = String(ACCU)":
        stringify = True
        cursor += 1
    return expr, stringify, cursor


def _has_following_concat_append(lines: List[str], start: int, reg: str) -> bool:
    part = _read_accu_part(lines, start)
    if not part:
        return False
    _expr, _stringify, cursor = part
    if cursor + 1 >= len(lines):
        return False
    return (
        lines[cursor].strip() == f"ACCU = ({reg} + ACCU)"
        and lines[cursor + 1].strip() == f"{reg} = ACCU"
    )


def _compact_string_concat_chains(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        part = _read_accu_part(lines, i)
        if part:
            expr, stringify, cursor = part
            formatted = _format_string_part(expr, stringify)

            if cursor < len(lines):
                m_base = re.match(r"^(r\d+) = ACCU$", lines[cursor].strip())
                if m_base:
                    reg = m_base.group(1)
                    if _has_following_concat_append(lines, cursor + 1, reg):
                        indent = _extract_indent(lines[cursor])
                        out.append(f"{indent}{reg} = {formatted}")
                        i = cursor + 1
                        continue

            if cursor + 1 < len(lines):
                m_append = re.match(r"^ACCU = \((r\d+) \+ ACCU\)$", lines[cursor].strip())
                if m_append and lines[cursor + 1].strip() == f"{m_append.group(1)} = ACCU":
                    reg = m_append.group(1)
                    indent = _extract_indent(lines[cursor + 1])
                    out.append(f"{indent}{reg} = ({reg} + {formatted})")
                    i = cursor + 2
                    continue
                if m_append and lines[cursor + 1].strip() == "return ACCU":
                    reg = m_append.group(1)
                    indent = _extract_indent(lines[cursor + 1])
                    out.append(f"{indent}return ({reg} + {formatted})")
                    i = cursor + 2
                    continue

            if cursor < len(lines):
                m_return = re.match(r"^return \((.+) \+ ACCU\)$", lines[cursor].strip())
                if m_return:
                    prefix = m_return.group(1).strip()
                    if "ACCU" in prefix:
                        out.append(lines[i])
                        i += 1
                        continue
                    indent = _extract_indent(lines[cursor])
                    out.append(f"{indent}return ({prefix} + {formatted})")
                    i = cursor + 1
                    continue

            if cursor < len(lines):
                m_return_accu_binary = re.match(
                    r"^return \((.+) \+ String\(\(ACCU\s*([+*])\s*(.+)\)\)\)$",
                    lines[cursor].strip(),
                )
                if m_return_accu_binary:
                    prefix, op, rhs = m_return_accu_binary.groups()
                    prefix = prefix.strip()
                    rhs = rhs.strip()
                    if "ACCU" not in prefix and "ACCU" not in expr + rhs:
                        indent = _extract_indent(lines[cursor])
                        out.append(f"{indent}return ({prefix} + String(({expr} {op} {rhs})))")
                        i = cursor + 1
                        continue

        out.append(lines[i])
        i += 1
    return out
