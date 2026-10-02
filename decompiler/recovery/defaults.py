from __future__ import annotations

import re
from typing import List

from .common import _extract_indent, is_live_after, uses_identifier


def recover_undefined_default_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        recovered = _try_recover_undefined_default(lines, i)
        if recovered is not None:
            rendered, i = recovered
            out.extend(rendered)
        else:
            out.append(lines[i])
            i += 1
    return out


def _try_recover_undefined_default(
    lines: List[str], start: int
) -> tuple[List[str], int] | None:
    initial = re.match(r"^ACCU\s*=\s*(.+)$", lines[start].strip())
    if not initial:
        return None

    cursor = start + 1
    saved_lines: List[str] = []
    while cursor < len(lines) and _is_simple_reg_save(lines[cursor].strip()):
        saved_lines.append(lines[cursor])
        cursor += 1

    if cursor + 3 >= len(lines):
        return None
    fallback = re.match(r"^ACCU\s*=\s*(.+)$", lines[cursor + 1].strip())
    if (
        lines[cursor].strip() != "if (!(ACCU !== undefined)) {"
        or not fallback
        or lines[cursor + 2].strip() != "}"
    ):
        return None
    cursor += 3

    otherwise = "ACCU"
    if lines[cursor].strip() == "else {":
        if cursor + 3 >= len(lines):
            return None
        explicit_else = re.match(r"^ACCU\s*=\s*(.+)$", lines[cursor + 1].strip())
        if not explicit_else or lines[cursor + 2].strip() != "}":
            return None
        otherwise = explicit_else.group(1)
        cursor += 3

    store = re.fullmatch(r"(r\d+)\s*=\s*ACCU", lines[cursor].strip())
    if not store:
        return None
    dest = store.group(1)
    indent = _extract_indent(lines[cursor])
    # Keep the first read before saved receivers and reuse it when the default is not taken.
    rendered = [lines[start], *saved_lines]
    condition = "ACCU"
    value = initial.group(1)
    if (
        not saved_lines and re.fullmatch(r"(?:r|arg)\d+", value)
        and not uses_identifier(fallback.group(1), "ACCU")
        and (otherwise == "ACCU" or not uses_identifier(otherwise, "ACCU"))
    ):
        rendered = []
        condition = value
        if otherwise == "ACCU":
            otherwise = value
    rendered.append(f"{indent}{dest} = ({condition} === undefined ? {fallback.group(1)} : {otherwise})")
    if is_live_after(lines, cursor + 1, "ACCU"):
        rendered.append(f"{indent}ACCU = {dest}")
    return rendered, cursor + 1


def _is_simple_reg_save(stripped: str) -> bool:
    match = re.match(r"^r\d+\s*=\s*(.+)$", stripped)
    if not match:
        return False
    expr = match.group(1).strip()
    if "ACCU" in expr or "(" in expr:
        return False
    return bool(
        re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?", expr)
        or re.fullmatch(r"[-+]?\d+", expr)
        or expr in {"true", "false", "null", "undefined", "this", "closure", "context"}
    )
