from __future__ import annotations

from typing import Any

from .disassembler import (
    _jump_target,
    _object_address,
    _operand_arguments,
    _profile_string,
    _root_address,
    _target_object,
)
from .model import BytecodeArray, ParsedDisassembly
from .serializer import Reference, SerializedObject
from .structured_objects import StructuredObjectEncoder


SCHEMA_NAME = "v8asm.disassembly"
SCHEMA_VERSION = 1


def _address(value: int) -> str:
    return f"0x{value:012x}"


def _constant_pool_address(object_index: int) -> int:
    return 0xD00000000000 + object_index * 0x100


def _reference_address(reference: Reference) -> int | None:
    if reference.object_index is not None:
        return _object_address(reference.object_index)
    if reference.kind == "root" and reference.values:
        return _root_address(reference.values[0])
    if reference.kind == "read_only" and len(reference.values) == 2:
        return _root_address(0x20000 + reference.values[1])
    return None


def _reference_source(reference: Reference) -> dict[str, Any]:
    if reference.object_index is not None:
        return {
            "kind": "serialized_object",
            "id": f"serialized_object:{reference.object_index}",
            "object_index": reference.object_index,
        }

    source_kinds = {
        "root": "root",
        "read_only": "read_only_heap",
        "startup_cache": "startup_object_cache",
        "read_only_cache": "read_only_object_cache",
        "shared_cache": "shared_heap_object_cache",
        "attached": "attached_reference",
        "external": "external_reference",
        "raw_external": "raw_external_reference",
    }
    kind = source_kinds.get(reference.kind, reference.kind)
    source: dict[str, Any] = {"kind": kind}
    if reference.kind == "read_only" and len(reference.values) == 2:
        source.update(page=reference.values[0], offset=reference.values[1])
    elif reference.values:
        source["index"] = reference.values[0]
        if len(reference.values) > 1:
            source["values"] = list(reference.values)
    suffix = ":".join(str(value) for value in reference.values)
    source["id"] = f"{kind}:{suffix}" if suffix else kind
    return source


def _root_literal(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = "".join(character for character in name.lower() if character.isalpha())
    for literal in ("undefined", "null", "true", "false"):
        if normalized in {literal, f"{literal}value"}:
            return literal
    return None


class StructuredGraphBuilder:
    def __init__(self, parsed: ParsedDisassembly) -> None:
        self.parsed = parsed
        self.objects = list(parsed.objects)
        self.arrays = {array.object_index: array for array in parsed.arrays}
        self.semantic_types: dict[int, str] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self._index_semantic_types()
        self.object_encoder = StructuredObjectEncoder(
            parsed,
            self.arrays,
            self.semantic_types,
            self._reference,
        )

    def _index_semantic_types(self) -> None:
        literal_types = {
            "CreateArrayLiteral": "ArrayBoilerplateDescription",
            "CreateObjectLiteral": "ObjectBoilerplateDescription",
        }
        for array in self.parsed.arrays:
            registers = {}
            accumulator = None
            runtime_names = self.parsed.profile.runtime_names_for(
                self.parsed.header.flags_hash, self.parsed.runtime_variant
            )
            define_class_id = runtime_names.index("DefineClass")
            boundaries = {_jump_target(item, array) for item in array.instructions}
            for instruction in array.instructions:
                if instruction.offset in boundaries:
                    registers.clear()
                    accumulator = None
                name = instruction.name.split(".", 1)[0]
                operands = instruction.operands
                if name == "CallRuntime" and operands[0][1] == define_class_id:
                    value = registers.get(operands[1][1])
                    if isinstance(value, Reference) and value.object_index is not None:
                        self.semantic_types[value.object_index] = "ClassBoilerplate"
                if name == "LdaConstant":
                    accumulator = array.constant_pool[operands[0][1]]
                elif name.startswith("Star"):
                    register = (operands[0][1] if name == "Star" else
                                self.parsed.profile.register_file_start - int(name[4:]))
                    registers[register] = accumulator
                elif name == "Mov":
                    registers[operands[1][1]] = registers.get(operands[0][1])
                else:
                    accumulator = None
                    for kind, register in operands:
                        if kind in {"RegOut", "RegInOut"}:
                            registers.pop(register, None)
                    if instruction.jump_mode or name.startswith("SwitchOn"):
                        registers.clear()
                object_type = literal_types.get(instruction.name.split(".", 1)[0])
                if object_type is None or not instruction.operands:
                    continue
                constant_index = instruction.operands[0][1]
                if not 0 <= constant_index < len(array.constant_pool):
                    continue
                value = array.constant_pool[constant_index]
                if isinstance(value, Reference) and value.object_index is not None:
                    self.semantic_types[value.object_index] = object_type

    def build(self) -> dict[str, Any]:
        for obj in self.objects:
            self._add_serialized_object(obj)
        for array in self.parsed.arrays:
            self._add_bytecode_array(array)
        for function in self.parsed.functions.values():
            self._add_function(function.sfi_object_index)

        profile = self.parsed.profile
        header = self.parsed.header
        runtime_variant = self.parsed.runtime_variant or (
            profile.runtime_variant_by_flags_hash.get(header.flags_hash)
            or profile.runtime_default_variant
        )
        snapshot = self.parsed.snapshot
        metadata: dict[str, Any] = {
            "v8_version": profile.version,
            "root_layout_version": profile.root_layout_version or profile.version,
            "runtime_variant": runtime_variant,
            "literal_flags": profile.literal_flags,
            "tagged_size": self.parsed.tagged_size,
            "address_kind": "synthetic_serializer_object",
            "serialized_object_count": len(self.parsed.objects),
            "bytecode_array_count": len(self.parsed.arrays),
            "header": {
                "magic": header.magic,
                "version_hash": header.version_hash,
                "source_hash": header.source_hash,
                "flags_hash": header.flags_hash,
                "read_only_snapshot_checksum": header.ro_snapshot_checksum,
                "payload_length": header.payload_length,
                "checksum": header.checksum,
                "header_size": header.header_size,
                "raw_payload": header.raw_payload,
            },
            "snapshot": None,
        }
        if snapshot is not None:
            metadata["snapshot"] = {
                "v8_version": snapshot.version,
                "magic": snapshot.magic,
                "checksum": snapshot.checksum,
                "static_roots": snapshot.static_roots,
            }
        return {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "metadata": metadata,
            "object_order": self.order,
            "objects": self.records,
        }

    def _put(self, address: int, record: dict[str, Any]) -> dict[str, Any]:
        key = _address(address)
        if key not in self.records:
            self.order.append(key)
        record["address"] = key
        self.records[key] = record
        return record

    def _add_serialized_object(self, obj: SerializedObject) -> None:
        self._put(_object_address(obj.index), self.object_encoder.encode(obj))

    def _add_bytecode_array(self, array: BytecodeArray) -> None:
        address = _object_address(array.object_index)
        record = self.records[_address(address)]
        runtime_names = self.parsed.profile.runtime_names_for(
            self.parsed.header.flags_hash, self.parsed.runtime_variant
        )
        instructions: list[dict[str, Any]] = []
        for instruction in array.instructions:
            target = _jump_target(instruction, array)
            instructions.append(
                {
                    "offset": instruction.offset,
                    "file_offset": array.file_offset + instruction.offset,
                    "raw_bytes": list(instruction.raw),
                    "mnemonic": instruction.name,
                    "scale": instruction.scale,
                    "operands": [
                        {"kind": kind, "value": value}
                        for kind, value in instruction.operands
                    ],
                    "arguments": list(
                        _operand_arguments(
                            instruction, self.parsed.profile, runtime_names
                        )
                    ),
                    "jump_target": target,
                    "jump_target_file_offset": (
                        array.file_offset + target if target is not None else None
                    ),
                }
            )

        pool_address = _constant_pool_address(array.object_index)
        pool_values = [self._value(value) for value in array.constant_pool]
        self._put(
            pool_address,
            {
                "type": "TrustedFixedArray",
                "type_evidence": {"kind": "bytecode_constant_pool"},
                "provenance": {
                    "kind": "derived_constant_pool",
                    "id": f"constant_pool:{array.object_index}",
                    "owner_object_index": array.object_index,
                },
                "owner_address": _address(address),
                "length": len(pool_values),
                "elements": pool_values,
            },
        )
        record.update(
            type="BytecodeArray",
            file_offset=array.file_offset,
            object_file_offset=array.object_offset,
            bytecode_offset=array.bytecode_offset,
            bytecode_bytes=list(array.data),
            parameter_count=array.parameter_count,
            register_count=array.register_count,
            frame_size=array.frame_size,
            constant_pool_address=_address(pool_address),
            handler_table_size=array.handler_table_size,
            handler_entries=[
                {
                    "start": start,
                    "end": end,
                    "handler": handler,
                    "prediction": prediction,
                    "data": data,
                }
                for start, end, handler, prediction, data in array.handler_entries
            ],
            source_position_table_size=array.source_position_table_size,
            instructions=instructions,
        )

    def _add_function(self, object_index: int) -> None:
        function = self.parsed.functions[object_index]
        address = _object_address(object_index)
        record = self.records[_address(address)]
        name = self._reference(function.name_reference)
        record.update(
            type="SharedFunctionInfo",
            name=name,
            name_value=function.name_value,
            formal_parameter_count=self.arrays[
                function.array_object_index
            ].parameter_count,
            bytecode_address=_address(_object_address(function.array_object_index)),
            scope_info_address=(
                _address(_object_address(function.scope_info_object_index))
                if function.scope_info_object_index is not None
                else None
            ),
        )
        scope = self.records.get(record["scope_info_address"], {})
        if "function_kind" in scope:
            record["function_kind"] = scope["function_kind"]

    def _value(self, value: int | Reference) -> dict[str, Any]:
        if isinstance(value, int):
            return {"kind": "smi", "value": value}
        reference = self._reference(value)
        if reference is None:
            return {"kind": "unresolved"}
        return reference

    def _reference(self, reference: Reference | None) -> dict[str, Any] | None:
        if reference is None:
            return None
        result: dict[str, Any] = {
            "kind": "reference",
            "reference_kind": reference.kind,
            "values": list(reference.values),
            "source": _reference_source(reference),
            "resolution": "unresolved",
        }
        if reference.object_index is not None:
            result["object_index"] = reference.object_index

        address = _reference_address(reference)
        if address is not None:
            result["address"] = _address(address)

        target = _target_object(reference, self.objects)
        if target is not None:
            target_type, type_evidence = self.object_encoder.object_type_info(target)
            result.update(
                target_type=target_type,
                type_evidence=type_evidence,
                resolution="serialized_object",
            )
            result["description"] = f"<{result['target_type']}>"
            return result

        profile = self.parsed.profile
        value = _profile_string(reference, profile, self.parsed.snapshot)
        root_name = None
        if reference.kind == "root" and reference.values:
            index = reference.values[0]
            if index < len(profile.root_names):
                root_name = profile.root_names[index]
        literal = _root_literal(root_name)
        if value is not None:
            evidence = (
                "read_only_snapshot"
                if reference.kind == "read_only"
                and self.parsed.snapshot is not None
                and len(reference.values) == 2
                and self.parsed.snapshot.string_at(*reference.values) is not None
                else "profile_metadata"
            )
            result.update(
                target_type="String",
                type_evidence={"kind": evidence},
                resolution=evidence,
                description=f"<String[{len(value)}]>",
            )
            if address is not None:
                self._put(
                    address,
                    {
                        "type": "String",
                        "type_evidence": {"kind": evidence},
                        "value": value,
                        "length": len(value),
                        "external": True,
                        "provenance": result["source"],
                        "reference_kind": reference.kind,
                    },
                )
        elif literal is not None:
            result.update(
                target_type="Primitive",
                type_evidence={"kind": "profile_root_name"},
                resolution="profile_metadata",
                literal=literal,
            )
            result["description"] = f"<{literal}>"
            if address is not None:
                self._put(
                    address,
                    {
                        "type": "Primitive",
                        "type_evidence": {"kind": "profile_root_name"},
                        "value": literal,
                        "external": True,
                        "provenance": result["source"],
                        "reference_kind": reference.kind,
                    },
                )
        elif (
            root_name is not None
            and root_name.replace("_", "").lower() in {
                "emptyobjectboilerplatedescription", "emptyfixedarray"
            }
            and address is not None
        ):
            is_array = root_name.replace("_", "").lower() == "emptyfixedarray"
            target_type = "FixedArray" if is_array else "ObjectBoilerplateDescription"
            contents = {"length": 0, "elements": []} if is_array else {
                "capacity": 0, "backing_store_size": 0, "flags": 0, "entries": []
            }
            result.update(
                target_type=target_type,
                type_evidence={"kind": "profile_root_name"},
                resolution="profile_metadata",
                description=f"<{target_type}>",
            )
            self._put(address, {
                "type": target_type,
                "type_evidence": {"kind": "profile_root_name"},
                **contents,
                "external": True, "provenance": result["source"],
                "reference_kind": reference.kind,
            })
        elif address is not None:
            target_type = "RootObject" if reference.kind == "root" else "ReadOnlyObject"
            description = root_name or target_type
            result.update(
                target_type=target_type,
                type_evidence={"kind": "unresolved"},
                resolution="external_identity",
                description=f"<{description}>",
            )
            self._put(
                address,
                {
                    "type": target_type,
                    "type_evidence": {"kind": "unresolved"},
                    "name": root_name,
                    "external": True,
                    "provenance": result["source"],
                    "reference_kind": reference.kind,
                    "reference_values": list(reference.values),
                },
            )
        else:
            values = ",".join(str(value) for value in reference.values)
            suffix = f"_{values}" if values else ""
            result["description"] = f"<{reference.kind}{suffix}>"
        return result
