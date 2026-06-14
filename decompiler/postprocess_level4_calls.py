from __future__ import annotations

import re
from typing import Dict, List, Optional

from postprocess_level4_common import _extract_indent


def _member_receiver(member: str) -> Optional[str]:
    if "." not in member:
        return None
    return member.rsplit(".", 1)[0]


def _is_member_expr(expr: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+", expr))


def _split_call_args(arg_text: str) -> Optional[List[str]]:
    args: List[str] = []
    start = 0
    depth = 0
    quote: Optional[str] = None
    escaped = False

    for idx, char in enumerate(arg_text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in {"'", '"'}:
            quote = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth -= 1
            if depth < 0:
                return None
            continue
        if char == "," and depth == 0:
            args.append(arg_text[start:idx].strip())
            start = idx + 1

    if quote or depth != 0:
        return None
    tail = arg_text[start:].strip()
    if tail:
        args.append(tail)
    return args


def _split_wrapped_binary_expr(expr: str) -> Optional[tuple[str, str, str]]:
    expr = expr.strip()
    if not (expr.startswith("(") and expr.endswith(")")):
        return None
    inner = expr[1:-1].strip()
    depth = 0
    quote: Optional[str] = None
    escaped = False
    operators = (" === ", " !== ", " >= ", " <= ", " + ", " - ", " * ", " / ", " % ")

    for idx, char in enumerate(inner):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth -= 1
            if depth < 0:
                return None
            continue
        if depth != 0:
            continue
        for op in operators:
            if inner.startswith(op, idx):
                lhs = inner[:idx].strip()
                rhs = inner[idx + len(op) :].strip()
                if lhs and rhs:
                    return lhs, op.strip(), rhs
    return None


def _rewrite_call_expr(expr: str, reg_members: Dict[str, str]) -> str:
    outer = re.match(r"^String\((.+)\)$", expr.strip())
    if outer:
        inner = outer.group(1).strip()
        rewritten_inner = _rewrite_call_expr(inner, reg_members)
        if rewritten_inner != inner:
            return f"String({rewritten_inner})"

    binary = _split_wrapped_binary_expr(expr)
    if binary:
        lhs, op, rhs = binary
        rewritten_lhs = _rewrite_call_expr(lhs, reg_members)
        rewritten_rhs = _rewrite_call_expr(rhs, reg_members)
        if rewritten_lhs != lhs or rewritten_rhs != rhs:
            return f"({rewritten_lhs} {op} {rewritten_rhs})"

    match = re.match(r"^(.+)\.call\((.*)\)$", expr.strip())
    if not match:
        return expr
    callee = match.group(1).strip()
    arg_text = match.group(2).strip()
    if not arg_text:
        return expr

    args = _split_call_args(arg_text)
    if not args:
        return expr
    receiver = args[0]
    call_args = ", ".join(args[1:])
    member = reg_members.get(callee, callee)
    member_receiver = _member_receiver(member)
    if receiver == "undefined" and re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*|r\d+", member):
        return f"{member}({call_args})" if call_args else f"{member}()"
    if member_receiver != receiver:
        return expr
    return f"{member}({call_args})" if call_args else f"{member}()"


def _rewrite_bound_method_calls(lines: List[str]) -> List[str]:
    reg_members: Dict[str, str] = {}
    out: List[str] = []

    for line in lines:
        stripped = line.strip()
        indent = _extract_indent(line)

        m_assign = re.match(r"^(ACCU|r\d+)\s*=\s*(.+)$", stripped)
        if m_assign:
            lhs, expr = m_assign.groups()
            expr = _rewrite_call_expr(expr.strip(), reg_members)
            out.append(f"{indent}{lhs} = {expr}")
            if lhs.startswith("r"):
                if _is_member_expr(expr):
                    reg_members[lhs] = expr
                else:
                    reg_members.pop(lhs, None)
            continue

        m_return = re.match(r"^return\s+(.+)$", stripped)
        if m_return:
            expr = _rewrite_call_expr(m_return.group(1).strip(), reg_members)
            out.append(f"{indent}return {expr}")
            continue

        m_compound = re.match(r"^(.+?\s*[+\-*/%]=)\s*(.+)$", stripped)
        if m_compound:
            lhs, expr = m_compound.groups()
            out.append(f"{indent}{lhs} {_rewrite_call_expr(expr.strip(), reg_members)}")
            continue

        rewritten = _rewrite_call_expr(stripped, reg_members)
        out.append(f"{indent}{rewritten}" if rewritten != stripped else line)

    return out
