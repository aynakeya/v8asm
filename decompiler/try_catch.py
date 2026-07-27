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
    return re.sub(r"\bACCU\b", lambda _match: expression, condition)


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


def _star_target(instruction: Instruction) -> Optional[str]:
    if instruction.mnemonic == "Star" and instruction.args:
        return instruction.args[0].strip()
    match = re.fullmatch(r"Star(\d+)", instruction.mnemonic)
    return f"r{match.group(1)}" if match else None


def _load_source(instruction: Instruction) -> Optional[str]:
    if instruction.mnemonic == "Ldar" and instruction.args:
        return instruction.args[0].strip()
    match = re.fullmatch(r"Ldar(\d+)", instruction.mnemonic)
    return f"r{match.group(1)}" if match else None


def _smi_value(instruction: Instruction) -> Optional[int]:
    if instruction.mnemonic == "LdaZero":
        return 0
    if instruction.mnemonic != "LdaSmi" or not instruction.args:
        return None
    token = instruction.args[0].strip()
    if token.startswith("[") and token.endswith("]"):
        token = token[1:-1]
    try:
        return int(token)
    except ValueError:
        return None


def _match_finally_handler(
    instructions: List[Instruction], handler_index: int
) -> Optional[tuple[str, str, str, int]]:
    if handler_index + 6 > len(instructions):
        return None
    result_register = _star_target(instructions[handler_index])
    if result_register is None or _smi_value(instructions[handler_index + 1]) != 0:
        return None
    completion_register = _star_target(instructions[handler_index + 2])
    if completion_register is None:
        return None
    if (
        instructions[handler_index + 3].mnemonic != "LdaTheHole"
        or instructions[handler_index + 4].mnemonic != "SetPendingMessage"
    ):
        return None
    pending_register = _star_target(instructions[handler_index + 5])
    if pending_register is None:
        return None
    return (
        result_register,
        completion_register,
        pending_register,
        handler_index + 6,
    )


def _match_finally_dispatch(
    instructions: List[Instruction],
    start_index: int,
    result_register: str,
    completion_register: str,
    pending_register: str,
) -> Optional[tuple[int, int]]:
    for index in range(start_index, len(instructions) - 8):
        branch = instructions[index + 2]
        if (
            _smi_value(instructions[index]) != 0
            or instructions[index + 1].mnemonic != "TestReferenceEqual"
            or not instructions[index + 1].args
            or instructions[index + 1].args[0].strip() != completion_register
            or branch.mnemonic not in {"JumpIfFalse", "JumpIfFalseConstant"}
            or _load_source(instructions[index + 3]) != pending_register
            or instructions[index + 4].mnemonic != "SetPendingMessage"
            or _load_source(instructions[index + 5]) != result_register
            or instructions[index + 6].mnemonic != "ReThrow"
        ):
            continue
        return_offset = parse_jump_target(branch)
        return_index = (
            _instruction_index_at_or_after(instructions, return_offset)
            if return_offset is not None
            else None
        )
        if (
            return_index is None
            or return_index != index + 7
            or _load_source(instructions[return_index]) != result_register
            or instructions[return_index + 1].mnemonic != "Return"
        ):
            continue
        return index, return_index + 2
    return None


def _match_return_completion(
    translator: InstructionTranslator,
    instructions: List[Instruction],
    completion_register: str,
    result_register: str,
    finalizer_offset: int,
) -> Optional[tuple[List[Instruction], str]]:
    if len(instructions) < 4:
        return None
    token, save_token, save_result, jump = instructions[-4:]
    if (
        _smi_value(token) in {None, 0}
        or _star_target(save_token) != completion_register
        or save_result.mnemonic != "Mov"
        or len(save_result.args) < 2
        or save_result.args[1].strip() != result_register
        or jump.mnemonic not in {"Jump", "JumpConstant"}
        or parse_jump_target(jump) != finalizer_offset
    ):
        return None
    translated = translator.translate(save_result).strip()
    assignment = re.match(
        rf"^{re.escape(result_register)}\s*=\s*(.+)$", translated
    )
    if assignment is None:
        return None
    return instructions[:-4], assignment.group(1).strip()


def _strip_exception_scaffolding(
    instructions: List[Instruction],
    context_registers: set[str],
    pending_register: str,
) -> List[Instruction]:
    result: List[Instruction] = []
    index = 0
    while index < len(instructions):
        instruction = instructions[index]
        if (
            instruction.mnemonic == "LdaTheHole"
            and index + 1 < len(instructions)
            and _star_target(instructions[index + 1]) == pending_register
        ):
            index += 2
            continue
        if (
            instruction.mnemonic == "Mov"
            and len(instruction.args) >= 2
            and instruction.args[0].strip() == "<context>"
            and instruction.args[1].strip() in context_registers
        ):
            index += 1
            continue
        result.append(instruction)
        index += 1
    return result


def _render_try_catch_finally(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    translator: InstructionTranslator,
    instructions: List[Instruction],
) -> Optional[List[str]]:
    entries = bytecode.handler_entries
    for outer in entries:
        if outer.handler != outer.end:
            continue
        outer_start = _instruction_index_at_or_after(instructions, outer.start)
        outer_end = _instruction_index_at_or_after(instructions, outer.end)
        outer_handler = _instruction_index_at_or_after(instructions, outer.handler)
        if outer_start is None or outer_end is None or outer_handler is None:
            continue
        handler = _match_finally_handler(instructions, outer_handler)
        if handler is None:
            continue
        result_register, completion_register, pending_register, finalizer_start = (
            handler
        )
        dispatch = _match_finally_dispatch(
            instructions,
            finalizer_start,
            result_register,
            completion_register,
            pending_register,
        )
        if dispatch is None:
            continue
        dispatch_start, suffix_start = dispatch
        finalizer_offset = instructions[finalizer_start].offset

        inner = next(
            (
                entry
                for entry in entries
                if entry is not outer
                and outer.start <= entry.start
                and entry.end <= outer.end
                and entry.handler < outer.end
            ),
            None,
        )
        if inner is None:
            continue
        try_start = _instruction_index_at_or_after(instructions, inner.start)
        catch_start = _instruction_index_at_or_after(instructions, inner.handler)
        if try_start is None or catch_start is None:
            continue

        try_completion = _match_return_completion(
            translator,
            instructions[try_start:catch_start],
            completion_register,
            result_register,
            finalizer_offset,
        )
        catch_instructions = instructions[catch_start:outer_end]
        push_index = next(
            (
                index
                for index, instruction in enumerate(catch_instructions)
                if instruction.mnemonic == "PushContext"
            ),
            None,
        )
        pop_index = (
            next(
                (
                    index
                    for index, instruction in enumerate(
                        catch_instructions[push_index + 1 :],
                        start=push_index + 1,
                    )
                    if instruction.mnemonic == "PopContext"
                ),
                None,
            )
            if push_index is not None
            else None
        )
        if try_completion is None or push_index is None or pop_index is None:
            continue
        catch_completion = _match_return_completion(
            translator,
            catch_instructions[pop_index + 1 :],
            completion_register,
            result_register,
            finalizer_offset,
        )
        catch_context = next(
            (
                instruction
                for instruction in catch_instructions[:push_index]
                if instruction.mnemonic == "CreateCatchContext"
            ),
            None,
        )
        if catch_completion is None or catch_context is None:
            continue

        context_registers = {
            f"r{entry.data}" for entry in entries if entry.data >= 0
        }
        prefix = _strip_exception_scaffolding(
            instructions[:outer_start],
            context_registers,
            pending_register,
        )
        outer_prefix = _strip_exception_scaffolding(
            instructions[outer_start:try_start],
            context_registers,
            pending_register,
        )
        try_body, try_result = try_completion
        catch_body = catch_instructions[push_index + 1 : pop_index]
        _, catch_result = catch_completion
        finalizer_body = instructions[finalizer_start:dispatch_start]
        catch_name = _catch_binding_name(context, translator, catch_context)

        output = _render_fragment(translator, prefix)
        if not outer_prefix:
            output.append(f"{INDENT}try {{")
            output.extend(_indent_lines(_render_fragment(translator, try_body)))
            output.append(f"{INDENT * 2}return {try_result}")
            output.append(f"{INDENT}}} catch ({catch_name}) {{")
            output.extend(
                _indent_lines(_render_fragment(translator, catch_body))
            )
            output.append(f"{INDENT * 2}return {catch_result}")
        else:
            inner_lines = [f"{INDENT}try {{"]
            inner_lines.extend(
                _indent_lines(_render_fragment(translator, try_body))
            )
            inner_lines.append(f"{INDENT * 2}return {try_result}")
            inner_lines.append(f"{INDENT}}} catch ({catch_name}) {{")
            inner_lines.extend(
                _indent_lines(_render_fragment(translator, catch_body))
            )
            inner_lines.append(f"{INDENT * 2}return {catch_result}")
            inner_lines.append(f"{INDENT}}}")

            output.append(f"{INDENT}try {{")
            output.extend(
                _indent_lines(_render_fragment(translator, outer_prefix))
            )
            output.extend(_indent_lines(inner_lines))
        output.append(f"{INDENT}}} finally {{")
        output.extend(
            _indent_lines(_render_fragment(translator, finalizer_body))
        )
        output.append(f"{INDENT}}}")
        if suffix_start < len(instructions):
            output.extend(
                _render_fragment(translator, instructions[suffix_start:])
            )
        return output
    return None


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
                                r"\bACCU\b",
                                lambda _match: expression,
                                guard_condition,
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
    rendered = _render_try_catch_finally(
        context, bytecode, translator, instructions
    )
    if rendered is not None:
        return rendered
    for entry in bytecode.handler_entries:
        rendered = _render_single_try_catch(
            context, translator, instructions, entry
        )
        if rendered is not None:
            return rendered
    return None
