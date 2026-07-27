from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable, List, Optional, Sequence, TYPE_CHECKING

from .instruction import Instruction
from .objects import (
    V8Address,
    V8FixedArray,
    V8SharedFunctionInfo,
    V8Smi,
)
from .objects.bytecode import V8BytecodeArray
from .utils import parse_jump_target

if TYPE_CHECKING:
    from .context import DecompilerContext


INDEX_RE = re.compile(r"^\[(-?\d+)\]$")


@dataclass(frozen=True)
class DefaultParameterInitializer:
    parameter_index: int
    value: str
    target_register: str | None
    instruction_offsets: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class LexicalDeclaration:
    name: str
    initializer: str | None = None


@dataclass(frozen=True)
class NormalizedInstructions:
    instructions: List[Instruction]
    lexical_declarations: tuple[LexicalDeclaration, ...] = ()


LiteralLoader = Callable[[Instruction], Optional[str]]


def _parameter_index(instruction: Instruction) -> Optional[int]:
    if instruction.mnemonic != "Ldar" or not instruction.args:
        return None
    parameter = instruction.args[0].strip()
    if not parameter.startswith("a") or not parameter[1:].isdigit():
        return None
    return int(parameter[1:])


def _star_register(instruction: Instruction) -> Optional[str]:
    suffix = instruction.mnemonic.removeprefix("Star")
    if suffix.isdigit():
        return f"r{int(suffix)}"
    if instruction.mnemonic == "Star" and instruction.args:
        register = instruction.args[0].strip()
        return register if register.startswith("r") else None
    return None


def find_default_parameter_initializers(
    instructions: Sequence[Instruction], literal_loader: LiteralLoader
) -> List[DefaultParameterInitializer]:
    conditional_jumps = {
        "JumpIfNotUndefined",
        "JumpIfNotUndefinedConstant",
    }
    unconditional_jumps = {"Jump", "JumpConstant"}
    initializers: List[DefaultParameterInitializer] = []
    for index in range(len(instructions) - 5):
        window = instructions[index : index + 6]
        load, branch, default_load, join, alternate, store = window
        parameter_index = _parameter_index(load)
        if parameter_index is None:
            continue
        if branch.mnemonic not in conditional_jumps:
            continue
        if join.mnemonic not in unconditional_jumps:
            continue
        if _parameter_index(alternate) != parameter_index:
            continue
        if not store.mnemonic.startswith("Star"):
            continue
        if parse_jump_target(branch) != alternate.offset:
            continue
        if parse_jump_target(join) != store.offset:
            continue
        value = literal_loader(default_load)
        if value is None:
            continue
        initializers.append(
            DefaultParameterInitializer(
                parameter_index,
                value,
                _star_register(store),
                tuple(instruction.offset for instruction in window),
            )
        )
    return initializers


def _rewrite_default_parameter_initializers(
    instructions: Sequence[Instruction],
    initializers: Sequence[DefaultParameterInitializer],
) -> List[Instruction]:
    by_start = {
        initializer.instruction_offsets[0]: initializer
        for initializer in initializers
    }
    output: List[Instruction] = []
    index = 0
    while index < len(instructions):
        initializer = by_start.get(instructions[index].offset)
        window = instructions[index : index + 6]
        if (
            initializer is not None
            and len(window) == 6
            and tuple(instruction.offset for instruction in window)
            == initializer.instruction_offsets
        ):
            output.extend((window[4], window[5]))
            index += 6
            continue
        output.append(instructions[index])
        index += 1
    return output


def _index(token: str) -> Optional[int]:
    match = INDEX_RE.match(token.strip())
    return int(match.group(1)) if match else None


def _context_load_name(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instruction: Instruction,
) -> Optional[str]:
    current_loads = {
        "LdaCurrentContextSlot",
        "LdaImmutableCurrentContextSlot",
        "LdaCurrentScriptContextSlot",
    }
    depth_loads = {"LdaContextSlot", "LdaImmutableContextSlot"}
    if instruction.mnemonic in current_loads and instruction.args:
        slot = _index(instruction.args[0])
        depth = 0
    elif instruction.mnemonic in depth_loads and len(instruction.args) >= 3:
        slot = _index(instruction.args[1])
        depth = _index(instruction.args[2])
    else:
        return None
    if slot is None or depth is None:
        return None
    return context.context_slot_name(bytecode, slot, depth)


def _is_redundant_hole_check(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    load: Instruction,
    check: Instruction,
) -> bool:
    if check.mnemonic != "ThrowReferenceErrorIfHole" or not check.args:
        return False
    name = _context_load_name(context, bytecode, load)
    constant_index = _index(check.args[0])
    if name is None or constant_index is None:
        return False
    constants = context.constant_pool_entries(bytecode)
    if not 0 <= constant_index < len(constants):
        return False
    return constants[constant_index].display == json.dumps(name)


def _remove_redundant_hole_checks(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instructions: Sequence[Instruction],
) -> List[Instruction]:
    output: List[Instruction] = []
    for instruction in instructions:
        if output and _is_redundant_hole_check(
            context, bytecode, output[-1], instruction
        ):
            continue
        output.append(instruction)
    return output


def _is_function_declaration_array(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    declaration_array: object,
) -> bool:
    if not isinstance(declaration_array, V8FixedArray):
        return False
    if not declaration_array.elements or len(declaration_array.elements) % 2:
        return False
    for index in range(0, len(declaration_array.elements), 2):
        function_reference = declaration_array.elements[index]
        flags = declaration_array.elements[index + 1]
        if not isinstance(function_reference, V8Address) or not isinstance(
            flags, V8Smi
        ):
            return False
        function = context.get_object(function_reference.address)
        function_bytecode = (
            context.get_object(function.trusted_function_data.address)
            if isinstance(function, V8SharedFunctionInfo)
            and function.trusted_function_data is not None
            else None
        )
        if (
            not isinstance(function_bytecode, V8BytecodeArray)
            or function_bytecode is bytecode
            or context.is_nested_function(function_bytecode)
        ):
            return False
    return True


def _remove_redundant_function_declarations(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instructions: Sequence[Instruction],
) -> List[Instruction]:
    output: List[Instruction] = []
    index = 0
    while index < len(instructions):
        window = instructions[index : index + 4]
        if len(window) < 4:
            output.extend(window)
            break
        load, store, closure_move, call = window
        store_register = _star_register(store)
        closure_register = (
            closure_move.args[1].strip()
            if closure_move.mnemonic == "Mov"
            and len(closure_move.args) >= 2
            and closure_move.args[0].strip() == "<closure>"
            else None
        )
        runtime = call.args[0].strip() if call.args else ""
        register_range = call.args[1].strip() if len(call.args) >= 2 else ""
        declaration_array = context.constant_object_for_instruction(
            bytecode, load
        )
        if (
            load.mnemonic == "LdaConstant"
            and store_register is not None
            and closure_register is not None
            and call.mnemonic == "CallRuntime"
            and runtime == "[DeclareGlobals]"
            and register_range == f"{store_register}-{closure_register}"
            and _is_function_declaration_array(
                context, bytecode, declaration_array
            )
        ):
            index += 4
            continue
        output.append(instructions[index])
        index += 1
    return output


def _remove_parameter_body_context(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instructions: Sequence[Instruction],
    initializers: Sequence[DefaultParameterInitializer],
) -> tuple[List[Instruction], tuple[LexicalDeclaration, ...]]:
    if not initializers:
        return list(instructions), ()

    last_store_offset = max(
        initializer.instruction_offsets[-1] for initializer in initializers
    )
    try:
        store_index = next(
            index
            for index, instruction in enumerate(instructions)
            if instruction.offset == last_store_offset
        )
    except StopIteration:
        return list(instructions), ()

    context_index = store_index + 1
    if context_index + 3 >= len(instructions):
        return list(instructions), ()
    create = instructions[context_index]
    push = instructions[context_index + 1]
    if create.mnemonic != "CreateBlockContext" or push.mnemonic != "PushContext":
        return list(instructions), ()

    scope = context.scope_for_instruction(bytecode, create)
    if scope is None or scope.scope_type != "BLOCK_SCOPE":
        return list(instructions), ()
    expected_slots = set(scope.context_slot_names)
    if not expected_slots:
        return list(instructions), ()

    initialized_slots: set[int] = set()
    end_index = context_index + 2
    while end_index + 1 < len(instructions):
        hole = instructions[end_index]
        store = instructions[end_index + 1]
        if hole.mnemonic != "LdaTheHole":
            break
        if store.mnemonic != "StaCurrentContextSlot" or not store.args:
            break
        slot = _index(store.args[0])
        if slot is None or slot not in expected_slots:
            break
        initialized_slots.add(slot)
        end_index += 2
    if initialized_slots != expected_slots:
        return list(instructions), ()

    declaration_names = {
        slot: name
        for slot in sorted(expected_slots)
        if (name := context.scope_slot_name(scope, slot)) is not None
    }
    if len(declaration_names) != len(expected_slots):
        return list(instructions), ()

    parameter_by_register = {
        initializer.target_register: context.parameter_name(
            bytecode, initializer.parameter_index
        )
        for initializer in initializers
        if initializer.target_register is not None
    }
    declaration_initializers: dict[int, str] = {}
    body_start = end_index
    while body_start + 1 < len(instructions):
        load = instructions[body_start]
        store = instructions[body_start + 1]
        if load.mnemonic != "Ldar" or not load.args:
            break
        parameter = parameter_by_register.get(load.args[0].strip())
        if parameter is None:
            break
        if store.mnemonic != "StaCurrentContextSlot" or not store.args:
            break
        slot = _index(store.args[0])
        if slot is None or slot not in declaration_names:
            break
        declaration_initializers[slot] = parameter
        body_start += 2

    declarations = tuple(
        LexicalDeclaration(name, declaration_initializers.get(slot))
        for slot, name in sorted(declaration_names.items())
    )
    return (
        list(instructions[:context_index]) + list(instructions[body_start:]),
        declarations,
    )


def _simple_context_initializer(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instruction: Instruction,
) -> Optional[str]:
    if instruction.mnemonic == "Ldar" and instruction.args:
        parameter = instruction.args[0].strip()
        if parameter.startswith("a") and parameter[1:].isdigit():
            return context.parameter_name(bytecode, int(parameter[1:]))
        return None
    literals = {
        "CreateEmptyArrayLiteral": "[]",
        "CreateEmptyObjectLiteral": "{}",
    }
    if instruction.mnemonic in literals:
        return literals[instruction.mnemonic]
    return context.literal_load(bytecode, instruction)


def _remove_function_context_prologue(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instructions: Sequence[Instruction],
) -> tuple[List[Instruction], tuple[LexicalDeclaration, ...]]:
    try:
        create_index = next(
            index
            for index, instruction in enumerate(instructions)
            if instruction.mnemonic == "CreateFunctionContext"
        )
    except StopIteration:
        return list(instructions), ()
    if create_index + 1 >= len(instructions):
        return list(instructions), ()
    create = instructions[create_index]
    push = instructions[create_index + 1]
    if push.mnemonic != "PushContext":
        return list(instructions), ()

    scope = context.scope_for_instruction(bytecode, create)
    if scope is None or scope.scope_type != "FUNCTION_SCOPE":
        return list(instructions), ()
    expected_slots = set(scope.context_slot_names)
    if not expected_slots:
        return list(instructions), ()

    removed = {create_index, create_index + 1}
    hole_slots: set[int] = set()
    index = create_index + 2
    while index + 1 < len(instructions):
        hole, store = instructions[index : index + 2]
        if (
            hole.mnemonic != "LdaTheHole"
            or store.mnemonic != "StaCurrentContextSlot"
            or not store.args
        ):
            break
        slot = _index(store.args[0])
        if slot is None or slot not in expected_slots:
            break
        hole_slots.add(slot)
        removed.update((index, index + 1))
        index += 2

    direct_parameter_slots: set[int] = set()
    initializers: dict[int, str] = {}
    scan = index
    while scan < len(instructions):
        if (
            scan + 1 < len(instructions)
            and instructions[scan].mnemonic == "CreateClosure"
            and _star_register(instructions[scan + 1]) is not None
        ):
            scan += 2
            continue
        if scan + 1 >= len(instructions):
            break
        load, store = instructions[scan : scan + 2]
        if (
            store.mnemonic != "StaCurrentContextSlot"
            or not store.args
            or (slot := _index(store.args[0])) not in expected_slots
        ):
            break
        initializer = _simple_context_initializer(context, bytecode, load)
        if initializer is None:
            break
        if slot in hole_slots:
            initializers[slot] = initializer
        elif (
            load.mnemonic == "Ldar"
            and load.args
            and load.args[0].strip().startswith("a")
        ):
            direct_parameter_slots.add(slot)
        else:
            break
        removed.update((scan, scan + 1))
        scan += 2

    if expected_slots != hole_slots | direct_parameter_slots:
        return list(instructions), ()

    declarations = tuple(
        LexicalDeclaration(
            context.scope_slot_name(scope, slot)
            or f"context_{scope.address:012x}_{slot}",
            initializers.get(slot),
        )
        for slot in sorted(hole_slots)
    )
    return (
        [
            instruction
            for instruction_index, instruction in enumerate(instructions)
            if instruction_index not in removed
        ],
        declarations,
    )


def normalize_source_instructions(
    context: DecompilerContext,
    bytecode: V8BytecodeArray,
    instructions: Sequence[Instruction],
) -> NormalizedInstructions:
    initializers = context.parameter_initializers(bytecode)
    without_declarations = _remove_redundant_function_declarations(
        context, bytecode, instructions
    )
    rewritten = _rewrite_default_parameter_initializers(
        without_declarations, initializers
    )
    without_function_context, function_declarations = (
        _remove_function_context_prologue(context, bytecode, rewritten)
    )
    without_context, declarations = _remove_parameter_body_context(
        context, bytecode, without_function_context, initializers
    )
    normalized = _remove_redundant_hole_checks(
        context, bytecode, without_context
    )
    return NormalizedInstructions(
        normalized,
        function_declarations + declarations,
    )
