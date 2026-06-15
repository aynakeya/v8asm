from __future__ import annotations

import re
from typing import Dict, List, Optional

from postprocess_level4 import _compact_compound_assignments, recover_js_structures

REG_TOKEN_RE = re.compile(r"\br(\d+)\b")
IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _is_simple_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if expr.startswith(('"', "'")):
        return True
    if expr[0] in "[{":
        return True
    if expr[0].isdigit() or expr[0] in "-+" and expr[1:].isdigit():
        return True
    if expr.startswith(("global[", "context_slot[", "Const[", "undefined", "null", "true", "false")):
        return True
    if expr.startswith(("Scope[", "script_context[")):
        return True
    if expr.startswith(("String(", "create_object_literal(", "create_function_context(")):
        return True
    if IDENT_RE.match(expr):
        return True
    return False


def simplify_lines(lines: List[str], recover_structures: bool = False) -> List[str]:
    reg_values: Dict[str, str] = {}
    accu_value: Optional[str] = None
    post_goto_uncertain = False
    post_goto_protected_regs: set[str] = set()
    simplified: List[str] = []

    def replace_tokens(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            reg = f"r{match.group(1)}"
            return reg_values.get(reg, reg)

        return REG_TOKEN_RE.sub(repl, text)

    def replace_assignment_target(text: str) -> str:
        text = text.strip()
        keyed = re.match(r"^(.+)\[(r\d+)\]$", text)
        if not keyed:
            return text
        receiver, key = keyed.groups()
        return f"{receiver.strip()}[{reg_values.get(key, key)}]"

    def reset_flow_state() -> None:
        reg_values.clear()
        nonlocal accu_value
        accu_value = None

    def invalidate_aliases_depending_on(reg: str) -> None:
        for cached_reg, cached_expr in list(reg_values.items()):
            if cached_reg != reg and re.search(rf"\b{re.escape(reg)}\b", cached_expr):
                del reg_values[cached_reg]

    for line in lines:
        stripped = line.lstrip()
        prefix = line[: len(line) - len(stripped)]
        if not stripped:
            simplified.append(line)
            continue

        if (
            stripped.startswith(("if ", "while ", "goto ", "loop goto ", "return ", "throw "))
            or stripped.startswith(("// goto ", "// loop goto "))
            or stripped == "}"
            or stripped == "else {"
        ):
            if stripped.startswith(("goto ", "loop goto ")):
                simplified.append(f"{prefix}// {stripped}")
                post_goto_uncertain = True
                post_goto_protected_regs.clear()
            elif stripped.startswith(("// goto ", "// loop goto ")):
                simplified.append(line)
                post_goto_uncertain = True
                post_goto_protected_regs.clear()
            else:
                simplified.append(line)
            reset_flow_state()
            continue

        if stripped.startswith("ACCU ="):
            expr = stripped.split("=", 1)[1].strip()
            expr = replace_tokens(expr)
            accu_value = expr
            simplified.append(f"{prefix}ACCU = {expr}")
            continue

        if re.match(r"^r\d+\s*=", stripped):
            reg, expr = stripped.split("=", 1)
            reg = reg.strip()
            expr = expr.strip()
            expr_before_replace = expr
            uses_post_goto_reg = bool(
                post_goto_protected_regs
                and re.search(
                    r"\b("
                    + "|".join(re.escape(item) for item in post_goto_protected_regs)
                    + r")\b",
                    expr_before_replace,
                )
            )
            unstable_accu_alias = False
            if expr == "ACCU" and accu_value is not None:
                if "ACCU" not in accu_value:
                    expr = accu_value
                else:
                    unstable_accu_alias = True
            elif expr == "ACCU":
                unstable_accu_alias = True
            else:
                expr = replace_tokens(expr)

            simplified.append(f"{prefix}{reg} = {expr}")
            invalidate_aliases_depending_on(reg)
            if uses_post_goto_reg:
                post_goto_protected_regs -= set(re.findall(r"\br\d+\b", expr_before_replace))
                if not post_goto_protected_regs:
                    post_goto_uncertain = False
            if post_goto_uncertain and not uses_post_goto_reg:
                post_goto_protected_regs.add(reg)
                post_goto_uncertain = False
                reg_values.pop(reg, None)
            elif unstable_accu_alias or uses_post_goto_reg:
                reg_values.pop(reg, None)
            elif _is_simple_expr(expr):
                reg_values[reg] = expr
            elif reg in reg_values:
                del reg_values[reg]
            continue

        m_assignment = re.match(r"^(.+?)\s*=\s*(.+)$", stripped)
        if m_assignment and not stripped.startswith(("if ", "while ", "for ")):
            target, expr = m_assignment.groups()
            if target.rstrip().endswith(("+", "-", "*", "/", "%", "!", "<", ">", "=")):
                simplified.append(f"{prefix}{target}= {replace_tokens(expr.strip())}")
                continue
            target = replace_assignment_target(target)
            receiver_match = re.match(r"^(r\d+)(?:\.|\[)", target.strip())
            if receiver_match:
                reg = receiver_match.group(1)
                reg_values.pop(reg, None)
                invalidate_aliases_depending_on(reg)
            expr = expr.strip()
            if expr == "ACCU" and accu_value is not None and "ACCU" not in accu_value:
                expr = accu_value
            else:
                expr = replace_tokens(expr)
            simplified.append(f"{prefix}{target} = {expr}")
            continue

        simplified.append(f"{prefix}{replace_tokens(stripped)}")

    if recover_structures:
        return recover_js_structures(simplified)
    return simplified
