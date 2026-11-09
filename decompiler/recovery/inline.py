from __future__ import annotations

import re
from functools import lru_cache
from typing import List

from .common import code_tokens, is_stable_assignment_target, replace_identifier_reads, uses_identifier

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
    # Same result as rescanning from line 0 after every inline, without the rescans.
    # Every line before i decided not to inline; an inline at i (line i removed, one later line rewritten) can only change a decision that read line i:
    # one that stopped in the register scan changes only if line i mentions its register, one that reached the move checks (inner) may change either way.
    # A register's scan stops at its next assignment, so per register only entries after its last real assignment before i can have read line i.
    out = lines[:]
    reach: List[int] = []
    kind: List[str] = []
    by_reg: dict[str, List[tuple[int, bool]]] = {}
    inner: List[int] = []
    log: List[str | None] = []
    i = 0
    while i < len(out):
        while len(log) > i:
            reg_of = log.pop()
            if reg_of is not None:
                by_reg[reg_of].pop()
            if inner and inner[-1] >= len(log):
                inner.pop()
        del reach[i:], kind[i:]
        line = out[i]
        reach.append(i)
        kind.append("fixed")
        log.append(None)
        changed = False
        match = re.match(r"^(\s*)(r\d+)\s*=\s*(.+)$", line)
        if match:
            _indent, reg, expr = match.groups()
            expr = expr.strip()
            log[i] = reg
            by_reg.setdefault(reg, []).append((i, _register_patterns(reg)[0].match(line.strip()) is not None))
            if not _has_live_prior_alias(out, i, reg):
                use_index, reach[i] = _single_use_scan(out, i + 1, reg)
                if use_index is None:
                    kind[i] = "scan"
                elif _is_inline_safe_expr(expr):
                    changed = _inline_at(out, i, reg, expr, use_index)
                    if not changed:
                        kind[i] = "inner"
                        inner.append(i)
        if not changed:
            i += 1
            continue
        restart = i
        for reg_of in set(REG_TOKEN_RE.findall(line)):
            for k, real in reversed(by_reg.get(reg_of, ())):
                if k < i and kind[k] == "scan" and reach[k] >= i:
                    restart = min(restart, k)
                if k < i and real:
                    break
        for k in inner:
            if k >= restart:
                break
            if reach[k] >= i:
                restart = k
                break
        i = restart
    return out


def _inline_at(out: List[str], i: int, reg: str, expr: str, use_index: int) -> bool:
    can_cross_statement = _can_cross_statement(expr)
    for j in range(i + 1, use_index + 1):
        stripped = out[j].strip()
        if stripped.endswith("{") or stripped.startswith("}"):
            return False
        if _assigns_referenced_value(stripped, expr):
            return False
        assignment = re.match(r"^(.+?)\s*[+\-*/%&|^]?=(?!=)\s*(.+)$", stripped)
        if (
            assignment and uses_identifier(assignment.group(2), reg)
            and not is_stable_assignment_target(assignment.group(1).strip())
        ):
            return False
        if uses_identifier(out[j], reg):
            replacement = replace_identifier_reads(out[j], {reg: expr})
            if replacement == out[j]:
                return False
            out[j] = replacement
            out.pop(i)
            return True
        if (
            stripped
            and not can_cross_statement
            and _is_movement_barrier(stripped)
        ):
            return False
    return False


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


@lru_cache(maxsize=None)
def _register_patterns(register: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    escaped = re.escape(register)
    return re.compile(rf"^{escaped}\s*=(?!=)\s*(.*)$"), re.compile(rf"(?<![\w$]){escaped}(?![\w$])")


def _single_use_scan(
    lines: List[str], start: int, register: str
) -> tuple[int | None, int]:
    """The register's single use before its reassignment (or None), and the last line read."""
    assign_re, use_re = _register_patterns(register)
    use_index: int | None = None
    index = start - 1
    for index in range(start, len(lines)):
        # code_tokens only blanks text, so a line without the name has neither a use nor an assignment of it.
        if register not in lines[index]:
            continue
        stripped = lines[index].strip()
        assignment = assign_re.match(stripped)
        searched = assignment.group(1) if assignment else stripped
        uses = len(use_re.findall(code_tokens(searched)))
        if assignment and uses:
            return None, index
        if uses:
            if use_index is not None or uses != 1:
                return None, index
            use_index = index
        if assignment:
            break
    return use_index, max(index, start - 1)


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
