from __future__ import annotations

import re
from typing import List, Optional

from .context import DecompilerContext
from .instruction import Instruction
from .objects import V8Address
from .objects.bytecode import V8BytecodeArray
from .postprocess import simplify_lines
from .structurer import decompile_to_statements
from .translator import InstructionTranslator
from .utils import parse_jump_target


IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
INDENT = "  "


def _render_fragment(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    statements = decompile_to_statements(translator, instructions)
    lines: List[str] = []
    for statement in statements:
        lines.extend(statement.render(1))
    return simplify_lines(lines, recover_structures=True)


def _indent_lines(lines: List[str]) -> List[str]:
    return [f"{INDENT}{line}" if line else line for line in lines]


def _instruction_index_at_or_after(
    instructions: List[Instruction], offset: int
) -> Optional[int]:
    for index, instruction in enumerate(instructions):
        if instruction.offset >= offset:
            return index
    return None


def _accu_load_expr(
    translator: InstructionTranslator, instruction: Instruction
) -> Optional[str]:
    text = translator.translate(instruction).strip()
    match = re.match(r"^ACCU\s*=\s*(.+)$", text)
    if not match:
        return None
    expression = match.group(1).strip()
    if "ACCU" in expression:
        return None
    return expression


def _branch_path_condition(
    translator: InstructionTranslator,
    branch: Instruction,
    *,
    branch_taken: bool,
) -> Optional[str]:
    info = translator.branch_condition(branch)
    if not info:
        return None
    expression, branch_on_true = info
    if branch_taken == branch_on_true:
        return expression
    return f"!({expression})"


def _condition_with_load(condition: str, expression: str) -> Optional[str]:
    if not condition or not expression or "ACCU" in expression:
        return None
    return re.sub(r"\bACCU\b", expression, condition)


def _match_short_circuit_alternate(
    translator: InstructionTranslator,
    instructions: List[Instruction],
    prefix_instructions: List[Instruction],
    guarded_entry_offset: int,
    suffix_start_index: Optional[int],
) -> Optional[tuple[List[Instruction], str, List[Instruction], List[Instruction]]]:
    if suffix_start_index is None or suffix_start_index >= len(instructions):
        return None
    if len(prefix_instructions) < 4:
        return None

    first_load, first_jump, second_load, second_jump = prefix_instructions[-4:]
    if parse_jump_target(first_jump) != guarded_entry_offset:
        return None
    alternate_offset = parse_jump_target(second_jump)
    if alternate_offset is None:
        return None

    after_try_jump = instructions[suffix_start_index]
    if after_try_jump.mnemonic not in {"Jump", "JumpConstant"}:
        return None
    final_offset = parse_jump_target(after_try_jump)
    if final_offset is None:
        return None

    alternate_start_index = _instruction_index_at_or_after(
        instructions, alternate_offset
    )
    final_suffix_index = _instruction_index_at_or_after(instructions, final_offset)
    if (
        alternate_start_index is None
        or final_suffix_index is None
        or not (
            suffix_start_index < alternate_start_index < final_suffix_index
        )
    ):
        return None

    first_expression = _accu_load_expr(translator, first_load)
    second_expression = _accu_load_expr(translator, second_load)
    first_condition = _branch_path_condition(
        translator, first_jump, branch_taken=True
    )
    second_condition = _branch_path_condition(
        translator, second_jump, branch_taken=False
    )
    if (
        first_expression is None
        or second_expression is None
        or first_condition is None
        or second_condition is None
    ):
        return None

    first_condition = _condition_with_load(first_condition, first_expression)
    second_condition = _condition_with_load(second_condition, second_expression)
    if first_condition is None or second_condition is None:
        return None

    setup = prefix_instructions[:-4]
    alternate = instructions[alternate_start_index:final_suffix_index]
    suffix = instructions[final_suffix_index:]
    return setup, f"{first_condition} || {second_condition}", alternate, suffix


def _catch_binding_name(
    context: DecompilerContext,
    translator: InstructionTranslator,
    instruction: Instruction,
) -> str:
    if len(instruction.args) < 2:
        return "e"
    token = instruction.args[1].strip()
    if not (token.startswith("[") and token.endswith("]")):
        return "e"
    try:
        index = int(token[1:-1])
    except ValueError:
        return "e"
    entry = translator.constants.get(index)
    if not entry or not isinstance(entry.raw, V8Address):
        return "e"
    name = context.scope_context_name(entry.raw)
    if name and IDENT_RE.match(name):
        return name
    if name:
        match = re.search(r"#([^>]+)", name)
        if match and IDENT_RE.match(match.group(1)):
            return match.group(1)
    return name or "e"


def _render_single_try_catch(
    context: DecompilerContext,
    translator: InstructionTranslator,
    instructions: List[Instruction],
    entry,
) -> Optional[List[str]]:
    try_start_index = _instruction_index_at_or_after(instructions, entry.start)
    try_end_index = _instruction_index_at_or_after(instructions, entry.end)
    handler_index = _instruction_index_at_or_after(instructions, entry.handler)
    if (
        try_start_index is None
        or try_end_index is None
        or handler_index is None
    ):
        return None

    prefix_end_index = try_start_index
    if try_start_index > 0:
        scaffold = instructions[try_start_index - 1]
        if (
            scaffold.mnemonic == "Mov"
            and scaffold.args
            and scaffold.args[0] == "<context>"
        ):
            prefix_end_index = try_start_index - 1

    skip_jump_index = (
        try_end_index
        if try_end_index < len(instructions)
        and instructions[try_end_index].mnemonic in {"Jump", "JumpConstant"}
        else None
    )
    resume_offset = (
        parse_jump_target(instructions[skip_jump_index])
        if skip_jump_index is not None
        else None
    )
    suffix_start_index = (
        _instruction_index_at_or_after(instructions, resume_offset)
        if resume_offset is not None
        else len(instructions)
    )

    try_instructions = instructions[try_start_index:try_end_index]
    if not try_instructions:
        return None
    if skip_jump_index is None and try_instructions[-1].mnemonic != "Return":
        return None
    catch_instructions = instructions[
        handler_index : (
            suffix_start_index
            if suffix_start_index is not None
            else len(instructions)
        )
    ]
    if not catch_instructions:
        return None

    push_index = next(
        (
            index
            for index, instruction in enumerate(catch_instructions)
            if instruction.mnemonic == "PushContext"
        ),
        None,
    )
    if push_index is None:
        return None
    pop_index = next(
        (
            index
            for index, instruction in enumerate(
                catch_instructions[push_index + 1 :], start=push_index + 1
            )
            if instruction.mnemonic == "PopContext"
        ),
        None,
    )
    catch_body = catch_instructions[
        push_index + 1 : (
            pop_index if pop_index is not None else len(catch_instructions)
        )
    ]
    if not catch_body:
        return None

    prefix = instructions[:prefix_end_index]
    suffix = (
        instructions[suffix_start_index:]
        if suffix_start_index is not None
        else []
    )
    guard_condition: Optional[str] = None
    prefix_lines: Optional[List[str]] = None
    if prefix and resume_offset is not None:
        guard = prefix[-1]
        prefix_offsets = {instruction.offset for instruction in prefix[:-1]}
        guard_is_branch_target = any(
            parse_jump_target(instruction) == guard.offset
            for instruction in prefix[:-1]
        )
        prefix_has_external_jump = any(
            (target := parse_jump_target(instruction)) is not None
            and target not in prefix_offsets
            for instruction in prefix[:-1]
        )
        if (
            not guard_is_branch_target
            and not prefix_has_external_jump
            and guard.mnemonic.startswith("JumpIf")
            and parse_jump_target(guard) == resume_offset
        ):
            guard_condition = translator.fallthrough_condition(guard)
            if guard_condition:
                prefix = prefix[:-1]
                if "ACCU" in guard_condition and prefix:
                    last_text = translator.translate(prefix[-1]).strip()
                    last_accu = re.match(r"^ACCU\s*=\s*(.+)$", last_text)
                    if last_accu:
                        expression = last_accu.group(1).strip()
                        prefix = prefix[:-1]
                        if "ACCU" not in expression:
                            guard_condition = re.sub(
                                r"\bACCU\b", expression, guard_condition
                            )
                        else:
                            prefix_lines = _render_fragment(translator, prefix)
                            prefix_lines.append(f"{INDENT}{last_text}")

    catch_context = next(
        (
            instruction
            for instruction in catch_instructions[:push_index]
            if instruction.mnemonic == "CreateCatchContext"
        ),
        None,
    )
    if catch_context is None:
        return None
    catch_name = _catch_binding_name(context, translator, catch_context)

    try_lines = _render_fragment(translator, try_instructions)
    catch_lines = _render_fragment(translator, catch_body)
    if not try_lines or not catch_lines:
        return None

    try_catch_lines = [f"{INDENT}try {{"]
    try_catch_lines.extend(_indent_lines(try_lines))
    try_catch_lines.append(f"{INDENT}}} catch ({catch_name}) {{")
    try_catch_lines.extend(_indent_lines(catch_lines))
    try_catch_lines.append(f"{INDENT}}}")

    output: List[str] = []
    guarded_entry_offset = instructions[prefix_end_index].offset
    alternate = _match_short_circuit_alternate(
        translator,
        instructions,
        prefix,
        guarded_entry_offset,
        suffix_start_index,
    )
    if alternate is not None:
        setup, condition, alternate_instructions, final_suffix = alternate
        if setup:
            output.extend(_render_fragment(translator, setup))
        output.append(f"{INDENT}if ({condition}) {{")
        output.extend(_indent_lines(try_catch_lines))
        output.append(f"{INDENT}}} else {{")
        output.extend(
            _indent_lines(_render_fragment(translator, alternate_instructions))
        )
        output.append(f"{INDENT}}}")
        if final_suffix:
            output.extend(_render_fragment(translator, final_suffix))
        return output

    if prefix_lines is not None:
        output.extend(prefix_lines)
    elif prefix:
        output.extend(_render_fragment(translator, prefix))
    if guard_condition:
        output.append(f"{INDENT}if ({guard_condition}) {{")
        output.extend(_indent_lines(try_catch_lines))
        output.append(f"{INDENT}}}")
    else:
        output.extend(try_catch_lines)
    if suffix:
        output.extend(_render_fragment(translator, suffix))
    return output


def render_simple_try_catch(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    translator: InstructionTranslator,
    instructions: List[Instruction],
) -> Optional[List[str]]:
    for entry in bytecode.handler_entries:
        rendered = _render_single_try_catch(
            context, translator, instructions, entry
        )
        if rendered is not None:
            return rendered
    return None
