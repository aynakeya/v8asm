from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Iterable, List, Optional

from .context import DecompilerContext
from .instruction import Instruction
from .normalization import normalize_source_instructions
from .objects import V8HeapObject
from .objects.bytecode import V8BytecodeArray
from .parser import parse_objects
from .recovery.propagation import simplify_lines
from .recovery.file import postprocess_source_file
from .recovery.destructuring import recover_object_rest
from .recovery.literals import recover_object_literals
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


def _format_register_locals(bytecode: V8BytecodeArray, body: List[str]) -> List[str]:
    used = set(re.findall(r"\b(?:ACCU|r\d+)\b", "\n".join(body)))
    lines = ["  let ACCU;"] if "ACCU" in used else []
    registers = ", ".join(
        f"r{index}" for index in range(bytecode.register_count or 0)
        if f"r{index}" in used
    )
    if registers:
        lines.append(f"  let {registers};")
    return lines


def _format_captures(
    context: DecompilerContext, bytecode: V8BytecodeArray
) -> List[str]:
    captures = []
    for binding in context.captured_context_bindings(bytecode):
        owner = context.get_object(binding.defining_bytecode_address)
        owner_function = (
            context.get_function_for_bytecode(owner)
            if isinstance(owner, V8BytecodeArray)
            else None
        )
        owner_name = (
            context.get_function_name(owner_function)
            if owner_function is not None
            else f"bytecode_{binding.defining_bytecode_address:012x}"
        )
        location = (
            f" defined@{binding.definition_offset}"
            if binding.definition_offset is not None
            else ""
        )
        captures.append(
            f"{binding.name} <- {owner_name} slot={binding.slot}{location}"
        )
    return [f"  // Captures: {', '.join(captures)}"] if captures else []


def _render_linear(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    lines: List[str] = []
    for instruction in instructions:
        translated = translator.translate(instruction)
        offset = instruction.offset if instruction.offset >= 0 else -1
        lines.append(f"  [{offset:4d}] {translated}")
    return lines


def _render_structured(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    statements = decompile_to_statements(translator, instructions)
    lines: List[str] = []
    for statement in statements:
        lines.extend(statement.render(1))
    return lines


def _render_source_fragment(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    return simplify_lines(
        _render_structured(translator, instructions), recover_structures=True
    )


def _indent_lines(lines: List[str]) -> List[str]:
    return [f"{INDENT}{line}" if line else line for line in lines]


def _render_source(
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
    return _render_source_fragment(translator, instructions)


def decompile_bytecode(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    *,
    nested_functions: Optional[List[str]] = None,
    linear: bool = False,
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
        if linear:
            body_lines = _render_linear(translator, instructions)
        else:
            normalization = normalize_source_instructions(
                context, bytecode, instructions
            )
            instructions = normalization.instructions
            lexical_declarations = list(
                normalization.lexical_declarations
            )
            body_lines = _render_source(
                context, bytecode, translator, instructions
            )
    except RecursionError:
        notes.append(
            "  // WARNING: structurer recursion overflow, "
            "fallback to linear output"
        )
        body_lines = _render_linear(translator, original_instructions)
    except Exception as exc:
        notes.append(
            f"  // WARNING: decompile error ({type(exc).__name__}), "
            "fallback to linear output"
        )
        body_lines = _render_linear(translator, original_instructions)

    nested_functions = list(nested_functions or ())
    nested_owners = {
        context.get_function_name(function): function
        for child in context.child_functions(bytecode)
        if (function := context.get_function_for_bytecode(child)) is not None
    }
    if not linear and not notes:
        kinds = {name: function.func_kind for name, function in nested_owners.items()}
        body_lines = recover_object_rest(body_lines)
        body_lines, nested_functions = recover_object_literals(body_lines, nested_functions, kinds)

    body: List[str] = [metadata]
    body.extend(_format_captures(context, bytecode))
    if as_script:
        lexical_declarations = context.script_context_declarations(bytecode) + lexical_declarations
    body.extend(_format_register_locals(bytecode, body_lines))
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
    if linear or notes:
        body.extend(_format_constant_pool(context, bytecode))
    for nested in nested_functions or ():
        declaration = re.match(r"function ([\w$]+)\((.*)\) \{", nested)
        function = nested_owners.get(declaration[1]) if declaration else None
        if not linear and function and function.func_kind in {
            "ConciseMethod", "GetterFunction", "SetterFunction"
        }:
            # An unmerged method is still not a constructor. Keep its callable
            # identity and original name instead of emitting a normal function.
            name = function.name_value
            if name is None:
                name = "" if function.name is None else declaration[1]
            key = json.dumps(name)
            nested = "\n".join([
                f"const {declaration[1]} = {{",
                f"  [{key}]({declaration[2]}) {{",
                *_indent_lines(nested.splitlines()[1:-1]),
                "  }",
                f"}}[{key}];",
            ])
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
    linear: bool,
    ancestors: frozenset[int] = frozenset(),
) -> str:
    if bytecode.address in ancestors:
        return decompile_bytecode(context, bytecode, linear=linear)
    next_ancestors = ancestors | {bytecode.address}
    nested = [
        _decompile_function_tree(context, child, linear, next_ancestors)
        for child in context.child_functions(bytecode)
    ]
    return decompile_bytecode(
        context,
        bytecode,
        nested_functions=nested,
        linear=linear,
        as_script=not linear and context.is_script(bytecode),
    )


def _read_disassembly_objects(path: Path):
    data = path.read_bytes()
    if data.lstrip().startswith(b"{"):
        document = json.loads(data.decode("utf-8"))
        return load_structured_objects(document)
    return parse_objects(data.decode("utf-8", errors="replace").splitlines())


def decompile_objects(
    objects: Iterable[V8HeapObject], *, linear: bool = False, runtime: bool = False
) -> str:
    object_list = list(objects)
    context = DecompilerContext(object_list)

    outputs: List[str] = []
    for obj in object_list:
        if isinstance(obj, V8BytecodeArray) and not context.is_nested_function(obj):
            outputs.append(_decompile_function_tree(context, obj, linear))
    output = "\n\n".join(outputs)
    if not linear:
        output = postprocess_source_file(output)
    if runtime:
        output = runtime_prelude().rstrip() + "\n\n" + output
    return output


def decompile_file(
    path: Path, *, linear: bool = False, runtime: bool = False
) -> str:
    return decompile_objects(
        _read_disassembly_objects(path), linear=linear, runtime=runtime
    )
