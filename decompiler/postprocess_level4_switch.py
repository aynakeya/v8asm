from __future__ import annotations

from collections import Counter
import re
from typing import Dict, List, Optional, Tuple

from postprocess_level4_common import _extract_indent


def _recover_constant_dispatch_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        replacement = _match_constant_dispatch_assignment(lines, i)
        if replacement is None:
            out.append(lines[i])
            i += 1
            continue
        rendered, consumed = replacement
        out.extend(rendered)
        i = consumed
    return out


def _match_constant_dispatch_assignment(
    lines: List[str], start: int
) -> Optional[Tuple[List[str], int]]:
    cases: List[Tuple[str, str, int]] = []
    cursor = start
    while cursor + 2 < len(lines):
        case_value = _match_accu_load(lines[cursor].strip())
        comparison = _match_accu_compare(lines[cursor + 1].strip())
        target = _match_truthy_goto(lines[cursor + 2].strip())
        if case_value is None or comparison is None or target is None:
            break
        if not _is_dispatch_literal(case_value):
            return None
        cases.append((case_value, comparison, target))
        cursor += 3

    if len(cases) < 2:
        return None

    default_target = (
        _match_goto_comment(lines[cursor].strip()) if cursor < len(lines) else None
    )
    if default_target is None:
        return None
    cursor += 1

    ordered_targets = sorted({target for _, _, target in cases})
    body_targets = ordered_targets + [default_target]
    body_values: Dict[int, str] = {}
    destination: Optional[str] = None

    for target in body_targets:
        while cursor < len(lines) and _match_goto_comment(lines[cursor].strip()) is not None:
            cursor += 1
        parsed = _parse_assignment_body(lines, cursor)
        if parsed is None:
            return None
        dst, expr, cursor = parsed
        if destination is None:
            destination = dst
        elif destination != dst:
            return None
        body_values[target] = expr

    if destination is None or default_target not in body_values:
        return None

    subject = _dominant_dispatch_subject([subject for _, subject, _ in cases])
    if subject is None:
        return None

    entries: List[str] = []
    for key, _, target in cases:
        value = body_values.get(target)
        if value is None:
            return None
        entries.append(f"{key}: {value}")

    indent = _extract_indent(lines[start])
    mapping = "{" + ", ".join(entries) + "}"
    default_expr = body_values[default_target]
    rendered = [f"{indent}{destination} = ({mapping}[{subject}] ?? {default_expr})"]
    return rendered, cursor


def _match_accu_load(stripped: str) -> Optional[str]:
    match = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
    return match.group(1).strip() if match else None


def _match_accu_compare(stripped: str) -> Optional[str]:
    match = re.match(r"^ACCU\s*=\s*\((.+?)\s*(?:===|==)\s*ACCU\)$", stripped)
    return match.group(1).strip() if match else None


def _match_truthy_goto(stripped: str) -> Optional[int]:
    match = re.match(r"^if \((?:truthy\(ACCU\)|ACCU)\) goto offset_(\d+)$", stripped)
    return int(match.group(1)) if match else None


def _match_goto_comment(stripped: str) -> Optional[int]:
    match = re.match(r"^// goto offset_(\d+)$", stripped)
    return int(match.group(1)) if match else None


def _parse_assignment_body(lines: List[str], start: int) -> Optional[Tuple[str, str, int]]:
    if start >= len(lines):
        return None

    stripped = lines[start].strip()
    accu_expr = _match_accu_load(stripped)
    if accu_expr is not None:
        if start + 1 >= len(lines):
            return None
        assignment = _match_non_accu_assignment(lines[start + 1].strip())
        if assignment is None:
            return None
        dst, expr = assignment
        if expr == "ACCU":
            expr = accu_expr
        if expr != accu_expr:
            return None
        return dst, expr, start + 2

    assignment = _match_non_accu_assignment(stripped)
    if assignment is None:
        return None
    dst, expr = assignment
    return dst, expr, start + 1


def _match_non_accu_assignment(stripped: str) -> Optional[Tuple[str, str]]:
    if stripped.startswith(("if ", "while ", "for ", "return ", "throw ", "//")):
        return None
    match = re.match(r"^(.+?)\s*=\s*(.+)$", stripped)
    if not match:
        return None
    dst, expr = match.group(1).strip(), match.group(2).strip()
    if dst == "ACCU":
        return None
    return dst, expr


def _dominant_dispatch_subject(subjects: List[str]) -> Optional[str]:
    if not subjects:
        return None
    counts = Counter(subjects)
    candidates = sorted(
        counts.items(),
        key=lambda item: (item[1], bool(re.fullmatch(r"r\d+", item[0]))),
        reverse=True,
    )
    subject, count = candidates[0]
    if count < len(subjects) - 1:
        return None
    return subject


def _is_dispatch_literal(expr: str) -> bool:
    if re.fullmatch(r"[-+]?\d+", expr):
        return True
    if re.fullmatch(r'"(?:\\.|[^"\\])*"', expr):
        return expr != '"__proto__"'
    if re.fullmatch(r"'(?:\\.|[^'\\])*'", expr):
        return expr != "'__proto__'"
    return False


def _recover_switch_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        replacement = _match_two_case_assignment_switch(lines, i)
        if replacement is None:
            out.append(lines[i])
            i += 1
            continue
        rendered, consumed = replacement
        out.extend(rendered)
        i = consumed
    return out


def _match_two_case_assignment_switch(
    lines: List[str], start: int
) -> Optional[Tuple[List[str], int]]:
    if start + 18 >= len(lines):
        return None

    def strip(idx: int) -> str:
        return lines[idx].strip()

    def assign(idx: int) -> Optional[Tuple[str, str]]:
        match = re.match(r"^(r\d+)\s*=\s*(.+)$", strip(idx))
        if not match:
            return None
        return match.group(1), match.group(2).strip()

    case1_line = strip(start)
    cmp1_line = strip(start + 1)
    m_case1 = re.match(r"^ACCU = (.+)$", case1_line)
    m_cmp1 = re.match(r"^ACCU = \((.+) === ACCU\)$", cmp1_line)
    if not m_case1 or not m_cmp1:
        return None

    alias_reg = None
    alias_value = None
    cursor = start + 2
    alias_match = assign(cursor)
    if alias_match is not None and alias_match[1] == m_cmp1.group(1).strip():
        alias_reg, alias_value = alias_match
        cursor += 1

    if strip(cursor) != "if (!(truthy(ACCU))) {":
        return None
    cursor += 1

    m_case2 = re.match(r"^ACCU = (.+)$", strip(cursor))
    m_cmp2 = re.match(r"^ACCU = \((.+) === ACCU\)$", strip(cursor + 1))
    if not m_case2 or not m_cmp2:
        return None
    if strip(cursor + 2) != "if (!(truthy(ACCU))) {":
        return None
    if not strip(cursor + 3).startswith("// goto offset_"):
        return None
    if strip(cursor + 4) != "}":
        return None
    if strip(cursor + 5) != "else {":
        return None
    value2_line = strip(cursor + 6)
    dst2 = assign(cursor + 7)
    if strip(cursor + 8) != "}":
        return None
    if strip(cursor + 9) != "}":
        return None
    if strip(cursor + 10) != "else {":
        return None
    value1_line = strip(cursor + 11)
    dst1 = assign(cursor + 12)
    if not strip(cursor + 13).startswith("// goto offset_"):
        return None
    if strip(cursor + 14) != "}":
        return None
    default_line = strip(cursor + 15)
    dst0 = assign(cursor + 16)
    if not dst0 or not dst1 or not dst2:
        return None

    m_value1 = re.match(r"^ACCU = (.+)$", value1_line)
    m_value2 = re.match(r"^ACCU = (.+)$", value2_line)
    m_default = re.match(r"^ACCU = (.+)$", default_line)
    if not m_value1 or not m_value2 or not m_default:
        return None
    if dst0[0] != dst1[0] or dst0[0] != dst2[0]:
        return None
    if dst0[1] != m_default.group(1).strip():
        return None
    if dst1[1] != m_value1.group(1).strip():
        return None
    if dst2[1] != m_value2.group(1).strip():
        return None

    subject1 = m_cmp1.group(1).strip()
    subject2 = m_cmp2.group(1).strip()
    if alias_reg and subject2 == alias_reg:
        subject2 = alias_value or subject2
    if subject1 != subject2:
        return None

    indent = _extract_indent(lines[start])
    condition = (
        f"(({subject1} === {m_case1.group(1).strip()}) ? "
        f"{m_value1.group(1).strip()} : "
        f"(({subject1} === {m_case2.group(1).strip()}) ? "
        f"{m_value2.group(1).strip()} : {m_default.group(1).strip()}))"
    )
    rendered = [
        f"{indent}{dst0[0]} = {condition}",
    ]
    return rendered, cursor + 17


def _recover_two_case_switch(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 13 < len(lines):
            s = [lines[i + k].strip() for k in range(14)]
            m1 = re.match(r"^ACCU = \((.+) === ACCU\)$", s[1])
            m2 = re.match(r"^ACCU = \((.+) === ACCU\)$", s[4])
            mret1 = re.match(r"^return (.+)$", s[10])
            mret2 = re.match(r"^return (.+)$", s[11])
            mret3 = re.match(r"^return (.+)$", s[13])
            if (
                s[2] == "if (!(truthy(ACCU))) {"
                and s[5] == "if (!(truthy(ACCU))) {"
                and s[6].startswith("// goto offset_")
                and s[7] == "}"
                and s[8] == "}"
                and s[9] == "else {"
                and s[12] == "}"
                and m1
                and m2
                and mret1
                and mret2
                and mret3
            ):
                v1 = s[0].replace("ACCU = ", "", 1).strip()
                v2 = s[3].replace("ACCU = ", "", 1).strip()
                cond1 = f"({m1.group(1)} === {v1})"
                cond2 = f"({m2.group(1)} === {v2})"
                indent = _extract_indent(lines[i])
                in2 = indent + "  "
                out.extend(
                    [
                        f"{indent}if {cond1} {{",
                        f"{in2}return {mret1.group(1)}",
                        f"{indent}}}",
                        f"{indent}if {cond2} {{",
                        f"{in2}return {mret2.group(1)}",
                        f"{indent}}}",
                        f"{indent}return {mret3.group(1)}",
                    ]
                )
                i += 14
                continue
        out.append(lines[i])
        i += 1
    return out
