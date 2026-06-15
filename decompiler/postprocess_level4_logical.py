from __future__ import annotations

import re
from typing import List

from postprocess_level4_common import _extract_indent, _find_block_end


def _body_reads_accu_before_reassign(lines: List[str], start: int, end: int) -> bool:
    for idx in range(start, min(end, len(lines))):
        stripped = lines[idx].strip()
        reassignment = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
        if reassignment:
            if re.search(r"\bACCU\b", reassignment.group(1)):
                return True
            return False
        if re.search(r"\bACCU\b", stripped):
            return True
    return False


def recover_nullish_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 6 < len(lines):
            s = [lines[i + offset].strip() for offset in range(7)]
            m_initial = re.match(r"^ACCU\s*=\s*(.+)$", s[0])
            m_fallback = re.match(r"^ACCU\s*=\s*(.+)$", s[4])
            m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s[6])
            if (
                m_initial
                and m_fallback
                and m_store
                and s[1] == "if (!(isNullish(ACCU))) {"
                and s[2] == "}"
                and s[3] == "else {"
                and s[5] == "}"
            ):
                lhs = m_initial.group(1).strip()
                rhs = m_fallback.group(1).strip()
                if "ACCU" not in lhs and "ACCU" not in rhs:
                    indent = _extract_indent(lines[i + 6])
                    out.append(f"{indent}{m_store.group(1)} = (isNullish({lhs}) ? {rhs} : {lhs})")
                    i += 7
                    continue
        out.append(lines[i])
        i += 1
    return out


def inline_accu_condition_loads(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_value = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_if = _match_accu_truthy_if(s1, allow_wrapped_negation=True)
            if m_value and m_if is not None:
                end = _find_block_end(lines, i + 1)
                value = m_value.group(1).strip()
                if end is not None and "ACCU" not in value:
                    if not _body_reads_accu_before_reassign(
                        lines, i + 2, end
                    ) and not _reads_accu_before_reassign(lines, end + 1):
                        indent = _extract_indent(lines[i + 1])
                        out.append(_format_truthy_if(indent, m_if, value))
                        i += 2
                        continue
        out.append(lines[i])
        i += 1
    return out


def inline_accu_equality_condition_loads(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_value = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            condition = _replace_accu_equality_condition(s1, m_value.group(1).strip() if m_value else "")
            if m_value and condition is not None:
                end = _find_block_end(lines, i + 1)
                value = m_value.group(1).strip()
                if end is not None and "ACCU" not in value:
                    replacement_body = _replace_accu_reads_until_store(lines[i + 2 : end], value)
                    if replacement_body is not None and not _reads_accu_before_reassign(lines, end + 1):
                        out.append(f"{_extract_indent(lines[i + 1])}{condition}")
                        out.extend(replacement_body)
                        out.append(lines[end])
                        i = end + 1
                        continue
        out.append(lines[i])
        i += 1
    return out


def _replace_accu_equality_condition(stripped: str, value: str) -> str | None:
    if not value:
        return None
    direct = re.match(r"^if \(ACCU\s*(===|!==|==|!=)\s*(.+)\) \{$", stripped)
    if direct:
        op, rhs = direct.groups()
        return f"if ({value} {op} {rhs.strip()}) {{"
    negated = re.match(r"^if \(!\(ACCU\s*(===|!==|==|!=)\s*(.+)\)\) \{$", stripped)
    if negated:
        op, rhs = negated.groups()
        return f"if (!({value} {op} {rhs.strip()})) {{"
    return None


def _replace_accu_reads_until_store(lines: List[str], value: str) -> List[str] | None:
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^ACCU\s*=", stripped):
            return None
        out.append(re.sub(r"\bACCU\b", value, line))
    return out


def _reads_accu_before_reassign(lines: List[str], start: int) -> bool:
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip()
        reassignment = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
        if reassignment:
            if re.search(r"\bACCU\b", reassignment.group(1)):
                return True
            return False
        if re.search(r"\bACCU\b", stripped):
            return True
        if stripped in {"}", "else {"} or stripped.startswith(("return ", "throw ")):
            return False
    return False


def rewrite_accu_condition_after_reg_store(lines: List[str]) -> List[str]:
    out = lines[:]
    for idx in range(len(out) - 1):
        s0 = out[idx].strip()
        s1 = out[idx + 1].strip()
        m_store = re.match(r"^(r\d+)\s*=\s*(.+)$", s0)
        m_if = _match_accu_truthy_if(s1, allow_wrapped_negation=False)
        if not m_store or m_if is None:
            continue
        expr = m_store.group(2).strip()
        if "ACCU" in expr:
            continue
        indent = _extract_indent(out[idx + 1])
        out[idx + 1] = _format_truthy_if(indent, m_if, m_store.group(1))
    return out


def rewrite_accu_condition_after_duplicate_store(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m_accu = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_store = re.match(r"^(r\d+)\s*=\s*(.+)$", s1)
            m_if = _match_accu_truthy_if(s2, allow_wrapped_negation=True)
            if m_accu and m_store and m_if is not None:
                expr = m_accu.group(1).strip()
                if expr == m_store.group(2).strip() and "ACCU" not in expr:
                    out.append(lines[i + 1])
                    indent = _extract_indent(lines[i + 2])
                    out.append(_format_truthy_if(indent, m_if, m_store.group(1)))
                    i += 3
                    continue
        out.append(lines[i])
        i += 1
    return out


def _match_accu_truthy_if(stripped: str, allow_wrapped_negation: bool) -> str | None:
    if stripped == "if (truthy(ACCU)) {":
        return ""
    if stripped == "if (!truthy(ACCU)) {":
        return "!"
    if allow_wrapped_negation and stripped == "if (!(truthy(ACCU))) {":
        return "!"
    return None


def _format_truthy_if(indent: str, negation: str, expr: str) -> str:
    return f"{indent}if ({negation}truthy({expr})) {{"


def recover_or_fallback_returns(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 4 < len(lines):
            s = [lines[i + offset].strip() for offset in range(5)]
            m_expr = re.match(r"^ACCU\s*=\s*(.+)$", s[0])
            m_fallback = re.match(r"^ACCU\s*=\s*(.+)$", s[2])
            if (
                m_expr
                and m_fallback
                and s[1] == "if (!(truthy(ACCU))) {"
                and s[3] == "}"
                and s[4] == "return ACCU"
            ):
                expr = m_expr.group(1).strip()
                fallback = m_fallback.group(1).strip()
                if "ACCU" not in expr and "ACCU" not in fallback:
                    indent = _extract_indent(lines[i + 4])
                    out.append(f"{indent}return ({expr} || {fallback})")
                    i += 5
                    continue
        out.append(lines[i])
        i += 1
    return out


def recover_or_fallback_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 4 < len(lines):
            s = [lines[i + offset].strip() for offset in range(5)]
            m_expr = re.match(r"^ACCU\s*=\s*(.+)$", s[0])
            m_fallback = re.match(r"^ACCU\s*=\s*(.+)$", s[2])
            m_store = re.match(r"^(r\d+)\s*=\s*ACCU$", s[4])
            if (
                m_expr
                and m_fallback
                and m_store
                and s[1] == "if (!(truthy(ACCU))) {"
                and s[3] == "}"
            ):
                expr = m_expr.group(1).strip()
                fallback = m_fallback.group(1).strip()
                if "ACCU" not in expr and "ACCU" not in fallback:
                    indent = _extract_indent(lines[i + 4])
                    out.append(f"{indent}{m_store.group(1)} = ({expr} || {fallback})")
                    i += 5
                    continue
        out.append(lines[i])
        i += 1
    return out


def combine_nested_truthy_ifs(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        outer = lines[i].strip()
        m_outer = re.match(r"^if \(truthy\((.+)\)\) \{$", outer)
        if not m_outer:
            out.append(lines[i])
            i += 1
            continue

        outer_end = _find_block_end(lines, i)
        if outer_end is None or i + 2 >= outer_end:
            out.append(lines[i])
            i += 1
            continue

        inner = lines[i + 1].strip()
        m_inner = re.match(r"^if \(truthy\((.+)\)\) \{$", inner)
        inner_end = _find_block_end(lines, i + 1)
        if not m_inner or inner_end != outer_end - 1:
            out.append(lines[i])
            i += 1
            continue

        indent = _extract_indent(lines[i])
        body_indent = indent + "  "
        out.append(f"{indent}if (truthy({m_outer.group(1)}) && truthy({m_inner.group(1)})) {{")
        for body_line in lines[i + 2 : inner_end]:
            out.append(f"{body_indent}{body_line.strip()}")
        out.append(f"{indent}}}")
        i = outer_end + 1
    return out
