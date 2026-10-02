from __future__ import annotations

import re
from typing import List

from .common import _extract_indent, _find_block_end, is_live_after


def recover_nullish_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        recovered = _try_recover_nullish_assignment(lines, i)
        if recovered is not None:
            replacement, next_i = recovered
            out.extend(replacement)
            i = next_i
            continue
        out.append(lines[i])
        i += 1
    return out


def _try_recover_nullish_assignment(
    lines: List[str], start: int
) -> tuple[List[str], int] | None:
    initial = re.match(r"^ACCU\s*=\s*(.+)$", lines[start].strip())
    if not initial:
        return None

    guard_idx = start + 1
    saved_bindings: List[str] = []
    while guard_idx < len(lines) and _is_pure_register_copy(lines[guard_idx]):
        if _extract_indent(lines[guard_idx]) != _extract_indent(lines[start]):
            return None
        saved_bindings.append(lines[guard_idx])
        guard_idx += 1

    if (
        guard_idx >= len(lines)
        or lines[guard_idx].strip() != "if (!(isNullish(ACCU))) {"
    ):
        return None
    then_end = _find_block_end(lines, guard_idx)
    if then_end is None:
        return None
    then_body = [line.strip() for line in lines[guard_idx + 1 : then_end] if line.strip()]
    if then_body or then_end + 1 >= len(lines) or lines[then_end + 1].strip() != "else {":
        return None

    else_end = _find_block_end(lines, then_end + 1)
    if else_end is None or else_end + 1 >= len(lines):
        return None
    else_body = [line.strip() for line in lines[then_end + 2 : else_end] if line.strip()]
    if len(else_body) != 1:
        return None
    fallback = re.match(r"^ACCU\s*=\s*(.+)$", else_body[0])
    store = re.match(r"^(r\d+)\s*=\s*ACCU$", lines[else_end + 1].strip())
    if not fallback or not store:
        return None

    lhs = initial.group(1).strip()
    rhs = fallback.group(1).strip()
    if "ACCU" in lhs or "ACCU" in rhs:
        return None

    destination = store.group(1)
    indent = _extract_indent(lines[else_end + 1])
    if saved_bindings:
        if _register_is_used(destination, rhs) or any(
            _register_is_used(destination, line) for line in saved_bindings
        ):
            return None
        replacement = [f"{_extract_indent(lines[start])}{destination} = {lhs}"]
        replacement.extend(saved_bindings)
        replacement.append(f"{indent}{destination} ??= {rhs}")
    else:
        replacement = [f"{indent}{destination} = ({lhs} ?? {rhs})"]
    if is_live_after(lines, else_end + 2, "ACCU"):
        replacement.append(f"{indent}ACCU = {destination}")
    return replacement, else_end + 2


def _is_pure_register_copy(line: str) -> bool:
    stripped = line.strip()
    match = re.match(
        r"^r\d+\s*=\s*([A-Za-z_$][A-Za-z0-9_$]*|r\d+|arg\d+)$",
        stripped,
    )
    return match is not None


def _register_is_used(register: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(register)}\b", text) is not None


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
                value = m_value.group(1).strip()
                if "ACCU" not in value and not _accu_live_through_if(lines, i + 1):
                    indent = _extract_indent(lines[i + 1])
                    out.append(_format_truthy_if(indent, m_if, value))
                    i += 2
                    continue
        out.append(lines[i])
        i += 1
    return out


def _accu_live_through_if(lines: List[str], start: int) -> bool:
    end = _find_block_end(lines, start)
    if end is None:
        return True
    branches = [lines[start + 1:end], []]
    join = end + 1
    if join < len(lines) and lines[join].strip() == "else {":
        else_end = _find_block_end(lines, join)
        if else_end is None:
            return True
        branches[1] = lines[join + 1:else_end]
        join = else_end + 1
    # A missing else is also a path through the merge.
    return any(is_live_after(branch + lines[join:], 0, "ACCU") for branch in branches)


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
                    if replacement_body is not None and not is_live_after(lines, end + 1, "ACCU"):
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
        out.append(re.sub(r"\bACCU\b", lambda _match: value, line))
    return out


def rewrite_accu_condition_after_reg_store(lines: List[str]) -> List[str]:
    out = lines[:]
    for idx in range(len(out) - 1):
        s0 = out[idx].strip()
        s1 = out[idx + 1].strip()
        m_store = re.fullmatch(r"(r\d+)\s*=\s*ACCU", s0)
        m_if = _match_accu_truthy_if(s1, allow_wrapped_negation=False)
        if not m_store or m_if is None:
            continue
        indent = _extract_indent(out[idx + 1])
        out[idx + 1] = _format_truthy_if(indent, m_if, m_store.group(1))
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
        if (
            outer_end is None or i + 2 >= outer_end
            or (outer_end + 1 < len(lines) and lines[outer_end + 1].strip() == "else {")
        ):
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


def drop_redundant_empty_else_truthy_guards(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 5 < len(lines):
            condition = _match_truthy_block_condition(lines[i].strip())
            m_accu = re.match(r"^ACCU\s*=\s*(.+)$", lines[i + 3].strip())
            goto_condition = _match_accu_truthy_goto(lines[i + 4].strip())
            if (
                condition is not None
                and m_accu
                and goto_condition is not None
                and goto_condition[0] == condition[0]
                and lines[i + 1].strip() == "}"
                and lines[i + 2].strip() == "else {"
                and lines[i + 5].strip() == "}"
                and m_accu.group(1).strip() == condition[1]
            ):
                i += 6
                continue
        out.append(lines[i])
        i += 1
    return out


def _match_truthy_block_condition(stripped: str) -> tuple[bool, str] | None:
    positive = re.match(r"^if \(truthy\((.+)\)\) \{$", stripped)
    if positive:
        return False, positive.group(1).strip()
    negative = re.match(r"^if \(!truthy\((.+)\)\) \{$", stripped)
    if negative:
        return True, negative.group(1).strip()
    wrapped_negative = re.match(r"^if \(!\(truthy\((.+)\)\)\) \{$", stripped)
    if wrapped_negative:
        return True, wrapped_negative.group(1).strip()
    return None


def _match_accu_truthy_goto(stripped: str) -> tuple[bool, str] | None:
    positive = re.match(r"^if \((?:truthy\(ACCU\)|ACCU)\) goto offset_\d+$", stripped)
    if positive:
        return False, "ACCU"
    negative = re.match(r"^if \((?:!truthy\(ACCU\)|!ACCU)\) goto offset_\d+$", stripped)
    if negative:
        return True, "ACCU"
    wrapped_negative = re.match(r"^if \(!\(truthy\(ACCU\)\)\) goto offset_\d+$", stripped)
    if wrapped_negative:
        return True, "ACCU"
    return None
