from __future__ import annotations

import re
from typing import List

from postprocess_level4_common import _count_reg_uses


REG_TOKEN_RE = re.compile(r"\br\d+\b")


def _is_inline_safe_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if expr == "ACCU":
        return False
    if expr.startswith(("true", "false", "null", "undefined", "HOLE", '"', "'")):
        return True
    if expr.startswith(("[", "{", "String(")):
        return True
    if re.fullmatch(r"[-+]?\d+", expr):
        return True
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(\.[A-Za-z_$][A-Za-z0-9_$]*)*", expr):
        return True
    if re.fullmatch(
        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?\[[^\]]+\]",
        expr,
    ):
        return True
    if expr.startswith(("context_slot[", "script_context[", "globalThis[")):
        return True
    return False


def _inline_single_use_registers(lines: List[str]) -> List[str]:
    usage = _count_reg_uses(lines)
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
            if usage.get(reg, 0) != 1 or not _is_inline_safe_expr(expr):
                continue

            for j in range(i + 1, len(out)):
                stripped = out[j].strip()
                if re.match(rf"^{re.escape(reg)}\s*=", stripped):
                    break
                if re.match(rf"^{re.escape(reg)}\s*[+\-*/%]?=", stripped):
                    break
                if _assigns_any_referenced_register(stripped, expr):
                    break
                if re.search(rf"\b{re.escape(reg)}\b", out[j]):
                    out[j] = re.sub(rf"\b{re.escape(reg)}\b", expr, out[j])
                    out.pop(i)
                    usage = _count_reg_uses(out)
                    changed = True
                    break
            if changed:
                break
    return out


def _assigns_any_referenced_register(line: str, expr: str) -> bool:
    referenced = {token for token in REG_TOKEN_RE.findall(expr)}
    if not referenced:
        return False
    assign = re.match(r"^(r\d+)\s*=", line)
    return bool(assign and assign.group(1) in referenced)
