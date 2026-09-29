from __future__ import annotations

import re
from typing import Dict, List

from .common import _extract_indent, _find_block_end, code_tokens, is_live_after


def _coalesce_accu_store_aliases(lines: List[str]) -> List[str]:
    out: List[str] = []
    active_alias: str | None = None
    index = 0

    while index < len(lines):
        if index + 1 < len(lines):
            accu_load = re.match(r"^\s*ACCU\s*=\s*(.+)$", lines[index])
            register_load = re.match(
                r"^(\s*)(r\d+)\s*=\s*ACCU$",
                lines[index + 1],
            )
            if (
                accu_load
                and register_load
                and (
                    "ACCU" not in accu_load.group(1)
                    or _is_self_keyed_accu_load(
                        accu_load.group(1).strip(),
                        register_load.group(2),
                    )
                )
                and _accu_alias_is_safe(lines, index + 2, register_load.group(2))
            ):
                out.append(
                    f"{register_load.group(1)}{register_load.group(2)} = "
                    f"{accu_load.group(1).strip()}"
                )
                active_alias = register_load.group(2)
                index += 2
                continue

        line = lines[index]
        stripped = line.strip()
        if active_alias is not None:
            accu_assignment = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
            if accu_assignment:
                rhs = accu_assignment.group(1)
                if re.search(r"\bACCU\b", rhs):
                    line = re.sub(r"\bACCU\b", active_alias, line)
                active_alias = None
            elif re.search(r"\bACCU\b", stripped):
                line = re.sub(r"\bACCU\b", active_alias, line)

            if active_alias is not None and re.match(
                rf"^{re.escape(active_alias)}\s*=",
                stripped,
            ):
                active_alias = None

        out.append(line)
        index += 1

    return out


def _is_self_keyed_accu_load(expr: str, alias: str) -> bool:
    return re.fullmatch(
        rf"{re.escape(alias)}"
        r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*\[ACCU\]",
        expr,
    ) is not None


def _accu_alias_is_safe(lines: List[str], start: int, alias: str) -> bool:
    alias_reassigned = False
    for line in lines[start:]:
        stripped = line.strip()
        accu_assignment = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
        if accu_assignment:
            if re.search(r"\bACCU\b", accu_assignment.group(1)):
                return not alias_reassigned
            return True
        if re.search(r"\bACCU\b", stripped) and alias_reassigned:
            return False
        if re.match(rf"^{re.escape(alias)}\s*=", stripped):
            alias_reassigned = True
    return True


def _is_pure_expression(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if expr in {"true", "false", "null", "undefined", "HOLE", "this"}:
        return True
    if re.fullmatch(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', expr):
        return True
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?n?", expr):
        return True
    if re.fullmatch(r"(?:r|arg)\d+", expr):
        return True
    if re.fullmatch(r"(?:context_slot|script_context)\[[^\]]+\]", expr):
        return True
    if expr in {"[]", "{}"}:
        return True
    return False


def _simplify_accu_return(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            if s1 == "return ACCU" and s0.startswith("ACCU = "):
                expr = s0[len("ACCU = ") :].strip()
                indent = _extract_indent(lines[i + 1])
                out.append(f"{indent}return {expr}")
                i += 2
                continue
        out.append(lines[i])
        i += 1
    return out


def _simplify_accu_throw(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            match = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            if match and s1 == "throw ACCU":
                expr = match.group(1).strip()
                if "ACCU" not in expr:
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}throw {expr}")
                    i += 2
                    continue
        out.append(lines[i])
        i += 1
    return out


def _flatten_else_after_early_exit(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("if (") and stripped.endswith("{"):
            then_end = _find_block_end(lines, i)
            if then_end is not None and then_end + 1 < len(lines):
                else_line = lines[then_end + 1].strip()
                if else_line == "else {":
                    else_end = _find_block_end(lines, then_end + 1)
                    if else_end is not None:
                        then_body = lines[i + 1 : then_end]
                        last_then = ""
                        for t in reversed(then_body):
                            st = t.strip()
                            if st:
                                last_then = st
                                break
                        if last_then.startswith(("return ", "throw ")):
                            out.extend(lines[i : then_end + 1])
                            out.extend(lines[then_end + 2 : else_end])
                            i = else_end + 1
                            continue
        out.append(line)
        i += 1
    return out


def _convert_unused_accu_assign_to_expr(lines: List[str]) -> List[str]:
    out = lines[:]
    for i, line in enumerate(out):
        match = re.match(r"^(\s*)ACCU\s*=\s*(.+)$", line)
        if not match:
            continue
        indent, expr = match.groups()
        expr = expr.strip()
        if _is_pure_expression(expr):
            continue
        if "(" not in expr and not _is_property_read_expr(expr):
            continue

        if not is_live_after(out, i + 1, "ACCU"):
            out[i] = f"{indent}{expr}"
    return out


def _inline_simple_accu_loads_into_next_line(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_accu = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            next_code = code_tokens(s1)
            if (
                m_accu
                and re.search(r"\bACCU\b", s1)
                and "`" not in s1
                and "{" not in next_code
                and not re.search(r"(?:\+\+|--)\s*ACCU\b|\bACCU\s*(?:[+\-*/%&|^]?=|\+\+|--)", next_code)
                and not s1.startswith(("if ", "while ", "for ", "else "))
            ):
                expr = m_accu.group(1).strip()
                if _is_pure_expression(expr) and "ACCU" not in expr:
                    matches = list(re.finditer(r"(?<![\w$.])ACCU(?![\w$])", code_tokens(lines[i + 1])))
                    if matches:
                        if is_live_after(lines, i + 2, "ACCU"):
                            out.append(lines[i])
                        replacement = lines[i + 1]
                        for match in reversed(matches):
                            replacement = replacement[:match.start()] + expr + replacement[match.end():]
                        out.append(replacement)
                        i += 2
                        continue
        out.append(lines[i])
        i += 1
    return out


def _is_property_read_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr or "ACCU" in expr:
        return False
    structure = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', expr)
    if any(token in structure for token in ("(", ")", "=", "=>")):
        return False
    return bool(re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]]+\])+", expr))


def _drop_duplicate_expr_before_assignment(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            expr = lines[i].strip()
            next_line = lines[i + 1].strip()
            m_accu = re.match(r"^ACCU\s*=\s*(.+)$", expr)
            m_reg_dup = re.match(r"^r\d+\s*=\s*(.+)$", next_line)
            if (
                m_accu
                and m_reg_dup
                and _is_pure_expression(m_accu.group(1).strip())
                and m_accu.group(1).strip() == m_reg_dup.group(1).strip()
                and not _reads_accu_before_reassign(lines, i + 2)
            ):
                i += 1
                continue

        out.append(lines[i])
        i += 1
    return out


def _collapse_accu_store_return(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m_accu = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_reg = re.match(r"^r\d+\s*=\s*(.+)$", s1)
            if (
                m_accu
                and m_reg
                and s2 == "return ACCU"
                and m_accu.group(1).strip() == m_reg.group(1).strip()
                and "ACCU" not in m_accu.group(1)
            ):
                indent = _extract_indent(lines[i + 2])
                out.append(f"{indent}return {m_accu.group(1).strip()}")
                i += 3
                continue
        out.append(lines[i])
        i += 1
    return out


def _collapse_accu_store(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_accu = re.match(r"^ACCU\s*=\s*(.+)$", s0)
            m_reg = re.match(r"^(r\d+)\s*=\s*ACCU$", s1)
            if m_accu and m_reg:
                expr = m_accu.group(1).strip()
                if "ACCU" not in expr and not _reads_accu_before_reassign(lines, i + 2):
                    indent = _extract_indent(lines[i + 1])
                    out.append(f"{indent}{m_reg.group(1)} = {expr}")
                    i += 2
                    continue
        out.append(lines[i])
        i += 1
    return out


def _collapse_accu_push_context(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            m_accu = re.match(r"^ACCU\s*=\s*(create_(?:function|block)_context\(.+\))$", s0)
            m_push = re.match(r"^(r\d+)\s*=\s*pushContext\(ACCU\)$", s1)
            if m_accu and m_push:
                indent = _extract_indent(lines[i + 1])
                out.append(f"{indent}{m_push.group(1)} = pushContext({m_accu.group(1).strip()})")
                i += 2
                continue
        out.append(lines[i])
        i += 1
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


def _drop_unused_pure_accu_loads(lines: List[str]) -> List[str]:
    keep = [True] * len(lines)

    for idx, line in enumerate(lines):
        stripped = line.strip()
        m_accu = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
        if not m_accu:
            continue

        expr = m_accu.group(1).strip()
        if not _is_pure_expression(expr):
            continue

        used = False
        for next_idx in range(idx + 1, len(lines)):
            next_stripped = lines[next_idx].strip()
            if next_stripped in {"}", "else {"}:
                used = True
                break
            next_reassignment = re.match(r"^ACCU\s*=\s*(.+)$", next_stripped)
            if next_reassignment:
                if re.search(r"\bACCU\b", next_reassignment.group(1)):
                    used = True
                break
            if re.search(r"\bACCU\b", next_stripped):
                used = True
                break

        if not used:
            keep[idx] = False

    return [line for idx, line in enumerate(lines) if keep[idx]]


def _name_async_reject_handler_exceptions(lines: List[str]) -> List[str]:
    out = lines[:]
    for idx, line in enumerate(out):
        stripped = line.strip()
        match = re.match(r"^(r\d+)\s*=\s*ACCU$", stripped)
        if not match:
            continue
        target_reg = match.group(1)
        pending_idx = _next_significant_index(out, idx + 1)
        if pending_idx is None or out[pending_idx].strip() != "// SetPendingMessage":
            continue
        if not _async_reject_uses_reg(out, pending_idx + 1, target_reg):
            continue
        indent = _extract_indent(line)
        out[idx] = f"{indent}{target_reg} = async_reject_exception"
    return out


def _next_significant_index(lines: List[str], start: int) -> int | None:
    for idx in range(start, len(lines)):
        if lines[idx].strip():
            return idx
    return None


def _async_reject_uses_reg(lines: List[str], start: int, reg: str) -> bool:
    for idx in range(start, min(len(lines), start + 6)):
        stripped = lines[idx].strip()
        if re.match(r"^ACCU\s*=", stripped):
            return False
        if stripped.startswith("return _AsyncFunctionReject(") and re.search(
            rf"\b{re.escape(reg)}\b", stripped
        ):
            return True
    return False


def _drop_unused_pure_reg_assignments(lines: List[str]) -> List[str]:
    live: set[str] = set()
    keep = [True] * len(lines)

    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        stripped = line.strip()
        match = re.match(r"^(r\d+)\s*=\s*(.+)$", stripped)
        if match:
            reg, expr = match.groups()
            rhs_regs = set(re.findall(r"\br\d+\b", expr))
            if (
                reg not in live
                and _is_pure_reg_rhs(expr.strip())
                and _has_following_executable_line(lines, idx + 1)
            ):
                keep[idx] = False
                continue
            live.discard(reg)
            live.update(rhs_regs)
            continue

        live.update(re.findall(r"\br\d+\b", stripped))

    return [line for idx, line in enumerate(lines) if keep[idx]]


def _has_following_executable_line(lines: List[str], start: int) -> bool:
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip()
        if not stripped or stripped in {"}", "else {"}:
            continue
        return True
    return False


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


def _is_pure_reg_rhs(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if "(" in expr:
        return False
    return _is_pure_expression(expr)
