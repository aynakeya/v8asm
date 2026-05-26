from __future__ import annotations

import re
from typing import List, Optional, Tuple

from postprocess_level4_common import _count_reg_uses, _extract_indent, _find_block_end


def _compact_fixed_array_builders(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0

    while i < len(lines):
        replacement = _match_fixed_array_builder(lines, i)
        if replacement is None:
            out.append(lines[i])
            i += 1
            continue

        end, rebuilt = replacement
        if out and re.match(r"^\s*ACCU\s*=\s*\[\]$", out[-1]):
            out.pop()
        out.append(rebuilt)
        i = end + 1

    return out


def _match_fixed_array_builder(lines: List[str], start: int) -> Optional[Tuple[int, str]]:
    init = re.match(r"^(\s*)(r\d+)\s*=\s*\[\]$", lines[start])
    if not init:
        return None

    indent, arr_reg = init.groups()
    idx = start + 1
    values: List[str] = []
    index_reg = None
    expected_index = 0

    while idx < len(lines):
        idx = _skip_accu_loads(lines, idx)
        if idx >= len(lines):
            break
        current_index = _match_index_assignment(lines[idx].strip())
        if current_index is None:
            break
        current_index_reg, current_index_value = current_index
        if index_reg is None:
            index_reg = current_index_reg
        if current_index_reg != index_reg or current_index_value != expected_index:
            break

        store_idx = _skip_accu_loads(lines, idx + 1)
        if store_idx >= len(lines):
            break
        value = _match_array_store(lines[store_idx].strip(), arr_reg, index_reg, expected_index)
        if value is None:
            break
        values.append(value)
        expected_index += 1
        idx = store_idx + 1

    if not values:
        return None

    literal = f"[{', '.join(values)}]"
    alias_idx = _skip_accu_loads(lines, idx)
    if alias_idx < len(lines):
        alias = re.match(rf"^(\s*)(r\d+)\s*=\s*{re.escape(arr_reg)}$", lines[alias_idx])
        if alias and not _reg_used_before_reassign(lines, alias_idx + 1, arr_reg):
            return alias_idx, f"{alias.group(1)}{alias.group(2)} = {literal}"

    return idx - 1, f"{indent}{arr_reg} = {literal}"


def _reg_used_before_reassign(lines: List[str], start: int, reg: str) -> bool:
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip()
        if re.match(rf"^{re.escape(reg)}\s*=", stripped):
            return False
        if re.search(rf"\b{re.escape(reg)}\b", stripped):
            return True
    return False


def _compact_spread_array_builders(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    compacted_arrays: set[str] = set()

    while i < len(lines):
        replacement = _match_spread_array_builder(lines, i)
        if replacement is None:
            out.append(lines[i])
            i += 1
            continue

        end, arr_reg, rebuilt = replacement
        compacted_arrays.add(arr_reg)
        if out and re.match(r"^\s*ACCU\s*=\s*\[\]$", out[-1]):
            out.pop()
        out.append(rebuilt)
        i = end + 1

    if not compacted_arrays:
        return out

    usage = _count_reg_uses(out)
    cleaned: List[str] = []
    for line in out:
        stripped = line.strip()
        alias = re.match(r"^(r\d+)\s*=\s*(r\d+)$", stripped)
        if alias and alias.group(2) in compacted_arrays and usage.get(alias.group(1), 0) == 0:
            continue
        cleaned.append(line)
    return cleaned


def _match_spread_array_builder(lines: List[str], start: int) -> Optional[Tuple[int, str, str]]:
    init = re.match(r"^(\s*)(r\d+)\s*=\s*\[\]$", lines[start])
    if not init:
        return None

    indent, arr_reg = init.groups()
    idx = start + 1
    values: List[str] = []
    index_reg = None
    expected_index = 0

    while idx + 1 < len(lines):
        idx = _skip_accu_loads(lines, idx)
        if idx + 1 >= len(lines):
            break
        current_index = _match_index_assignment(lines[idx].strip())
        if current_index is None:
            break
        current_index_reg, current_index_value = current_index
        if index_reg is None:
            index_reg = current_index_reg
        if current_index_reg != index_reg or current_index_value != expected_index:
            break

        store_idx = _skip_accu_loads(lines, idx + 1)
        if store_idx >= len(lines):
            break
        value = _match_array_store(lines[store_idx].strip(), arr_reg, index_reg, expected_index)
        if value is None:
            break
        values.append(value)
        expected_index += 1
        idx = store_idx + 1

    if not values or index_reg is None or idx >= len(lines):
        return None

    idx = _skip_accu_loads(lines, idx)
    spread_index = _match_index_assignment(lines[idx].strip())
    if spread_index is None:
        return None
    spread_index_reg, spread_index_value = spread_index
    if spread_index_reg != index_reg or spread_index_value != expected_index:
        return None
    idx += 1

    idx, method_regs = _skip_object_values_setup(lines, idx)
    if idx >= len(lines):
        return None

    source_match = _match_object_values_call(lines, idx, method_regs)
    if not source_match:
        return None
    source_reg, rest_expr = source_match.groups()
    idx = source_match.end_index

    if idx >= len(lines):
        return None
    for_match = re.match(
        rf"^for \(const ([A-Za-z_$][A-Za-z0-9_$]*) of {re.escape(source_reg)}\) \{{$",
        lines[idx].strip(),
    )
    if not for_match:
        return None
    loop_var = for_match.group(1)
    loop_end = _find_block_end(lines, idx)
    if loop_end is None:
        return None

    body = [
        line.strip()
        for line in lines[idx + 1 : loop_end]
        if line.strip() and line.strip() != f"ACCU = {loop_var}"
    ]
    accepted_bodies = {
        (f"{arr_reg}[{index_reg}] = {loop_var}", f"{index_reg} += 1"),
        (f"{arr_reg}[{expected_index}] = {loop_var}", f"{index_reg} += 1"),
        (f"{arr_reg}[{expected_index}] = {loop_var}", f"{expected_index} += 1"),
    }
    if tuple(body) not in accepted_bodies:
        return None

    parts = values + [f"...Object.values({rest_expr.strip()})"]
    return loop_end, arr_reg, f"{indent}{arr_reg} = [{', '.join(parts)}]"


def _match_index_assignment(line: str) -> Optional[Tuple[str, int]]:
    match = re.match(r"^(r\d+)\s*=\s*(-?\d+)$", line)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _match_array_store(line: str, arr_reg: str, index_reg: str, expected_index: int) -> Optional[str]:
    direct = re.match(rf"^{re.escape(arr_reg)}\[(\d+)\]\s*=\s*(.+)$", line)
    if direct and int(direct.group(1)) == expected_index:
        return direct.group(2).strip()

    indirect = re.match(rf"^{re.escape(arr_reg)}\[{re.escape(index_reg)}\]\s*=\s*(.+)$", line)
    if indirect:
        return indirect.group(1).strip()

    return None


def _skip_accu_loads(lines: List[str], idx: int) -> int:
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("ACCU = "):
            idx += 1
            continue
        break
    return idx


def _skip_object_values_setup(lines: List[str], idx: int) -> Tuple[int, set[str]]:
    method_regs: set[str] = set()
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped in {"ACCU = Object", "ACCU = Object.values"}:
            idx += 1
            continue
        object_reg = re.match(r"^r\d+\s*=\s*Object$", stripped)
        if object_reg:
            idx += 1
            continue
        method_reg = re.match(r"^(r\d+)\s*=\s*Object\.values$", stripped)
        if method_reg:
            method_regs.add(method_reg.group(1))
            idx += 1
            continue
        break
    return idx, method_regs


class _CallMatch:
    def __init__(self, source_reg: str, rest_expr: str, end_index: int) -> None:
        self._groups = (source_reg, rest_expr)
        self.end_index = end_index

    def groups(self) -> Tuple[str, str]:
        return self._groups


def _match_object_values_call(
    lines: List[str], idx: int, method_regs: set[str]
) -> Optional[_CallMatch]:
    direct = re.match(r"^(r\d+)\s*=\s*Object\.values\((.+)\)$", lines[idx].strip())
    if direct:
        return _CallMatch(direct.group(1), direct.group(2), idx + 1)

    accu_call = re.match(r"^ACCU\s*=\s*(r\d+)\.call\(Object,\s*(.+)\)$", lines[idx].strip())
    if accu_call and accu_call.group(1) in method_regs:
        idx += 1
        if idx >= len(lines):
            return None

    bound = re.match(r"^(r\d+)\s*=\s*(r\d+)\.call\(Object,\s*(.+)\)$", lines[idx].strip())
    if bound and bound.group(2) in method_regs:
        return _CallMatch(bound.group(1), bound.group(3), idx + 1)

    return None
