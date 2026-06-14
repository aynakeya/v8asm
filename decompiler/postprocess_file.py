from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List


IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
FUNCTION_DECL_RE = re.compile(rf"^\s*function\s+({IDENT})\s*\(")
SYNTHETIC_STRING_FUNCTION_DECL_RE = re.compile(
    rf"^\s*function\s+(String_\d+_({IDENT}))\s*\("
)


def postprocess_level4_file(text: str) -> str:
    text = recover_context_slot_closure_names(text)
    return normalize_unique_string_function_names(text)


def recover_context_slot_closure_names(text: str) -> str:
    lines = text.splitlines()
    out: List[str] = []
    reg_closures: Dict[str, str] = {}
    slot_closures: Dict[str, str] = {}
    pending_hole_name: str | None = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("function ") and stripped.endswith("{"):
            reg_closures.clear()
            slot_closures.clear()
            pending_hole_name = None

        if pending_hole_name and stripped and not stripped.startswith("//"):
            slot = re.search(r"\bcontext_slot\[(\d+)\]", stripped)
            if slot:
                slot_closures[slot.group(1)] = pending_hole_name
            pending_hole_name = None

        rewritten = _replace_context_slots(line, slot_closures)
        out.append(rewritten)
        pending_hole_name = _update_context_slot_state(
            stripped, reg_closures, slot_closures
        )

    if text.endswith("\n"):
        return "\n".join(out) + "\n"
    return "\n".join(out)


def _replace_context_slots(line: str, slot_closures: Dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        slot = match.group(1)
        return slot_closures.get(slot, match.group(0))

    return re.sub(r"\bcontext_slot\[(\d+)\]", repl, line)


def _update_context_slot_state(
    stripped: str,
    reg_closures: Dict[str, str],
    slot_closures: Dict[str, str],
) -> str | None:
    ensure = re.match(rf'^ensureDefined\("({IDENT})"\)$', stripped)
    if ensure:
        return ensure.group(1)

    reg_closure = re.match(rf"^(r\d+)\s*=\s*create_closure\(({IDENT})\)$", stripped)
    if reg_closure:
        reg_closures[reg_closure.group(1)] = reg_closure.group(2)
        return None

    reg_alias = re.match(r"^(r\d+)\s*=\s*(r\d+)$", stripped)
    if reg_alias:
        dst, src = reg_alias.groups()
        if src in reg_closures:
            reg_closures[dst] = reg_closures[src]
        else:
            reg_closures.pop(dst, None)
        return None

    reg_assign = re.match(r"^(r\d+)\s*=", stripped)
    if reg_assign:
        reg_closures.pop(reg_assign.group(1), None)

    slot_direct = re.match(
        rf"^script_context\[(\d+)\]\s*=\s*create_closure\(({IDENT})\)$",
        stripped,
    )
    if slot_direct:
        slot_closures[slot_direct.group(1)] = slot_direct.group(2)
        return None

    slot_reg = re.match(r"^script_context\[(\d+)\]\s*=\s*(r\d+)$", stripped)
    if slot_reg:
        slot, reg = slot_reg.groups()
        if reg in reg_closures:
            slot_closures[slot] = reg_closures[reg]
        else:
            slot_closures.pop(slot, None)
        return None

    slot_assign = re.match(r"^script_context\[(\d+)\]\s*=", stripped)
    if slot_assign:
        slot_closures.pop(slot_assign.group(1), None)
    return None


def normalize_unique_string_function_names(text: str) -> str:
    lines = text.splitlines()
    synthetic_decls: List[tuple[str, str]] = []
    suffix_counts: Counter[str] = Counter()
    all_decl_names: set[str] = set()

    for line in lines:
        decl = FUNCTION_DECL_RE.match(line)
        if decl:
            all_decl_names.add(decl.group(1))

        synthetic = SYNTHETIC_STRING_FUNCTION_DECL_RE.match(line)
        if synthetic:
            old_name, suffix = synthetic.groups()
            synthetic_decls.append((old_name, suffix))
            suffix_counts[suffix] += 1

    renames: Dict[str, str] = {}
    for old_name, suffix in synthetic_decls:
        if suffix_counts[suffix] != 1:
            continue
        if suffix in all_decl_names and suffix != old_name:
            continue
        renames[old_name] = suffix

    if not renames:
        return text

    names = sorted(renames, key=len, reverse=True)
    name_re = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in names) + r")\b"
    )

    def repl(match: re.Match[str]) -> str:
        return renames[match.group(1)]

    rewritten = [name_re.sub(repl, line) for line in lines]
    if text.endswith("\n"):
        return "\n".join(rewritten) + "\n"
    return "\n".join(rewritten)
