from __future__ import annotations

import re
from typing import List, Optional

from .postprocess_level4_common import _extract_indent


SIMPLE_BOUND_RECEIVER = (
    r"(?:[A-Za-z_$][A-Za-z0-9_$]*|"
    r"(?:context_slot|script_context)\[\d+\])"
)
SIMPLE_BOUND_RECEIVER_RE = re.compile(rf"^{SIMPLE_BOUND_RECEIVER}$")
DIRECT_BOUND_CALL_RE = re.compile(
    r"(?<![A-Za-z0-9_$\.\]])"
    rf"(?P<receiver>{SIMPLE_BOUND_RECEIVER})"
    r"\.(?P<method>[A-Za-z_$][A-Za-z0-9_$]*)\.call\("
)


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
            r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]]+\])+",
            expr,
        )
    )


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


def _matching_parenthesis(text: str, open_index: int) -> Optional[int]:
    depth = 0
    quote: Optional[str] = None
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
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
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return None
    return None


def _call_is_first_evaluated_expression(prefix: str) -> bool:
    remaining = prefix.strip()
    if remaining in {"return", "throw"}:
        return True
    control = re.match(r"^(?:if|while)\s*\(\s*(.*)$", remaining)
    if control:
        remaining = control.group(1)
    else:
        terminal = re.match(r"^(?:return|throw)\s+(.*)$", remaining)
        if terminal:
            remaining = terminal.group(1)
        else:
            assignment = re.match(
                r"^[A-Za-z_$][A-Za-z0-9_$]*"
                r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]]+\])*"
                r"\s*=(?!=)\s*(.*)$",
                remaining,
            )
            if assignment:
                remaining = assignment.group(1)

    wrappers = ("truthy", "isNullish", "String", "Boolean")
    while remaining:
        remaining = remaining.lstrip()
        if remaining.startswith(("(", "!", "~")):
            remaining = remaining[1:]
            continue
        wrapper = next(
            (
                name
                for name in wrappers
                if re.match(rf"^{name}\s*\(", remaining)
            ),
            None,
        )
        if wrapper is None:
            return False
        remaining = re.sub(rf"^{wrapper}\s*\(", "", remaining, count=1)
    return True


def _rewrite_adjacent_bound_call(
    line: str,
    callee: str,
    member: str,
    receiver: str,
) -> Optional[str]:
    stripped = line.strip()
    call_uses = list(
        re.finditer(rf"\b{re.escape(callee)}\.call\(", stripped)
    )
    if len(call_uses) != 1:
        return None
    call_start = call_uses[0].start()
    usage_text = stripped
    self_assignment = re.match(
        rf"^{re.escape(callee)}\s*=(?!=)", usage_text
    )
    if self_assignment:
        usage_text = usage_text[self_assignment.end() :]
    if len(re.findall(rf"\b{re.escape(callee)}\b", usage_text)) != 1:
        return None
    call_prefix = f"{callee}.call("
    if not stripped.startswith(call_prefix, call_start):
        return None
    if not _call_is_first_evaluated_expression(stripped[:call_start]):
        return None

    open_index = call_start + len(call_prefix) - 1
    close_index = _matching_parenthesis(stripped, open_index)
    if close_index is None:
        return None
    args = _split_call_args(stripped[open_index + 1 : close_index])
    if not args or args[0] != receiver:
        return None

    direct_args = ", ".join(args[1:])
    direct_call = f"{member}({direct_args})" if direct_args else f"{member}()"
    rewritten = stripped[:call_start] + direct_call + stripped[close_index + 1 :]
    return f"{_extract_indent(line)}{rewritten}"


def _temporary_has_later_use(
    lines: List[str], start: int, temporary: str, base_indent: str
) -> bool:
    for line in lines[start:]:
        stripped = line.strip()
        indent = _extract_indent(line)
        if stripped == "}" and len(indent) < len(base_indent):
            return False
        if stripped.startswith("function ") and len(indent) <= len(base_indent):
            return False
        if not re.search(rf"\b{re.escape(temporary)}\b", stripped):
            continue
        assignment = re.match(
            rf"^{re.escape(temporary)}\s*=(?!=)\s*(.*)$", stripped
        )
        if assignment and indent == base_indent:
            return bool(
                re.search(
                    rf"\b{re.escape(temporary)}\b", assignment.group(1)
                )
            )
        return True
    return False


def _fold_adjacent_bound_method_calls(lines: List[str]) -> List[str]:
    out: List[str] = []
    index = 0
    while index < len(lines):
        if index + 1 < len(lines):
            definition = re.match(r"^(r\d+)\s*=\s*(.+)$", lines[index].strip())
            if definition:
                callee, member = definition.groups()
                receiver = _member_receiver(member)
                if (
                    receiver is not None
                    and SIMPLE_BOUND_RECEIVER_RE.fullmatch(receiver)
                    and _is_member_expr(member)
                    and not re.search(rf"\b{re.escape(callee)}\b", receiver)
                    and _extract_indent(lines[index])
                    == _extract_indent(lines[index + 1])
                ):
                    next_line_assigns_temporary = re.match(
                        rf"^{re.escape(callee)}\s*=(?!=)",
                        lines[index + 1].strip(),
                    )
                    rewritten = _rewrite_adjacent_bound_call(
                        lines[index + 1], callee, member, receiver
                    )
                    if rewritten is not None and (
                        next_line_assigns_temporary
                        or not _temporary_has_later_use(
                            lines,
                            index + 2,
                            callee,
                            _extract_indent(lines[index]),
                        )
                    ):
                        out.append(rewritten)
                        index += 2
                        continue
        out.append(lines[index])
        index += 1
    return out


def _rewrite_direct_bound_method_calls(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        rewritten = line
        search_start = 0
        while match := DIRECT_BOUND_CALL_RE.search(rewritten, search_start):
            open_index = match.end() - 1
            close_index = _matching_parenthesis(rewritten, open_index)
            if close_index is None:
                break
            args = _split_call_args(rewritten[open_index + 1 : close_index])
            receiver = match.group("receiver")
            if not args or args[0] != receiver:
                search_start = close_index + 1
                continue
            call_args = ", ".join(args[1:])
            direct_call = f"{receiver}.{match.group('method')}({call_args})"
            rewritten = (
                rewritten[: match.start()]
                + direct_call
                + rewritten[close_index + 1 :]
            )
            search_start = match.start() + len(direct_call)
        out.append(rewritten)
    return out


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


def _rewrite_call_expr(expr: str) -> str:
    outer = re.match(r"^String\((.+)\)$", expr.strip())
    if outer:
        inner = outer.group(1).strip()
        rewritten_inner = _rewrite_call_expr(inner)
        if rewritten_inner != inner:
            return f"String({rewritten_inner})"

    binary = _split_wrapped_binary_expr(expr)
    if binary:
        lhs, op, rhs = binary
        rewritten_lhs = _rewrite_call_expr(lhs)
        rewritten_rhs = _rewrite_call_expr(rhs)
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
    if receiver == "undefined" and re.fullmatch(
        r"[A-Za-z_$][A-Za-z0-9_$]*|r\d+",
        callee,
    ):
        return f"{callee}({call_args})" if call_args else f"{callee}()"
    member_receiver = _member_receiver(callee)
    if (
        member_receiver != receiver
        or not SIMPLE_BOUND_RECEIVER_RE.fullmatch(receiver)
    ):
        return expr
    return f"{callee}({call_args})" if call_args else f"{callee}()"


def _rewrite_bound_method_calls(lines: List[str]) -> List[str]:
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
            expr = _rewrite_call_expr(expr.strip())
            out.append(f"{indent}{lhs} = {expr}")
            continue

        m_return = re.match(r"^return\s+(.+)$", stripped)
        if m_return:
            expr = _rewrite_call_expr(m_return.group(1).strip())
            out.append(f"{indent}return {expr}")
            continue

        m_compound = re.match(r"^(.+?\s*[+\-*/%]=)\s*(.+)$", stripped)
        if m_compound:
            lhs, expr = m_compound.groups()
            out.append(
                f"{indent}{lhs} "
                f"{_rewrite_call_expr(expr.strip())}"
            )
            continue

        rewritten = _rewrite_call_expr(stripped)
        out.append(f"{indent}{rewritten}" if rewritten != stripped else line)

    return out
