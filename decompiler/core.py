from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable, List, Optional

from .context import DecompilerContext
from .instruction import Instruction
from .normalization import normalize_level4_instructions
from .objects import V8HeapObject
from .objects.bytecode import V8BytecodeArray
from .parser import parse_objects
from .postprocess import simplify_lines
from .postprocess_file import postprocess_level4_file
from .runtime import runtime_prelude
from .structured import load_structured_objects
from .structurer import decompile_to_statements
from .translator import InstructionTranslator
from .try_catch import render_simple_try_catch


IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
INDENT = "  "


def _format_params(context: DecompilerContext, bytecode: V8BytecodeArray) -> str:
    count = bytecode.parameter_count or 0
    user_params = max(0, count - 1)
    return ", ".join(
        context.parameter_declaration(bytecode, index)
        for index in range(user_params)
    )


def _format_constant_pool(
    context: DecompilerContext, bytecode: V8BytecodeArray
) -> List[str]:
    entries = context.constant_pool_entries(bytecode)
    if not entries:
        return []
    lines = ["  // Constant pool:"]
    for entry in entries:
        lines.append(f"  //   [{entry.index}] = {entry.display}")
    return lines


def _sanitize_identifier(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return fallback
    if not IDENT_RE.match(cleaned):
        if cleaned[0].isdigit():
            cleaned = f"fn_{cleaned}"
        if not IDENT_RE.match(cleaned):
            return fallback
    return cleaned


def _format_register_locals(bytecode: V8BytecodeArray) -> List[str]:
    lines = ["  let ACCU = undefined;"]
    register_count = bytecode.register_count or 0
    if register_count <= 0:
        return lines
    registers = ", ".join(f"r{index}" for index in range(register_count))
    lines.append(f"  let {registers};")
    return lines


def render_level1(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    lines: List[str] = []
    for instruction in instructions:
        translated = translator.translate(instruction)
        offset = instruction.offset if instruction.offset >= 0 else -1
        lines.append(f"  [{offset:4d}] {translated}")
    return lines


def render_level2(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    statements = decompile_to_statements(translator, instructions)
    lines: List[str] = []
    for statement in statements:
        lines.extend(statement.render(1))
    return lines


def render_level3(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    return simplify_lines(
        render_level2(translator, instructions), recover_structures=False
    )


def _render_level4_fragment(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    return simplify_lines(
        render_level2(translator, instructions), recover_structures=True
    )


def _indent_lines(lines: List[str]) -> List[str]:
    return [f"{INDENT}{line}" if line else line for line in lines]


def render_level4(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    translator: InstructionTranslator,
    instructions: List[Instruction],
) -> List[str]:
    recovered = render_simple_try_catch(
        context, bytecode, translator, instructions
    )
    if recovered is not None:
        return recovered
    return _render_level4_fragment(translator, instructions)


def decompile_bytecode(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    level: int,
    nested_functions: Optional[List[str]] = None,
    *,
    as_script: bool = False,
) -> str:
    owner = context.get_function_for_bytecode(bytecode)
    if owner:
        raw_name = context.get_function_name(owner)
        fallback = f"fn_{bytecode.address:012x}"
        function_name = _sanitize_identifier(raw_name, fallback)
    else:
        function_name = f"bytecode_{bytecode.address:012x}"

    header = f"function {function_name}({_format_params(context, bytecode)}) {{"
    metadata = (
        f"  // Bytecode 0x{bytecode.address:012x} "
        f"params={bytecode.parameter_count} "
        f"regs={bytecode.register_count} frame={bytecode.frame_size}"
    )

    translator = InstructionTranslator(context, bytecode)
    original_instructions = [
        Instruction.from_codeline(raw) for raw in bytecode.instructions
    ]
    instructions = original_instructions

    notes: List[str] = []
    lexical_declarations = []
    try:
        if level == 1:
            body_lines = render_level1(translator, instructions)
        elif level == 2:
            body_lines = render_level2(translator, instructions)
        elif level == 3:
            body_lines = render_level3(translator, instructions)
        else:
            normalization = normalize_level4_instructions(
                context, bytecode, instructions
            )
            instructions = normalization.instructions
            lexical_declarations = list(
                normalization.lexical_declarations
            )
            body_lines = render_level4(
                context, bytecode, translator, instructions
            )
    except RecursionError:
        notes.append(
            "  // WARNING: structurer recursion overflow, "
            "fallback to level-1 linear output"
        )
        body_lines = render_level1(translator, original_instructions)
    except Exception as exc:
        notes.append(
            f"  // WARNING: decompile error ({type(exc).__name__}), "
            "fallback to level-1 linear output"
        )
        body_lines = render_level1(translator, original_instructions)

    body: List[str] = [metadata]
    if as_script:
        context_names = context.script_context_names(bytecode)
        if context_names:
            body.append(f"  let {', '.join(context_names)};")
    body.extend(_format_register_locals(bytecode))
    if lexical_declarations:
        declarations = ", ".join(
            (
                f"{declaration.name} = {declaration.initializer}"
                if declaration.initializer is not None
                else declaration.name
            )
            for declaration in lexical_declarations
        )
        body.append(f"  let {declarations};")
    body.extend(notes)
    body.extend(_format_constant_pool(context, bytecode))
    for nested in nested_functions or ():
        body.append("")
        body.extend(_indent_lines(nested.splitlines()))
    body.extend(body_lines)
    if as_script:
        while body and not body[-1]:
            body.pop()
        if body and body[-1].lstrip().startswith("return "):
            body.pop()
        return "\n".join(
            line[len(INDENT) :] if line.startswith(INDENT) else line
            for line in body
        )

    lines: List[str] = [header, *body]
    lines.append("}")
    return "\n".join(lines)


def _decompile_function_tree(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    level: int,
    ancestors: frozenset[int] = frozenset(),
) -> str:
    if bytecode.address in ancestors:
        return decompile_bytecode(context, bytecode, level)
    next_ancestors = ancestors | {bytecode.address}
    nested = [
        _decompile_function_tree(context, child, level, next_ancestors)
        for child in context.child_functions(bytecode)
    ]
    return decompile_bytecode(
        context,
        bytecode,
        level,
        nested,
        as_script=level >= 4 and context.is_script(bytecode),
    )


def _read_disassembly_objects(path: Path):
    data = path.read_bytes()
    if data.lstrip().startswith(b"{"):
        document = json.loads(data.decode("utf-8"))
        return load_structured_objects(document)
    return parse_objects(data.decode("utf-8", errors="replace").splitlines())


def decompile_objects(
    objects: Iterable[V8HeapObject], level: int, runtime: bool = False
) -> str:
    object_list = list(objects)
    context = DecompilerContext(object_list)

    outputs: List[str] = []
    if runtime:
        outputs.append(runtime_prelude().rstrip())
    for obj in object_list:
        if isinstance(obj, V8BytecodeArray) and not context.is_nested_function(obj):
            outputs.append(_decompile_function_tree(context, obj, level))
    output = "\n\n".join(outputs)
    if level >= 4:
        output = postprocess_level4_file(output)
    return output


def decompile_file(path: Path, level: int, runtime: bool = False) -> str:
    return decompile_objects(_read_disassembly_objects(path), level, runtime)
