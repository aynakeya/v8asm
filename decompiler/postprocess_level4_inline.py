from __future__ import annotations

import re
from typing import List

REG_TOKEN_RE = re.compile(r"\br\d+\b")


def _is_inline_safe_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr or expr == "ACCU":
        return False
    if expr in {"true", "false", "null", "undefined", "HOLE", "this"}:
        return True
    if re.fullmatch(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', expr):
        return True
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?n?", expr):
        return True
    if expr.startswith(("[", "{")):
        return True
    if re.fullmatch(
        r"[A-Za-z_$][A-Za-z0-9_$]*(\.[A-Za-z_$][A-Za-z0-9_$]*)*",
        expr,
    ):
        return True
    if re.fullmatch(
        r"[A-Za-z_$][A-Za-z0-9_$]*"
        r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?\[[^\]]+\]",
        expr,
    ):
        return True
    if expr.startswith(("context_slot[", "script_context[", "globalThis[")):
        return True
    return False


def _can_cross_statement(expr: str) -> bool:
    expr = expr.strip()
    if expr in {"true", "false", "null", "undefined", "HOLE", "this"}:
        return True
    if re.fullmatch(r"(?:r|arg)\d+", expr):
        return True
    if re.fullmatch(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', expr):
        return True
    return re.fullmatch(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?n?",
        expr,
    ) is not None


def _inline_single_use_registers(lines: List[str]) -> List[str]:
    out = lines[:]
    changed = True
    while changed:
        changed = False
        for i, line in enumerate(out):
            match = re.match(r"^(\s*)(r\d+)\s*=\s*(.+)$", line)
            if not match:
                continue
            _indent, reg, expr = match.groups()
            expr = expr.strip()
            if _has_live_prior_alias(out, i, reg):
                continue
            use_index = _single_use_before_reassignment(out, i + 1, reg)
            if use_index is None or not _is_inline_safe_expr(expr):
                continue

            can_cross_statement = _can_cross_statement(expr)
            for j in range(i + 1, use_index + 1):
                stripped = out[j].strip()
                if _assigns_referenced_value(stripped, expr):
                    break
                if re.search(rf"\b{re.escape(reg)}\b", out[j]):
                    out[j] = re.sub(
                        rf"\b{re.escape(reg)}\b",
                        lambda _match: expr,
                        out[j],
                    )
                    out.pop(i)
                    changed = True
                    break
                if (
                    stripped
                    and not can_cross_statement
                    and _is_movement_barrier(stripped)
                ):
                    break
            if changed:
                break
    return out


def _has_live_prior_alias(lines: List[str], index: int, register: str) -> bool:
    reassigned: set[str] = set()
    indent = len(lines[index]) - len(lines[index].lstrip())
    for previous in range(index - 1, -1, -1):
        line = lines[previous]
        stripped = line.strip()
        line_indent = len(line) - len(line.lstrip())
        if line_indent != indent or stripped in {"}", "else {"}:
            break
        assignment = re.match(r"^(r\d+)\s*=(?!=)\s*(.+)$", stripped)
        if not assignment:
            if stripped.startswith(("if ", "while ", "for ", "return ", "throw ")):
                break
            continue
        target, value = assignment.groups()
        if target == register:
            break
        if target in reassigned:
            continue
        if value.strip() == register:
            return True
        reassigned.add(target)
    return False


def _single_use_before_reassignment(
    lines: List[str], start: int, register: str
) -> int | None:
    use_index: int | None = None
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        assignment = re.match(rf"^{re.escape(register)}\s*=(?!=)\s*(.*)$", stripped)
        searched = assignment.group(1) if assignment else stripped
        uses = len(re.findall(rf"\b{re.escape(register)}\b", searched))
        if assignment and uses:
            return None
        if uses:
            if use_index is not None or uses != 1:
                return None
            use_index = index
        if assignment:
            break
    return use_index


def _is_movement_barrier(line: str) -> bool:
    if not line or line.startswith("//"):
        return False
    register_assignment = re.match(r"^r\d+\s*=\s*(.+)$", line)
    if not register_assignment:
        return True
    rhs = register_assignment.group(1).strip()
    if _can_cross_statement(rhs):
        return False
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", rhs):
        return False
    return not (
        rhs.startswith(("[", "{"))
        and "(" not in rhs
        and "..." not in rhs
    )


def _assigns_referenced_value(line: str, expr: str) -> bool:
    referenced = {token for token in REG_TOKEN_RE.findall(expr)}
    register_assign = re.match(r"^(r\d+)\s*=", line)
    if register_assign and register_assign.group(1) in referenced:
        return True

    identifier_assign = re.match(
        r"^([A-Za-z_$][A-Za-z0-9_$]*)\s*=(?!=)", line
    )
    return bool(
        identifier_assign
        and re.search(
            rf"\b{re.escape(identifier_assign.group(1))}\b",
            expr,
        )
    )
