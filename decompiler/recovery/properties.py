from __future__ import annotations

import re
from typing import List

from .common import _extract_indent, is_live_after, is_stable_assignment_target

def _compact_keyed_property_reads(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m_key = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_key_store = re.match(r"^(r\d+)\s*=\s*(.+)$", s1)
            m_read = re.match(r"^ACCU\s*=\s*(.+)\[ACCU\]$", s2)
            if m_key and m_key_store and m_read:
                key = m_key.group(1).strip()
                key_reg, stored_key = m_key_store.groups()
                receiver = m_read.group(1).strip()
                if key == stored_key.strip() and "ACCU" not in key and "ACCU" not in receiver:
                    expr = f"{receiver}[{key}]"
                    out.append(lines[i + 1])
                    if i + 3 < len(lines):
                        s3 = lines[i + 3].strip()
                        m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s3)
                        if m_store:
                            indent = _extract_indent(lines[i + 3])
                            if _reads_accu_before_reassign(lines, i + 4):
                                out.append(f"{_extract_indent(lines[i + 2])}ACCU = {expr}")
                                expr = "ACCU"
                            out.append(f"{indent}{m_store.group(1)} = {expr}")
                            i += 4
                            continue
                    indent = _extract_indent(lines[i + 2])
                    out.append(f"{indent}ACCU = {expr}")
                    i += 3
                    continue

        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_key = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_read = re.match(r"^ACCU\s*=\s*(.+)\[ACCU\]$", s1)
            if m_key and m_read:
                key = m_key.group(1).strip()
                receiver = m_read.group(1).strip()
                if "ACCU" not in key and "ACCU" not in receiver:
                    expr = f"{receiver}[{key}]"
                    if i + 2 < len(lines):
                        s2 = lines[i + 2].strip()
                        m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s2)
                        if m_store:
                            indent = _extract_indent(lines[i + 2])
                            if _reads_accu_before_reassign(lines, i + 3):
                                out.append(f"{_extract_indent(lines[i + 1])}ACCU = {expr}")
                                expr = "ACCU"
                            out.append(f"{indent}{m_store.group(1)} = {expr}")
                            i += 3
                            continue
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}ACCU = {expr}")
                    i += 2
                    continue
        out.append(lines[i])
        i += 1
    return out


def _reads_accu_before_reassign(lines: List[str], start: int) -> bool:
    return is_live_after(lines, start, "ACCU")


def _compact_accu_property_stores(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_value = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_store = re.match(r"^(.+)\s*=\s*ACCU$", s1)
            if m_value and m_store:
                target = m_store.group(1).strip()
                value = m_value.group(1).strip()
                if (
                    not re.fullmatch(r"r\d+|ACCU", target)
                    and is_stable_assignment_target(target)
                    and "ACCU" not in value
                    and not is_live_after(lines, i + 2, "ACCU")
                ):
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}{target} = {value}")
                    i += 2
                    continue

        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m_base = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_update = re.match(r"^ACCU\s*=\s*\(ACCU\s*([+*])\s*(.+)\)$", s1)
            m_store = re.match(r"^(.+)\s*=\s*ACCU$", s2)
            if m_base and m_update and m_store:
                target = m_store.group(1).strip()
                base = m_base.group(1).strip()
                op, rhs = m_update.groups()
                rhs = rhs.strip()
                if (
                    not re.fullmatch(r"r\d+|ACCU", target)
                    and is_stable_assignment_target(target)
                    and "ACCU" not in base + rhs
                    and not is_live_after(lines, i + 3, "ACCU")
                ):
                    indent = _extract_indent(lines[i + 2])
                    out.append(f"{indent}{target} = ({base} {op} {rhs})")
                    i += 3
                    continue

        out.append(lines[i])
        i += 1
    return out
