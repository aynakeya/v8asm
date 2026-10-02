from __future__ import annotations

from typing import Any

from .objects import (
    V8Address,
    V8ArrayBoilerplateDescription,
    V8BytecodeArray,
    V8FixedArray,
    V8HeapObject,
    V8ObjectBoilerplateDescription,
    V8ClassBoilerplate,
    V8SharedFunctionInfo,
    V8ScopeInfo,
    V8Smi,
    V8String,
    V8TrustedFixedArray,
    parse_object,
)
from .objects.bytecode import CodeLine, HandlerEntry


SCHEMA_NAME = "v8asm.disassembly"
SCHEMA_VERSION = 1


class StructuredDisassemblyError(ValueError):
    pass


def _address(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise StructuredDisassemblyError(f"{field} must be a hexadecimal address")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise StructuredDisassemblyError(
            f"{field} must be a hexadecimal address"
        ) from exc


def _integer(record: dict[str, Any], field: str, default: int = 0) -> int:
    value = record.get(field, default)
    if not isinstance(value, int):
        raise StructuredDisassemblyError(f"{field} must be an integer")
    return value


def _value(record: Any) -> Any:
    if not isinstance(record, dict):
        raise StructuredDisassemblyError("serialized value must be an object")
    kind = record.get("kind")
    if kind == "smi":
        return V8Smi(_integer(record, "value"))
    if kind == "reference":
        description = record.get("description", "")
        if not isinstance(description, str):
            raise StructuredDisassemblyError("reference description must be a string")
        address = record.get("address")
        if address is not None:
            return V8Address(_address(address, "reference.address"), description)
        return description or f"<{record.get('reference_kind', 'unresolved')}>"
    if kind == "unresolved":
        return "<unresolved>"
    raise StructuredDisassemblyError(f"unsupported serialized value kind: {kind}")


def _populate_bytecode(
    obj: V8BytecodeArray,
    record: dict[str, Any],
    records: dict[str, Any],
) -> None:
    obj.parameter_count = _integer(record, "parameter_count")
    obj.register_count = _integer(record, "register_count")
    obj.frame_size = _integer(record, "frame_size")
    obj.file_offset = _integer(record, "file_offset")
    obj.handler_table_size = _integer(record, "handler_table_size")
    obj.source_position_table_size = _integer(
        record, "source_position_table_size"
    )

    pool_address = record.get("constant_pool_address")
    if pool_address is not None:
        obj.constant_pool_address = _address(
            pool_address, "BytecodeArray.constant_pool_address"
        )
        pool = records.get(pool_address)
        if not isinstance(pool, dict):
            raise StructuredDisassemblyError(
                "BytecodeArray constant pool does not exist in objects"
            )
        obj.constant_pool_size = _integer(pool, "length")

    instructions = record.get("instructions")
    if not isinstance(instructions, list):
        raise StructuredDisassemblyError("BytecodeArray.instructions must be a list")
    for instruction in instructions:
        if not isinstance(instruction, dict):
            raise StructuredDisassemblyError("instruction must be an object")
        raw_bytes = instruction.get("raw_bytes")
        arguments = instruction.get("arguments")
        if not isinstance(raw_bytes, list) or not all(
            isinstance(value, int) and 0 <= value <= 255 for value in raw_bytes
        ):
            raise StructuredDisassemblyError("instruction.raw_bytes must contain bytes")
        if not isinstance(arguments, list) or not all(
            isinstance(value, str) for value in arguments
        ):
            raise StructuredDisassemblyError("instruction.arguments must contain strings")
        mnemonic = instruction.get("mnemonic")
        if not isinstance(mnemonic, str):
            raise StructuredDisassemblyError("instruction.mnemonic must be a string")
        jump_target = instruction.get("jump_target")
        if jump_target is not None and not isinstance(jump_target, int):
            raise StructuredDisassemblyError("instruction.jump_target must be an integer")
        offset = _integer(instruction, "offset")
        obj.instructions.append(
            CodeLine(
                offset,
                " ".join(f"{value:02x}" for value in raw_bytes),
                mnemonic,
                "",
                f"<structured instruction @{offset}>",
                arguments=arguments,
                jump_target=jump_target,
            )
        )

    handlers = record.get("handler_entries", [])
    if not isinstance(handlers, list):
        raise StructuredDisassemblyError("BytecodeArray.handler_entries must be a list")
    for handler in handlers:
        if not isinstance(handler, dict):
            raise StructuredDisassemblyError("handler entry must be an object")
        obj.handler_entries.append(
            HandlerEntry(
                _integer(handler, "start"),
                _integer(handler, "end"),
                _integer(handler, "handler"),
                _integer(handler, "prediction"),
                _integer(handler, "data"),
            )
        )


def _populate_object(
    obj: V8HeapObject,
    record: dict[str, Any],
    records: dict[str, Any],
) -> None:
    if isinstance(obj, V8String):
        value = record.get("value", "")
        if not isinstance(value, str):
            raise StructuredDisassemblyError("String.value must be a string")
        obj.value = value
    elif isinstance(obj, V8BytecodeArray):
        _populate_bytecode(obj, record, records)
    elif isinstance(obj, V8SharedFunctionInfo):
        name = record.get("name")
        if name is not None:
            decoded = _value(name)
            if isinstance(decoded, V8Address):
                obj.name = decoded
        name_value = record.get("name_value")
        if name_value is not None and not isinstance(name_value, str):
            raise StructuredDisassemblyError(
                "SharedFunctionInfo.name_value must be a string or null"
            )
        obj.name_value = name_value
        kind = record.get("function_kind")
        if kind is not None and not isinstance(kind, str):
            raise StructuredDisassemblyError("SharedFunctionInfo.function_kind must be a string")
        obj.func_kind = kind
        obj.formal_parameter_count = _integer(record, "formal_parameter_count")
        bytecode_address = record.get("bytecode_address")
        if bytecode_address is not None:
            obj.trusted_function_data = V8Address(
                _address(bytecode_address, "SharedFunctionInfo.bytecode_address"),
                "<BytecodeArray>",
            )
        scope_info_address = record.get("scope_info_address")
        if scope_info_address is not None:
            obj.scope_info = V8Address(
                _address(scope_info_address, "SharedFunctionInfo.scope_info_address"),
                "<ScopeInfo>",
            )
    elif isinstance(obj, V8FixedArray):
        elements = record.get("elements", [])
        if not isinstance(elements, list):
            raise StructuredDisassemblyError("FixedArray.elements must be a list")
        obj.length = _integer(record, "length")
        obj.elements = [_value(element) for element in elements]
    elif isinstance(obj, V8ArrayBoilerplateDescription):
        elements_kind = record.get("elements_kind")
        obj.elements_kind = (
            str(elements_kind) if elements_kind is not None else None
        )
        constant_elements = record.get("constant_elements")
        if constant_elements is not None:
            decoded = _value(constant_elements)
            if isinstance(decoded, V8Address):
                obj.constant_elements = decoded
    elif isinstance(obj, V8ObjectBoilerplateDescription):
        obj.capacity = _integer(record, "capacity")
        obj.backing_store_size = _integer(record, "backing_store_size")
        obj.flags = _integer(record, "flags")
        entries = record.get("entries", [])
        if not isinstance(entries, list):
            raise StructuredDisassemblyError(
                "ObjectBoilerplateDescription.entries must be a list"
            )
        obj.entries = [_value(entry) for entry in entries]
    elif isinstance(obj, V8ClassBoilerplate):
        obj.arguments_count = _integer(record, "arguments_count")
        indices = record.get("argument_indices", {})
        members = record.get("members", [])
        if not isinstance(indices, dict) or not all(isinstance(value, int) for value in indices.values()):
            raise StructuredDisassemblyError("ClassBoilerplate.argument_indices must contain integers")
        if not isinstance(members, list):
            raise StructuredDisassemblyError("ClassBoilerplate.members must be a list")
        obj.argument_indices = indices
        obj.supported = record.get("supported", False) is True
        for member in members:
            if (not isinstance(member, dict) or member.get("kind") not in {"method", "getter", "setter"}
                or not isinstance(member.get("static"), bool)):
                raise StructuredDisassemblyError("invalid class member")
            index = _integer(member, "argument_index")
            if not 0 <= index < obj.arguments_count:
                raise StructuredDisassemblyError("class member argument index is out of range")
            obj.members.append({**member, "key": _value(member["key"])})
    elif isinstance(obj, V8ScopeInfo):
        scope_type = record.get("scope_type")
        if scope_type is not None and not isinstance(scope_type, str):
            raise StructuredDisassemblyError("ScopeInfo.scope_type must be a string")
        obj.scope_type = scope_type
        obj.context_local_count = _integer(record, "context_local_count")
        obj.context_header_length = _integer(record, "context_header_length")
        outer_scope = record.get("outer_scope_info")
        if outer_scope is not None:
            decoded_outer = _value(outer_scope)
            if isinstance(decoded_outer, V8Address):
                obj.outer_scope_info = decoded_outer
        locals_ = record.get("context_locals", [])
        if not isinstance(locals_, list):
            raise StructuredDisassemblyError("ScopeInfo.context_locals must be a list")
        for local in locals_:
            if not isinstance(local, dict):
                raise StructuredDisassemblyError("ScopeInfo context local must be an object")
            name = local.get("name")
            decoded = _value(name) if name is not None else "<unknown>"
            obj.context_slots.append(decoded)
            obj.context_slot_names[_integer(local, "context_slot")] = decoded
            initialization = local.get("needs_initialization")
            if initialization is not None:
                if not isinstance(initialization, bool):
                    raise StructuredDisassemblyError("ScopeInfo local needs_initialization must be a boolean")
                obj.context_slot_initialization[_integer(local, "context_slot")] = initialization


def load_structured_objects(document: Any) -> list[V8HeapObject]:
    if not isinstance(document, dict):
        raise StructuredDisassemblyError("disassembly document must be an object")
    if document.get("schema") != SCHEMA_NAME:
        raise StructuredDisassemblyError("unsupported disassembly schema")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise StructuredDisassemblyError(
            f"unsupported disassembly schema version: {document.get('schema_version')}"
        )

    records = document.get("objects")
    order = document.get("object_order")
    if not isinstance(records, dict) or not isinstance(order, list):
        raise StructuredDisassemblyError("objects and object_order are required")
    if len(order) != len(set(order)) or set(order) != set(records):
        raise StructuredDisassemblyError(
            "object_order must contain every object address exactly once"
        )

    metadata = document.get("metadata", {})
    if not isinstance(metadata, dict):
        raise StructuredDisassemblyError("metadata must be an object")
    literal_flags = metadata.get("literal_flags", {})
    if not isinstance(literal_flags, dict) or not all(
        isinstance(key, str) and isinstance(value, int) and value >= 0
        for key, value in literal_flags.items()
    ):
        raise StructuredDisassemblyError("literal_flags must contain non-negative integers")
    if literal_flags and not {
        "define_keyed_set_function_name",
        "define_keyed_dont_enum",
        "object_literal_null_prototype",
    } <= literal_flags.keys():
        raise StructuredDisassemblyError("literal_flags is missing required masks")

    objects: list[V8HeapObject] = []
    for key in order:
        if not isinstance(key, str):
            raise StructuredDisassemblyError("object_order entries must be strings")
        record = records[key]
        if not isinstance(record, dict):
            raise StructuredDisassemblyError(f"object {key} must be an object")
        if record.get("address") != key:
            raise StructuredDisassemblyError(f"object {key} has a mismatched address")
        object_type = record.get("type")
        if not isinstance(object_type, str):
            raise StructuredDisassemblyError(f"object {key} has no type")
        obj = parse_object(_address(key, "object address"), object_type, [])
        _populate_object(obj, record, records)
        if isinstance(obj, (V8BytecodeArray, V8ObjectBoilerplateDescription)):
            obj.literal_flags = literal_flags
        objects.append(obj)
    return objects
