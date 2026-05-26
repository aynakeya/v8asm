from __future__ import annotations

import re
from typing import List, Optional, Tuple

from postprocess_level4_common import (
    _compact_compound_assignments,
    _drop_unused_reg_assignments,
    _extract_indent,
    _find_block_end,
)

def _parse_iter_setup(lines: List[str]) -> Optional[Tuple[int, int, str, str, str]]:
    for i in range(len(lines) - 3):
        s0 = lines[i].strip()
        s1 = lines[i + 1].strip()
        s2 = lines[i + 2].strip()
        s3 = lines[i + 3].strip()

        if not s0.startswith("ACCU = GetIterator(") or not s0.endswith(")"):
            continue
        source = s0[len("ACCU = GetIterator(") : -1]
        m1 = re.match(r"^(r\d+) = GetIterator\((.+)\)$", s1)
        if not m1:
            continue
        iter_reg = m1.group(1)
        if m1.group(2) != source:
            continue
        m2 = re.match(rf"^ACCU = {re.escape(iter_reg)}\.next$", s2)
        m3 = re.match(rf"^(r\d+) = {re.escape(iter_reg)}\.next$", s3)
        if not m2 or not m3:
            continue
        next_reg = m3.group(1)
        return i, i + 3, source, iter_reg, next_reg
    return None

def _recover_for_of(lines: List[str]) -> List[str]:
    setup = _parse_iter_setup(lines)
    if not setup:
        return lines
    setup_start, setup_end, source, iter_reg, next_reg = setup

    while_idx = None
    while_end = None
    for i in range(setup_end + 1, len(lines)):
        if lines[i].strip() != "while (!(truthy(ACCU))) {":
            continue
        end = _find_block_end(lines, i)
        if end is None:
            continue
        while_idx = i
        while_end = end
        break
    if while_idx is None or while_end is None:
        return lines

    body = lines[while_idx + 1 : while_end]
    next_call_a = f"ACCU = {next_reg}.call({iter_reg})"
    next_call_b = re.compile(rf"^(r\d+) = {re.escape(next_reg)}\.call\({re.escape(iter_reg)}\)$")
    result_reg = None
    for line in body:
        s = line.strip()
        if next_call_a == s:
            continue
        m = next_call_b.match(s)
        if m:
            result_reg = m.group(1)
            break
    if not result_reg:
        return lines

    flag_reg = None
    for line in body:
        m_flag = re.match(r"^(r\d+) = true$", line.strip())
        if m_flag:
            flag_reg = m_flag.group(1)
            break

    inner_if_start = None
    inner_if_end = None
    for idx in range(while_idx + 1, while_end):
        if lines[idx].strip() == "if (!(truthy(ACCU))) {":
            end = _find_block_end(lines, idx)
            if end is None or end > while_end:
                continue
            inner_if_start = idx
            inner_if_end = end
            break
    if inner_if_start is None or inner_if_end is None:
        return lines

    inner_body = lines[inner_if_start + 1 : inner_if_end]
    loop_var = None
    assign_re = re.compile(rf"^(r\d+) = {re.escape(result_reg)}$")
    for line in inner_body:
        m = assign_re.match(line.strip())
        if m:
            loop_var = m.group(1)
            break
    if not loop_var:
        loop_var = "item"

    filtered: List[str] = []
    for line in inner_body:
        s = line.strip()
        if s in {"ACCU = false", "ACCU = true"}:
            continue
        if s == f"{loop_var} = {result_reg}":
            continue
        if s in {f"r6 = false", f"r6 = true"}:
            continue
        if s == f"ACCU = {result_reg}.value":
            s = f"ACCU = {loop_var}"
        elif s == f"{result_reg} = {result_reg}.value":
            continue
        elif s == f"{loop_var} = {result_reg}":
            continue
        if f"{result_reg}.value" in s:
            s = re.sub(rf"\b{re.escape(result_reg)}\.value\b", loop_var, s)
        if s.startswith(f"{loop_var} ="):
            continue
        m_noop = re.match(r"^(r\d+) = \1$", s)
        if m_noop:
            continue
        filtered.append(s)
    filtered = _compact_compound_assignments(filtered)
    filtered = _drop_unused_reg_assignments(filtered)

    loop_var_name = "item"
    body_text = "\n".join(filtered)
    if re.search(r"\bitem\b", body_text):
        loop_var_name = "item1"
    if loop_var_name != loop_var:
        filtered = [
            re.sub(rf"\b{re.escape(loop_var)}\b", loop_var_name, stmt) for stmt in filtered
        ]

    if result_reg != loop_var_name:
        needs_alias = any(re.search(rf"\b{re.escape(result_reg)}\b", stmt) for stmt in filtered)
        if needs_alias:
            filtered.insert(0, f"{result_reg} = {loop_var_name}")

    while_indent = _extract_indent(lines[while_idx])
    body_indent = while_indent + "  "
    replacement = [f"{while_indent}for (const {loop_var_name} of {source}) {{"]
    for stmt in filtered:
        replacement.append(f"{body_indent}{stmt}")
    replacement.append(f"{while_indent}}}")

    out: List[str] = []
    skip_ranges: List[Tuple[int, int]] = []
    if flag_reg:
        for idx in range(while_end + 1, len(lines) - 1):
            if lines[idx].strip() != f"ACCU = {flag_reg}":
                continue
            if lines[idx + 1].strip() != "if (!(truthy(ACCU))) {":
                continue
            end = _find_block_end(lines, idx + 1)
            if end is None:
                continue
            block_text = "\n".join(lines[idx + 1 : end + 1])
            if f"{iter_reg}.return" not in block_text:
                continue
            start = idx
            if idx >= 4:
                p0 = lines[idx - 4].strip()
                p1 = lines[idx - 3].strip()
                p2 = lines[idx - 2].strip()
                p3 = lines[idx - 1].strip()
                if (
                    p0 == "ACCU = -1"
                    and re.match(r"^r\d+ = -1$", p1)
                    and re.match(r"^r\d+ = -1$", p2)
                    and p3.startswith("// goto offset_")
                ):
                    start = idx - 4
            skip_ranges.append((start, end))
            break

    def in_skip_ranges(i: int) -> bool:
        for a, b in skip_ranges:
            if a <= i <= b:
                return True
        return False

    for idx, line in enumerate(lines):
        if in_skip_ranges(idx):
            continue
        if setup_start <= idx <= setup_end:
            continue
        if idx == while_idx:
            out.extend(replacement)
            continue
        if while_idx < idx <= while_end:
            continue
        out.append(line)
    return out

def _strip_for_of_state_initializers(lines: List[str]) -> List[str]:
    remove: set[int] = set()
    for i, line in enumerate(lines):
        if not line.strip().startswith("for ("):
            continue

        j = i - 1
        if j >= 0 and re.match(r"^\s*r\d+\s*=\s*context$", lines[j]):
            remove.add(j)
            j -= 1

        while j >= 0:
            s_cur = lines[j].strip()
            if re.match(r"^r\d+\s*=\s*(?:true|false|HOLE)$", s_cur):
                remove.add(j)
                j -= 1
                continue
            break

        while j - 1 >= 0:
            s_prev = lines[j - 1].strip()
            s_cur = lines[j].strip()
            if s_prev == "ACCU = HOLE" and re.match(r"^r\d+\s*=\s*HOLE$", s_cur):
                remove.update({j - 1, j})
                j -= 2
                continue
            if s_prev == "ACCU = false" and re.match(r"^r\d+\s*=\s*false$", s_cur):
                remove.update({j - 1, j})
                j -= 2
                continue
            break

    return [line for idx, line in enumerate(lines) if idx not in remove]

def _accu_used_before_reassign_or_block_end(lines: List[str], start: int, end: int) -> bool:
    for idx in range(start, min(end + 1, len(lines))):
        stripped = lines[idx].strip()
        if re.match(r"^ACCU\s*=", stripped):
            return False
        if re.search(r"\bACCU\b", stripped):
            return True
    return False

def _reg_used_before_reassign_or_block_end(
    lines: List[str], reg: str, start: int, end: int
) -> bool:
    for idx in range(start, min(end + 1, len(lines))):
        stripped = lines[idx].strip()
        if re.match(rf"^{re.escape(reg)}\s*=", stripped):
            return False
        if re.search(rf"\b{re.escape(reg)}\b", stripped):
            return True
    return False

def _strip_for_of_recovery_noise(lines: List[str]) -> List[str]:
    remove: set[int] = set()
    active_loops: List[Tuple[int, str]] = []

    for idx, line in enumerate(lines):
        active_loops = [(end, var) for end, var in active_loops if idx <= end]
        stripped = line.strip()

        m_for = re.match(r"^for \(const ([A-Za-z_$][A-Za-z0-9_$]*) of .+\) \{$", stripped)
        if m_for:
            end = _find_block_end(lines, idx)
            if end is not None:
                active_loops.append((end, m_for.group(1)))
            continue

        if not active_loops:
            continue

        loop_end = min(end for end, _var in active_loops)
        loop_vars = {var for _end, var in active_loops}

        m_accu = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
        if m_accu and m_accu.group(1).strip() in loop_vars:
            if not _accu_used_before_reassign_or_block_end(lines, idx + 1, loop_end):
                remove.add(idx)
            continue

        m_bool = re.match(r"^(r\d+)\s*=\s*(?:true|false)$", stripped)
        if m_bool and not _reg_used_before_reassign_or_block_end(
            lines, m_bool.group(1), idx + 1, loop_end
        ):
            remove.add(idx)

    return [line for idx, line in enumerate(lines) if idx not in remove]

def _avoid_for_of_loop_var_source_collision(lines: List[str]) -> List[str]:
    out = lines[:]
    idx = 0
    while idx < len(out):
        stripped = out[idx].strip()
        m_for = re.match(
            r"^(for \(const )([A-Za-z_$][A-Za-z0-9_$]*)( of (.+)\) \{)$", stripped
        )
        if not m_for:
            idx += 1
            continue

        var = m_for.group(2)
        source = m_for.group(4)
        if not re.search(rf"\b{re.escape(var)}\b", source):
            idx += 1
            continue

        end = _find_block_end(out, idx)
        if end is None:
            idx += 1
            continue

        suffix = 1
        new_var = f"{var}{suffix}"
        block_text = "\n".join(out[idx : end + 1])
        while re.search(rf"\b{re.escape(new_var)}\b", block_text):
            suffix += 1
            new_var = f"{var}{suffix}"

        indent = _extract_indent(out[idx])
        out[idx] = f"{indent}{m_for.group(1)}{new_var}{m_for.group(3)}"
        for body_idx in range(idx + 1, end):
            out[body_idx] = re.sub(rf"\b{re.escape(var)}\b", new_var, out[body_idx])

        idx = end + 1
    return out
