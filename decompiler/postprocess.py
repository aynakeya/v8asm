from __future__ import annotations

import re
from typing import Dict, List, Optional

REG_TOKEN_RE = re.compile(r"\br(\d+)\b")


def _is_simple_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if expr.startswith(('"', "'")):
        return True
    if expr[0].isdigit() or expr[0] in "-+" and expr[1:].isdigit():
        return True
    if expr.startswith(("global[", "context_slot[", "Const[", "undefined", "null", "true", "false")):
        return True
    if expr.startswith(("Scope[", "script_context[")):
        return True
    return False


def simplify_lines(lines: List[str]) -> List[str]:
    reg_values: Dict[str, str] = {}
    accu_value: Optional[str] = None
    simplified: List[str] = []

    def replace_tokens(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            reg = f"r{match.group(1)}"
            return reg_values.get(reg, reg)

        return REG_TOKEN_RE.sub(repl, text)

    for line in lines:
        stripped = line.lstrip()
        prefix = line[: len(line) - len(stripped)]
        if not stripped:
            simplified.append(line)
            continue

        if stripped.startswith("ACCU ="):
            expr = stripped.split("=", 1)[1].strip()
            expr = replace_tokens(expr)
            accu_value = expr
            simplified.append(f"{prefix}ACCU = {expr}")
            continue

        if stripped.startswith("r") and "=" in stripped:
            reg, expr = stripped.split("=", 1)
            reg = reg.strip()
            expr = expr.strip()
            if expr == "ACCU" and accu_value is not None:
                expr = accu_value
            else:
                expr = replace_tokens(expr)

            simplified.append(f"{prefix}{reg} = {expr}")
            if _is_simple_expr(expr):
                reg_values[reg] = expr
            elif reg in reg_values:
                del reg_values[reg]
            continue

        simplified.append(f"{prefix}{replace_tokens(stripped)}")

    return simplified
