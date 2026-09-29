"""Local expression recovery; never move an effect across a statement or branch."""

from __future__ import annotations

import re

from .common import _extract_indent, is_live_after
from .cleanup import _is_pure_expression


def compact_accumulator_expressions(lines: list[str]) -> list[str]:
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.fullmatch(r"(\s*)ACCU = (.+)", line)
        if not match:
            output.append(line)
            index += 1
            continue
        indent, value = match.groups()
        cursor = index + 1
        if cursor < len(lines) and _extract_indent(lines[cursor]) == indent:
            following = lines[cursor].strip()
            if following == "ACCU = ToName(ACCU)":
                value = f"ToName({value})"
                cursor += 1
            else:
                comparison = re.fullmatch(r"ACCU = \((r\d+|arg\d+) (in|instanceof) ACCU\)", following)
                if comparison and re.fullmatch(r"[A-Za-z_$][\w$]*", value):
                    left, operator = comparison.groups()
                    value = f"({left} {operator} {value})"
                    cursor += 1
        if cursor < len(lines) and _extract_indent(lines[cursor]) == indent:
            store = re.fullmatch(r"(r\d+(?:\.[A-Za-z_$][\w$]*)?) = ACCU", lines[cursor].strip())
            if store and not is_live_after(lines, cursor + 1, "ACCU"):
                output.append(f"{indent}{store.group(1)} = {value}")
                index = cursor + 1
                continue
            literal_store = re.fullmatch(
                r'(define_literal_property\(r\d+, (?:r\d+|"(?:\\.|[^"\\])*"), )ACCU(, (?:true|false), true\))',
                lines[cursor].strip(),
            )
            if literal_store and not is_live_after(lines, cursor + 1, "ACCU"):
                output.append(f"{indent}{literal_store[1]}{value}{literal_store[2]}")
                index = cursor + 1
                continue
        if not is_live_after(lines, cursor, "ACCU"):
            # A dead result is not a dead evaluation (getters and calls can throw).
            if not _is_pure_expression(value):
                expression = f"({value})" if value.startswith("{") else value
                output.append(f"{indent}{expression}")
        else:
            output.append(f"{indent}ACCU = {value}")
        index = cursor
    return output
