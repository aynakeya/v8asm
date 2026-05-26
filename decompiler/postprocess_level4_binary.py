from __future__ import annotations

import re
from typing import List, Optional, Tuple

from postprocess_level4_common import _extract_indent


def _format_accu_binary(left: str, op: str, right: str) -> str:
    return f"({left.strip()} {op} {right.strip()})"


def _match_accu_binary(line: str) -> Optional[Tuple[str, str, str, str]]:
    return_match = re.match(
        r"^return\s+\((.+?)\s*([+\-*/%])\s*(.+)\)$", line.strip()
    )
    if return_match and "ACCU" in {return_match.group(1).strip(), return_match.group(3).strip()}:
        return (
            return_match.group(1).strip(),
            return_match.group(2),
            return_match.group(3).strip(),
            "return",
        )
    assign_match = re.match(
        r"^ACCU\s*=\s*\((.+?)\s*([+\-*/%])\s*(.+)\)$", line.strip()
    )
    if assign_match and "ACCU" in {assign_match.group(1).strip(), assign_match.group(3).strip()}:
        return (
            assign_match.group(1).strip(),
            assign_match.group(2),
            assign_match.group(3).strip(),
            "assign",
        )
    return None


def _compact_accu_binary_exprs(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_temp = re.match(r"^(r\d+)\s*=\s*(.+)$", s0)
            m_binary_store = re.match(r"^(r\d+)\s*=\s*\((r\d+)\s*([+*])\s*(.+)\)$", s1)
            if m_temp and m_binary_store:
                temp_reg, expr = m_temp.groups()
                dest, left_reg, op, rhs = m_binary_store.groups()
                expr = expr.strip()
                rhs = rhs.strip()
                if (
                    temp_reg == left_reg
                    and dest != temp_reg
                    and "ACCU" not in expr
                    and temp_reg not in rhs
                ):
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}{dest} = {_format_accu_binary(expr, op, rhs)}")
                    i += 2
                    continue

        if i + 4 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            s3 = lines[i + 3].strip()
            s4 = lines[i + 4].strip()
            m_left = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_left_reg = re.match(r"^(r\d+)\s*=\s*(.+)$", s1)
            m_right = re.match(r"^ACCU\s*=\s*(.+)$", s2)
            m_binary = re.match(r"^ACCU\s*=\s*\((r\d+)\s*([+*])\s*ACCU\)$", s3)
            m_target = re.match(r"^(.+?)\s*=\s*ACCU$", s4)
            if m_left and m_left_reg and m_right and m_binary and m_target:
                left = m_left.group(1).strip()
                saved_reg, saved_value = m_left_reg.groups()
                right = m_right.group(1).strip()
                binary_reg, op = m_binary.groups()
                target = m_target.group(1).strip()
                if (
                    saved_reg == binary_reg
                    and saved_value.strip() == left
                    and "ACCU" not in left
                    and "ACCU" not in right
                    and not re.fullmatch(r"r\d+", target)
                ):
                    indent = _extract_indent(lines[i + 4])
                    out.append(f"{indent}{target} = {_format_accu_binary(left, op, right)}")
                    i += 5
                    continue

        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_value = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            binary = _match_accu_binary(s1)
            if m_value and binary and "ACCU" not in m_value.group(1):
                value = m_value.group(1).strip()
                left, op, right, kind = binary
                expr = _format_accu_binary(
                    value if left == "ACCU" else left,
                    op,
                    value if right == "ACCU" else right,
                )
                indent = _extract_indent(lines[i + 1])

                if kind == "return":
                    out.append(f"{indent}return {expr}")
                    i += 2
                    continue

                if i + 2 < len(lines):
                    s2 = lines[i + 2].strip()
                    m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s2)
                    if m_store:
                        reg = m_store.group(1)
                        store_indent = _extract_indent(lines[i + 2])
                        out.append(f"{store_indent}{reg} = {expr}")
                        i += 3
                        continue
                    m_target_store = re.match(r"^(.+?)\s*=\s*ACCU$", s2)
                    if m_target_store:
                        target = m_target_store.group(1).strip()
                        if not re.fullmatch(r"r\d+", target):
                            store_indent = _extract_indent(lines[i + 2])
                            out.append(f"{store_indent}{target} = {expr}")
                            i += 3
                            continue

                if i + 4 < len(lines):
                    s2 = lines[i + 2].strip()
                    s3 = lines[i + 3].strip()
                    s4 = lines[i + 4].strip()
                    m_saved = re.match(r"^r\d+\s*=\s*" + re.escape(left) + r"$", s2)
                    m_dest = re.match(r"^(r\d+)\s*=\s*ACCU$", s3)
                    m_return = re.match(r"^return\s+\(ACCU\s*([+*])\s*(.+)\)$", s4)
                    if m_saved and m_dest and m_return:
                        dest = m_dest.group(1)
                        dest_indent = _extract_indent(lines[i + 3])
                        return_indent = _extract_indent(lines[i + 4])
                        if dest == left and op == "+":
                            out.append(f"{dest_indent}{dest} += {value}")
                        else:
                            out.append(f"{dest_indent}{dest} = {expr}")
                        ret_op, ret_right = m_return.groups()
                        out.append(f"{return_indent}return {_format_accu_binary(dest, ret_op, ret_right)}")
                        i += 5
                        continue

        out.append(lines[i])
        i += 1
    return out


def _compact_self_binary_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        match = re.match(r"^(r\d+)\s*=\s*\(\1\s*([+*])\s*(.+)\)$", stripped)
        if match:
            reg, op, expr = match.groups()
            indent = _extract_indent(line)
            out.append(f"{indent}{reg} {op}= {expr.strip()}")
            continue
        out.append(line)
    return out


def _compact_adjacent_binary_temp_registers(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_temp = re.match(r"^(r\d+)\s*=\s*(.+)$", s0)
            m_binary_store = re.match(r"^(r\d+)\s*=\s*\((r\d+)\s*([+*])\s*(.+)\)$", s1)
            if m_temp and m_binary_store:
                temp_reg, expr = m_temp.groups()
                dest, left_reg, op, rhs = m_binary_store.groups()
                expr = expr.strip()
                rhs = rhs.strip()
                if (
                    temp_reg == left_reg
                    and dest != temp_reg
                    and "ACCU" not in expr
                    and temp_reg not in rhs
                ):
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}{dest} = {_format_accu_binary(expr, op, rhs)}")
                    i += 2
                    continue
            m_property_store = re.match(r"^(.+?)\s*=\s*\((r\d+)\s*([+*])\s*(.+)\)$", s1)
            if m_temp and m_property_store:
                temp_reg, expr = m_temp.groups()
                target, left_reg, op, rhs = m_property_store.groups()
                expr = expr.strip()
                target = target.strip()
                rhs = rhs.strip()
                if (
                    temp_reg == left_reg
                    and target == expr
                    and "ACCU" not in expr
                    and temp_reg not in rhs
                ):
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}{target} = {_format_accu_binary(target, op, rhs)}")
                    i += 2
                    continue
        out.append(lines[i])
        i += 1
    return out


def _compact_accu_compare_if(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m0 = re.match(r"^ACCU = ([-+]?\d+)$", s0)
            m1 = re.match(r"^ACCU = \((.+)\s*([><]=?|===|!==)\s*ACCU\)$", s1)
            if m0 and m1 and s2 in {"if (truthy(ACCU)) {", "if (!(truthy(ACCU))) {"}:
                indent = _extract_indent(lines[i + 2])
                lhs, op = m1.group(1).strip(), m1.group(2)
                condition = f"{lhs} {op} {m0.group(1)}"
                if s2 == "if (!(truthy(ACCU))) {":
                    condition = f"!({condition})"
                out.append(f"{indent}if ({condition}) {{")
                i += 3
                continue
        out.append(lines[i])
        i += 1
    return out


def _recover_accu_conditional_expr(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 8 < len(lines):
            s = [lines[i + k].strip() for k in range(9)]
            m_lhs = re.match(r"^ACCU = (.+)$", s[0])
            m_rhs = re.match(r"^ACCU = (.+)$", s[1])
            m_cmp = re.match(r"^ACCU = \((.+?)\s*(===|!==|==|!=|[<>]=?)\s*ACCU\)$", s[2])
            m_then = re.match(r"^ACCU = (.+)$", s[4])
            m_else = re.match(r"^ACCU = (.+)$", s[7])
            if (
                m_lhs
                and m_rhs
                and m_cmp
                and m_then
                and m_else
                and s[3] in {"if (truthy(ACCU)) {", "if (!(truthy(ACCU))) {"}
                and s[5] == "}"
                and s[6] == "else {"
                and s[8] == "}"
            ):
                lhs = m_cmp.group(1).strip()
                op = m_cmp.group(2)
                rhs = m_rhs.group(1).strip()
                if lhs == m_lhs.group(1).strip():
                    then_expr = m_then.group(1).strip()
                    else_expr = m_else.group(1).strip()
                    if s[3] == "if (!(truthy(ACCU))) {":
                        then_expr, else_expr = else_expr, then_expr
                    indent = _extract_indent(lines[i])
                    out.append(f"{indent}ACCU = (({lhs} {op} {rhs}) ? {then_expr} : {else_expr})")
                    i += 9
                    continue
        out.append(lines[i])
        i += 1
    return out


def _recover_accu_conditional_return_expr(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 6 < len(lines):
            s = [lines[i + k].strip() for k in range(7)]
            cond = _truthy_condition_expr(s[0])
            m_then = re.match(r"^ACCU\s*=\s*(.+)$", s[1])
            m_else = re.match(r"^ACCU\s*=\s*(.+)$", s[4])
            m_return = re.match(r"^return\s+\((.+?)\s*([+\-*/%])\s*(.+)\)$", s[6])
            if (
                cond
                and m_then
                and m_else
                and m_return
                and s[2] == "}"
                and s[3] == "else {"
                and s[5] == "}"
            ):
                then_expr = m_then.group(1).strip()
                else_expr = m_else.group(1).strip()
                left = m_return.group(1).strip()
                op = m_return.group(2)
                right = m_return.group(3).strip()
                if (
                    "ACCU" not in cond
                    and "ACCU" not in then_expr
                    and "ACCU" not in else_expr
                    and (left == "ACCU" or right == "ACCU")
                ):
                    ternary = f"({cond} ? {then_expr} : {else_expr})"
                    expr = _format_accu_binary(
                        ternary if left == "ACCU" else left,
                        op,
                        ternary if right == "ACCU" else right,
                    )
                    indent = _extract_indent(lines[i + 6])
                    out.append(f"{indent}return {expr}")
                    i += 7
                    continue
        out.append(lines[i])
        i += 1
    return out


def _truthy_condition_expr(line: str) -> Optional[str]:
    positive = re.match(r"^if \(truthy\((.+)\)\) \{$", line)
    if positive:
        return positive.group(1).strip()
    negative = re.match(r"^if \(!truthy\((.+)\)\) \{$", line)
    if negative:
        return f"!truthy({negative.group(1).strip()})"
    return None
