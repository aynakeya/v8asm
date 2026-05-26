from __future__ import annotations

import re
from typing import List

from postprocess_level4_common import _extract_indent


def recover_undefined_default_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        interleaved = _match_undefined_default_with_interleaved_saves(lines, i)
        if interleaved is not None:
            rendered, consumed = interleaved
            out.extend(rendered)
            i = consumed
            continue

        if i + 7 < len(lines):
            s = [lines[i + offset].strip() for offset in range(8)]
            m_initial = re.match(r"^ACCU\s*=\s*(.+)$", s[0])
            m_fallback = re.match(r"^ACCU\s*=\s*(.+)$", s[2])
            m_else = re.match(r"^ACCU\s*=\s*(.+)$", s[5])
            m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s[7])
            if (
                m_initial
                and m_fallback
                and m_else
                and m_store
                and s[1] == "if (!(ACCU !== undefined)) {"
                and s[3] == "}"
                and s[4] == "else {"
                and s[6] == "}"
            ):
                initial = m_initial.group(1).strip()
                fallback = m_fallback.group(1).strip()
                else_expr = m_else.group(1).strip()
                if "ACCU" not in initial and "ACCU" not in fallback and "ACCU" not in else_expr:
                    dest = m_store.group(1)
                    expr = f"({initial} === undefined ? {fallback} : {else_expr})"
                    indent = _extract_indent(lines[i + 7])
                    out.append(f"{indent}{dest} = {expr}")
                    if i + 8 < len(lines):
                        rewritten = _rewrite_immediate_accu_consumer(lines[i + 8], dest)
                        if rewritten is not None:
                            out.append(rewritten)
                            i += 9
                            continue
                    i += 8
                    continue

        if i + 4 < len(lines):
            s = [lines[i + offset].strip() for offset in range(5)]
            m_initial = re.match(r"^ACCU\s*=\s*(.+)$", s[0])
            m_fallback = re.match(r"^ACCU\s*=\s*(.+)$", s[2])
            m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s[4])
            if (
                m_initial
                and m_fallback
                and m_store
                and s[1] == "if (!(ACCU !== undefined)) {"
                and s[3] == "}"
            ):
                initial = m_initial.group(1).strip()
                fallback = m_fallback.group(1).strip()
                if "ACCU" not in initial and "ACCU" not in fallback:
                    dest = m_store.group(1)
                    expr = f"({initial} === undefined ? {fallback} : {initial})"
                    indent = _extract_indent(lines[i + 4])
                    out.append(f"{indent}{dest} = {expr}")
                    if i + 5 < len(lines):
                        rewritten = _rewrite_immediate_accu_consumer(lines[i + 5], dest)
                        if rewritten is not None:
                            out.append(rewritten)
                            i += 6
                            continue
                    i += 5
                    continue

        out.append(lines[i])
        i += 1
    return out


def _match_undefined_default_with_interleaved_saves(
    lines: List[str], start: int
) -> tuple[List[str], int] | None:
    if start + 5 >= len(lines):
        return None

    initial_match = re.match(r"^ACCU\s*=\s*(.+)$", lines[start].strip())
    if not initial_match:
        return None
    initial = initial_match.group(1).strip()
    if "ACCU" in initial:
        return None

    cursor = start + 1
    saved_lines: List[str] = []
    while cursor < len(lines) and len(saved_lines) < 3:
        stripped = lines[cursor].strip()
        if stripped == "if (!(ACCU !== undefined)) {":
            break
        if not _is_simple_reg_save(stripped):
            return None
        saved_lines.append(lines[cursor])
        cursor += 1

    if not saved_lines or cursor + 3 >= len(lines):
        return None

    s_if = lines[cursor].strip()
    s_fallback = lines[cursor + 1].strip()
    s_close = lines[cursor + 2].strip()
    s_store = lines[cursor + 3].strip()
    fallback_match = re.match(r"^ACCU\s*=\s*(.+)$", s_fallback)
    store_match = re.match(r"^(r\d+)\s*=\s*ACCU$", s_store)
    if (
        s_if != "if (!(ACCU !== undefined)) {"
        or not fallback_match
        or s_close != "}"
        or not store_match
    ):
        return None

    fallback = fallback_match.group(1).strip()
    if "ACCU" in fallback:
        return None

    dest = store_match.group(1)
    indent = _extract_indent(lines[cursor + 3])
    rendered = saved_lines[:]
    rendered.append(f"{indent}{dest} = ({initial} === undefined ? {fallback} : {initial})")
    return rendered, cursor + 4


def _is_simple_reg_save(stripped: str) -> bool:
    match = re.match(r"^r\d+\s*=\s*(.+)$", stripped)
    if not match:
        return False
    expr = match.group(1).strip()
    if "ACCU" in expr or "(" in expr:
        return False
    return bool(
        re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?", expr)
        or re.fullmatch(r"[-+]?\d+", expr)
        or expr in {"true", "false", "null", "undefined", "this", "closure", "context"}
    )


def _rewrite_immediate_accu_consumer(line: str, replacement: str) -> str | None:
    stripped = line.strip()
    match = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
    if not match:
        return None
    rhs = match.group(1).strip()
    if "ACCU" not in rhs:
        return None
    indent = _extract_indent(line)
    rhs = re.sub(r"\bACCU\b", replacement, rhs)
    return f"{indent}ACCU = {rhs}"
