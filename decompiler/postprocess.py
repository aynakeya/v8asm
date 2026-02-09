from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

REG_TOKEN_RE = re.compile(r"\br(\d+)\b")
IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


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
    if IDENT_RE.match(expr):
        return True
    return False


def simplify_lines(lines: List[str], recover_structures: bool = False) -> List[str]:
    reg_values: Dict[str, str] = {}
    accu_value: Optional[str] = None
    simplified: List[str] = []

    def replace_tokens(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            reg = f"r{match.group(1)}"
            return reg_values.get(reg, reg)

        return REG_TOKEN_RE.sub(repl, text)

    def reset_flow_state() -> None:
        reg_values.clear()
        nonlocal accu_value
        accu_value = None

    for line in lines:
        stripped = line.lstrip()
        prefix = line[: len(line) - len(stripped)]
        if not stripped:
            simplified.append(line)
            continue

        if (
            stripped.startswith(("if ", "while ", "goto ", "loop goto ", "return ", "throw "))
            or stripped == "}"
            or stripped == "else {"
        ):
            if stripped.startswith(("goto ", "loop goto ")):
                simplified.append(f"{prefix}// {stripped}")
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

        if stripped.startswith("r") and "=" in stripped:
            reg, expr = stripped.split("=", 1)
            reg = reg.strip()
            expr = expr.strip()
            if expr == "ACCU" and accu_value is not None:
                if "ACCU" not in accu_value:
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

    if recover_structures:
        return recover_js_structures(simplified)
    return simplified


def _find_block_end(lines: List[str], start: int) -> Optional[int]:
    depth = 0
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip()
        if stripped.endswith("{"):
            depth += 1
        if stripped == "}":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _extract_indent(line: str) -> str:
    stripped = line.lstrip()
    return line[: len(line) - len(stripped)]


def _compact_compound_assignments(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("ACCU = ") and i + 2 < len(lines):
            expr = s[len("ACCU = ") :]
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m = re.match(r"^ACCU = \((r\d+) \+ ACCU\)$", s1)
            if not m:
                m = re.match(r"^ACCU = \(ACCU \+ (r\d+)\)$", s1)
            if m and s2 == f"{m.group(1)} = ACCU":
                indent = _extract_indent(lines[i + 2])
                out.append(f"{indent}{m.group(1)} += {expr}")
                i += 3
                continue
            m2 = re.match(r"^ACCU = \(ACCU \+ ([-+]?\d+)\)$", s1)
            if m2 and re.match(r"^r\d+ = ACCU$", s2):
                dst = s2.split("=", 1)[0].strip()
                if expr == dst:
                    indent = _extract_indent(lines[i + 2])
                    out.append(f"{indent}{dst} += {m2.group(1)}")
                    i += 3
                    continue

        if out and out[-1].strip() == s and s.startswith("ACCU = "):
            i += 1
            continue

        out.append(lines[i])
        i += 1
    return out


def _parse_iter_setup(lines: List[str]) -> Optional[Tuple[int, int, str, str, str]]:
    for i in range(len(lines) - 3):
        s0 = lines[i].strip()
        s1 = lines[i + 1].strip()
        s2 = lines[i + 2].strip()
        s3 = lines[i + 3].strip()

        if not s0.startswith("ACCU = GetIterator(") or not s0.endswith(")"):
            continue
        source = s0[len("ACCU = GetIterator(") : -1]
        m1 = re.match(r"^(r\d+) = GetIterator\((.+)\)$", s1)
        if not m1:
            continue
        iter_reg = m1.group(1)
        if m1.group(2) != source:
            continue
        m2 = re.match(rf"^ACCU = {re.escape(iter_reg)}\.next$", s2)
        m3 = re.match(rf"^(r\d+) = {re.escape(iter_reg)}\.next$", s3)
        if not m2 or not m3:
            continue
        next_reg = m3.group(1)
        return i, i + 3, source, iter_reg, next_reg
    return None


def _recover_for_of(lines: List[str]) -> List[str]:
    setup = _parse_iter_setup(lines)
    if not setup:
        return lines
    setup_start, setup_end, source, iter_reg, next_reg = setup

    while_idx = None
    while_end = None
    for i in range(setup_end + 1, len(lines)):
        if lines[i].strip() != "while (!(truthy(ACCU))) {":
            continue
        end = _find_block_end(lines, i)
        if end is None:
            continue
        while_idx = i
        while_end = end
        break
    if while_idx is None or while_end is None:
        return lines

    body = lines[while_idx + 1 : while_end]
    next_call_a = f"ACCU = {next_reg}.call({iter_reg})"
    next_call_b = re.compile(rf"^(r\d+) = {re.escape(next_reg)}\.call\({re.escape(iter_reg)}\)$")
    result_reg = None
    for line in body:
        s = line.strip()
        if next_call_a == s:
            continue
        m = next_call_b.match(s)
        if m:
            result_reg = m.group(1)
            break
    if not result_reg:
        return lines

    flag_reg = None
    for line in body:
        m_flag = re.match(r"^(r\d+) = true$", line.strip())
        if m_flag:
            flag_reg = m_flag.group(1)
            break

    inner_if_start = None
    inner_if_end = None
    for idx in range(while_idx + 1, while_end):
        if lines[idx].strip() == "if (!(truthy(ACCU))) {":
            end = _find_block_end(lines, idx)
            if end is None or end > while_end:
                continue
            inner_if_start = idx
            inner_if_end = end
            break
    if inner_if_start is None or inner_if_end is None:
        return lines

    inner_body = lines[inner_if_start + 1 : inner_if_end]
    loop_var = None
    assign_re = re.compile(rf"^(r\d+) = {re.escape(result_reg)}$")
    for line in inner_body:
        m = assign_re.match(line.strip())
        if m:
            loop_var = m.group(1)
            break
    if not loop_var:
        loop_var = "item"

    filtered: List[str] = []
    for line in inner_body:
        s = line.strip()
        if s in {"ACCU = false", "ACCU = true"}:
            continue
        if s == f"{loop_var} = {result_reg}":
            continue
        if s in {f"r6 = false", f"r6 = true"}:
            continue
        if s == f"ACCU = {result_reg}.value":
            s = f"ACCU = {loop_var}"
        elif s == f"{result_reg} = {result_reg}.value":
            continue
        elif s == f"{loop_var} = {result_reg}":
            continue
        if s.startswith(f"{loop_var} ="):
            continue
        m_noop = re.match(r"^(r\d+) = \1$", s)
        if m_noop:
            continue
        filtered.append(s)
    filtered = _compact_compound_assignments(filtered)
    filtered = _drop_unused_reg_assignments(filtered)

    loop_var_name = "item"
    body_text = "\n".join(filtered)
    if re.search(r"\bitem\b", body_text):
        loop_var_name = "item1"
    if loop_var_name != loop_var:
        filtered = [
            re.sub(rf"\b{re.escape(loop_var)}\b", loop_var_name, stmt) for stmt in filtered
        ]

    if result_reg != loop_var_name:
        needs_alias = any(re.search(rf"\b{re.escape(result_reg)}\b", stmt) for stmt in filtered)
        if needs_alias:
            filtered.insert(0, f"{result_reg} = {loop_var_name}")

    while_indent = _extract_indent(lines[while_idx])
    body_indent = while_indent + "  "
    replacement = [f"{while_indent}for (const {loop_var_name} of {source}) {{"]
    for stmt in filtered:
        replacement.append(f"{body_indent}{stmt}")
    replacement.append(f"{while_indent}}}")

    out: List[str] = []
    skip_ranges: List[Tuple[int, int]] = []
    if flag_reg:
        for idx in range(while_end + 1, len(lines) - 1):
            if lines[idx].strip() != f"ACCU = {flag_reg}":
                continue
            if lines[idx + 1].strip() != "if (!(truthy(ACCU))) {":
                continue
            end = _find_block_end(lines, idx + 1)
            if end is None:
                continue
            block_text = "\n".join(lines[idx + 1 : end + 1])
            if f"{iter_reg}.return" not in block_text:
                continue
            start = idx
            if idx >= 4:
                p0 = lines[idx - 4].strip()
                p1 = lines[idx - 3].strip()
                p2 = lines[idx - 2].strip()
                p3 = lines[idx - 1].strip()
                if (
                    p0 == "ACCU = -1"
                    and re.match(r"^r\d+ = -1$", p1)
                    and re.match(r"^r\d+ = -1$", p2)
                    and p3.startswith("// goto offset_")
                ):
                    start = idx - 4
            skip_ranges.append((start, end))
            break

    def in_skip_ranges(i: int) -> bool:
        for a, b in skip_ranges:
            if a <= i <= b:
                return True
        return False

    for idx, line in enumerate(lines):
        if in_skip_ranges(idx):
            continue
        if setup_start <= idx <= setup_end:
            continue
        if idx == while_idx:
            out.extend(replacement)
            continue
        if while_idx < idx <= while_end:
            continue
        out.append(line)
    return out


def recover_js_structures(lines: List[str]) -> List[str]:
    current = lines
    while True:
        nxt = _recover_for_of(current)
        if nxt == current:
            break
        current = nxt
    current = _strip_iterator_exception_guard(current)
    current = _strip_pending_message_status_guard(current)
    current = _inline_single_use_registers(current)
    current = _compact_accu_compare_if(current)
    current = _simplify_accu_return(current)
    current = _flatten_else_after_early_exit(current)
    current = _recover_two_case_switch(current)
    current = _convert_unused_accu_assign_to_expr(current)
    return current


def _strip_iterator_exception_guard(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            if (
                s0 == "ACCU = 0"
                and re.match(r"^ACCU = \(r\d+ === ACCU\)$", s1)
                and s2 == "if (truthy(ACCU)) {"
            ):
                end = _find_block_end(lines, i + 2)
                if end is not None:
                    block_text = "\n".join(lines[i + 2 : end + 1])
                    if "// SetPendingMessage" in block_text and "throw ACCU" in block_text:
                        i = end + 1
                        continue
        out.append(lines[i])
        i += 1
    return out


def _strip_pending_message_status_guard(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            if (
                s0 == "ACCU = 0"
                and re.match(r"^ACCU = \(r\d+ === ACCU\)$", s1)
                and s2 == "if (truthy(ACCU)) {"
            ):
                end = _find_block_end(lines, i + 2)
                if end is not None:
                    final_end = end
                    if end + 1 < len(lines) and lines[end + 1].strip() == "else {":
                        else_end = _find_block_end(lines, end + 1)
                        if else_end is not None:
                            final_end = else_end
                    block = "\n".join(lines[i + 2 : final_end + 1])
                    if "// SetPendingMessage" in block:
                        i = final_end + 1
                        continue
        out.append(lines[i])
        i += 1
    return out


def _drop_unused_reg_assignments(lines: List[str]) -> List[str]:
    usage = _count_reg_uses(lines)
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^(r\d+)\s*=\s*(.+)$", stripped)
        if m and usage.get(m.group(1), 0) == 0:
            continue
        out.append(line)
    return out


def _count_reg_uses(lines: List[str]) -> Dict[str, int]:
    usage: Dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        assign = re.match(r"^(r\d+)\s*=", stripped)
        lhs = assign.group(1) if assign else None
        for reg in re.findall(r"\br\d+\b", stripped):
            if reg == lhs and stripped.startswith(f"{reg} ="):
                continue
            usage[reg] = usage.get(reg, 0) + 1
    return usage


def _is_inline_safe_expr(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if expr.startswith(("true", "false", "null", "undefined", "HOLE", '"', "'")):
        return True
    if re.fullmatch(r"[-+]?\d+", expr):
        return True
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(\.[A-Za-z_$][A-Za-z0-9_$]*)*", expr):
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
            m = re.match(r"^(\s*)(r\d+)\s*=\s*(.+)$", line)
            if not m:
                continue
            _indent, reg, expr = m.groups()
            expr = expr.strip()
            if usage.get(reg, 0) != 1 or not _is_inline_safe_expr(expr):
                continue

            for j in range(i + 1, len(out)):
                stripped = out[j].strip()
                if re.match(rf"^{re.escape(reg)}\s*=", stripped):
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


def _simplify_accu_return(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            if s1 == "return ACCU" and s0.startswith("ACCU = "):
                expr = s0[len("ACCU = ") :].strip()
                indent = _extract_indent(lines[i + 1])
                out.append(f"{indent}return {expr}")
                i += 2
                continue
        out.append(lines[i])
        i += 1
    return out


def _flatten_else_after_early_exit(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("if (") and stripped.endswith("{"):
            then_end = _find_block_end(lines, i)
            if then_end is not None and then_end + 1 < len(lines):
                else_line = lines[then_end + 1].strip()
                if else_line == "else {":
                    else_end = _find_block_end(lines, then_end + 1)
                    if else_end is not None:
                        then_body = lines[i + 1 : then_end]
                        last_then = ""
                        for t in reversed(then_body):
                            st = t.strip()
                            if st:
                                last_then = st
                                break
                        if last_then.startswith(("return ", "throw ")):
                            out.extend(lines[i : then_end + 1])
                            out.extend(lines[then_end + 2 : else_end])
                            i = else_end + 1
                            continue
        out.append(line)
        i += 1
    return out


def _expr_reg_uses(expr: str) -> List[str]:
    return re.findall(r"\br\d+\b", expr)


def _expr_uses_accu(expr: str) -> bool:
    return bool(re.search(r"\bACCU\b", expr))


def _is_pure_expr_level4(expr: str) -> bool:
    expr = expr.strip()
    if not expr:
        return False
    if expr.startswith(("true", "false", "null", "undefined", "HOLE", '"', "'")):
        return True
    if re.fullmatch(r"[-+]?\d+", expr):
        return True
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(\.[A-Za-z_$][A-Za-z0-9_$]*)*", expr):
        return True
    if expr.startswith(("context_slot[", "script_context[", "globalThis[")):
        return True
    if expr.startswith("(") and expr.endswith(")") and "call(" not in expr:
        return True
    return False


def _dead_store_eliminate_chunk(lines: List[str]) -> List[str]:
    live_regs = set()
    live_accu = False
    keep = [True] * len(lines)

    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        m_reg = re.match(r"^(r\d+)\s*=\s*(.+)$", stripped)
        m_accu = re.match(r"^ACCU\s*=\s*(.+)$", stripped)
        if m_reg:
            reg, expr = m_reg.groups()
            expr = expr.strip()
            live_regs.discard(reg)
            for used in _expr_reg_uses(expr):
                live_regs.add(used)
            if _expr_uses_accu(expr):
                live_accu = True
            continue

        if m_accu:
            expr = m_accu.group(1).strip()
            if not live_accu and _is_pure_expr_level4(expr):
                keep[i] = False
                continue
            live_accu = False
            for used in _expr_reg_uses(expr):
                live_regs.add(used)
            if _expr_uses_accu(expr):
                live_accu = True
            continue

        for used in re.findall(r"\br\d+\b", stripped):
            live_regs.add(used)
        if re.search(r"\bACCU\b", stripped):
            live_accu = True

    return [line for i, line in enumerate(lines) if keep[i]]


def _dead_store_eliminate_level4(lines: List[str]) -> List[str]:
    out: List[str] = []
    chunk: List[str] = []

    def flush_chunk() -> None:
        nonlocal chunk
        if chunk:
            out.extend(_dead_store_eliminate_chunk(chunk))
            chunk = []

    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith(("if ", "for ", "while ", "else"))
            or stripped in {"{", "}"}
            or stripped.startswith(("return ", "throw ", "//"))
        ):
            flush_chunk()
            out.append(line)
            continue
        chunk.append(line)

    flush_chunk()
    return out


def _drop_dead_reg_assignments_local(lines: List[str]) -> List[str]:
    keep = [True] * len(lines)

    def is_boundary(s: str) -> bool:
        return (
            s.startswith(("if ", "for ", "while ", "else "))
            or s in {"{", "}"}
            or s.startswith(("return ", "throw "))
        )

    for i, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r"^(r\d+)\s*=\s*(.+)$", stripped)
        if not m:
            continue
        reg, expr = m.groups()
        expr = expr.strip()
        if not _is_pure_expr_level4(expr):
            continue

        used = False
        for j in range(i + 1, len(lines)):
            s = lines[j].strip()
            if is_boundary(s):
                if s.startswith(("if ", "for ", "while ")) and s.endswith("{"):
                    end = _find_block_end(lines, j)
                    if end is not None:
                        for k in range(j + 1, end):
                            sk = lines[k].strip()
                            if re.search(rf"\b{re.escape(reg)}\b", sk) and not re.match(
                                rf"^{re.escape(reg)}\s*=", sk
                            ):
                                used = True
                                break
                break
            if re.search(rf"\b{re.escape(reg)}\b", s) and not re.match(
                rf"^{re.escape(reg)}\s*=", s
            ):
                used = True
                break
            if re.match(rf"^{re.escape(reg)}\s*=", s):
                used = False
                break
        if not used:
            keep[i] = False

    return [line for i, line in enumerate(lines) if keep[i]]


def _convert_unused_accu_assign_to_expr(lines: List[str]) -> List[str]:
    out = lines[:]
    for i, line in enumerate(out):
        m = re.match(r"^(\s*)ACCU\s*=\s*(.+)$", line)
        if not m:
            continue
        indent, expr = m.groups()
        expr = expr.strip()
        if _is_pure_expr_level4(expr) or "(" not in expr:
            continue

        used = False
        for j in range(i + 1, len(out)):
            s = out[j].strip()
            if re.match(r"^ACCU\s*=", s):
                break
            if re.search(r"\bACCU\b", s):
                used = True
                break
            if s.startswith(("if ", "for ", "while ", "else ")) or s in {"{", "}"}:
                break
        if not used:
            out[i] = f"{indent}{expr}"
    return out


def _compact_accu_compare_if(lines: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines):
            s0 = lines[i].strip()
            s1 = lines[i + 1].strip()
            s2 = lines[i + 2].strip()
            m0 = re.match(r"^ACCU = ([-+]?\d+)$", s0)
            m1 = re.match(r"^ACCU = \((.+)\s*([><]=?|===|!==)\s*ACCU\)$", s1)
            if m0 and m1 and s2 == "if (truthy(ACCU)) {":
                indent = _extract_indent(lines[i + 2])
                lhs, op = m1.group(1).strip(), m1.group(2)
                out.append(f"{indent}if ({lhs} {op} {m0.group(1)}) {{")
                i += 3
                continue
        out.append(lines[i])
        i += 1
    return out


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
