from __future__ import annotations

import re
from typing import Dict, List, Optional

from .postprocess_level4_common import _extract_indent


def _member_receiver(member: str) -> Optional[str]:
    dot = re.fullmatch(r"(.+)\.[A-Za-z_$][A-Za-z0-9_$]*", member)
    if dot:
        return dot.group(1)
    keyed = re.fullmatch(r"(.+)\[[^\]]+\]", member)
    if keyed:
        return keyed.group(1)
    return None


def _is_member_expr(expr: str) -> bool:
    return bool(
        re.fullmatch(
            r"[A-Za-z_$][A-Za-z0-9_$]*"
            r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+",
            expr,
        )
    )


def _resolve_register_alias(value: str, aliases: Dict[str, str]) -> str:
    resolved = value
    seen: set[str] = set()
    while resolved in aliases and resolved not in seen:
        seen.add(resolved)
        resolved = aliases[resolved]
    return resolved


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


def _rewrite_call_expr(
    expr: str, reg_members: Dict[str, str], reg_aliases: Dict[str, str]
) -> str:
    outer = re.match(r"^String\((.+)\)$", expr.strip())
    if outer:
        inner = outer.group(1).strip()
        rewritten_inner = _rewrite_call_expr(inner, reg_members, reg_aliases)
        if rewritten_inner != inner:
            return f"String({rewritten_inner})"

    binary = _split_wrapped_binary_expr(expr)
    if binary:
        lhs, op, rhs = binary
        rewritten_lhs = _rewrite_call_expr(lhs, reg_members, reg_aliases)
        rewritten_rhs = _rewrite_call_expr(rhs, reg_members, reg_aliases)
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
    receiver = _resolve_register_alias(args[0], reg_aliases)
    call_args = ", ".join(args[1:])
    member = reg_members.get(callee, callee)
    member_receiver = _member_receiver(member)
    if member_receiver is not None:
        member_receiver = _resolve_register_alias(member_receiver, reg_aliases)
    if receiver == "undefined" and re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*|r\d+", member):
        return f"{member}({call_args})" if call_args else f"{member}()"
    if member_receiver != receiver:
        return expr
    return f"{member}({call_args})" if call_args else f"{member}()"


def _rewrite_bound_method_calls(lines: List[str]) -> List[str]:
    reg_members: Dict[str, str] = {}
    reg_aliases: Dict[str, str] = {}
    out: List[str] = []

    for line in lines:
        stripped = line.strip()
        indent = _extract_indent(line)

        m_assign = re.match(
            r"^([A-Za-z_$][A-Za-z0-9_$]*"
            r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]]+\])*)"
            r"\s*=(?!=)\s*(.+)$",
            stripped,
        )
        if m_assign:
            lhs, expr = m_assign.groups()
            expr = _rewrite_call_expr(expr.strip(), reg_members, reg_aliases)
            out.append(f"{indent}{lhs} = {expr}")
            if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", lhs):
                _kill_bindings(lhs, reg_members, reg_aliases)
            if re.fullmatch(r"r\d+", lhs):
                if _is_member_expr(expr):
                    reg_members[lhs] = expr
                elif re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*|r\d+", expr):
                    reg_aliases[lhs] = _resolve_register_alias(expr, reg_aliases)
            continue

        m_return = re.match(r"^return\s+(.+)$", stripped)
        if m_return:
            expr = _rewrite_call_expr(
                m_return.group(1).strip(), reg_members, reg_aliases
            )
            out.append(f"{indent}return {expr}")
            continue

        m_compound = re.match(r"^(.+?\s*[+\-*/%]=)\s*(.+)$", stripped)
        if m_compound:
            lhs, expr = m_compound.groups()
            out.append(
                f"{indent}{lhs} "
                f"{_rewrite_call_expr(expr.strip(), reg_members, reg_aliases)}"
            )
            continue

        rewritten = _rewrite_call_expr(stripped, reg_members, reg_aliases)
        out.append(f"{indent}{rewritten}" if rewritten != stripped else line)

    return out


def _kill_bindings(
    name: str,
    members: Dict[str, str],
    aliases: Dict[str, str],
) -> None:
    members.pop(name, None)
    aliases.pop(name, None)
    for alias, value in list(aliases.items()):
        if value == name:
            aliases.pop(alias)
    for alias, member in list(members.items()):
        if re.search(rf"\b{re.escape(name)}\b", member):
            members.pop(alias)
