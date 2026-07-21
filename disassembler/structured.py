from __future__ import annotations

from typing import Any

from .disassembler import (
    _decode_string,
    _fixed_array_object_values,
    _jump_target,
    _map_name,
    _map_type,
    _object_address,
    _operand_arguments,
    _profile_string,
    _read_smi,
    _read_u32,
    _root_address,
    _target_object,
)
from .model import BytecodeArray, ParsedDisassembly
from .serializer import Reference, SerializedObject


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


def _root_literal(name: str | None) -> str | None:
    if name is None:
        return None
    normalized = "".join(character for character in name.lower() if character.isalpha())
    for literal in ("undefined", "null", "true", "false"):
        if normalized in {literal, f"{literal}value"}:
            return literal
    return None


class _GraphBuilder:
    def __init__(self, parsed: ParsedDisassembly) -> None:
        self.parsed = parsed
        self.objects = list(parsed.objects)
        self.arrays = {array.object_index: array for array in parsed.arrays}
        self.semantic_types: dict[int, str] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self._index_semantic_types()

    def _index_semantic_types(self) -> None:
        literal_types = {
            "CreateArrayLiteral": "ArrayBoilerplateDescription",
            "CreateObjectLiteral": "ObjectBoilerplateDescription",
        }
        for array in self.parsed.arrays:
            for instruction in array.instructions:
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
            "runtime_variant": runtime_variant,
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

    def _serializer_metadata(self, obj: SerializedObject) -> dict[str, Any]:
        return {
            "object_index": obj.index,
            "space": obj.space,
            "size": obj.size,
            "payload_offset": obj.payload_offset,
            "map": self._reference(obj.map_reference),
            "references": {
                f"0x{offset:08x}": self._reference(reference)
                for offset, reference in sorted(obj.references.items())
            },
            "raw_chunks": [
                {
                    "object_offset": chunk.object_offset,
                    "payload_offset": chunk.payload_offset,
                    "size": len(chunk.data),
                }
                for chunk in obj.raw_chunks
            ],
        }

    def _object_type(self, obj: SerializedObject) -> str:
        if obj.index in self.arrays:
            return "BytecodeArray"
        if obj.index in self.parsed.functions:
            return "SharedFunctionInfo"
        if obj.index in self.semantic_types:
            return self.semantic_types[obj.index]
        if _decode_string(obj, self.parsed.profile, self.parsed.tagged_size) is not None:
            return "String"
        map_type = _map_type(obj, self.parsed.profile)
        special = {
            "arrayboilerplatedescriptionmap": "ArrayBoilerplateDescription",
            "fixedarraymap": "FixedArray",
            "fixedcowarraymap": "FixedArray",
            "objectboilerplatedescriptionmap": "ObjectBoilerplateDescription",
            "scopeinfomap": "ScopeInfo",
            "sharedfunctioninfomap": "SharedFunctionInfo",
        }
        if map_type in special:
            return special[map_type]
        map_name = _map_name(obj, self.parsed.profile)
        if map_name:
            return map_name.removesuffix("Map")
        return "SerializedObject"

    def _add_serialized_object(self, obj: SerializedObject) -> None:
        record: dict[str, Any] = {
            "type": self._object_type(obj),
            "serializer": self._serializer_metadata(obj),
        }
        object_type = record["type"]
        if object_type == "String":
            value = _decode_string(obj, self.parsed.profile, self.parsed.tagged_size)
            record.update(value=value, length=len(value or ""))
        elif object_type == "FixedArray":
            values = _fixed_array_object_values(obj, self.parsed.tagged_size)
            record.update(
                length=len(values),
                elements=[self._value(value) for value in values],
                copy_on_write=_map_type(obj, self.parsed.profile)
                == "fixedcowarraymap",
            )
        elif object_type == "ArrayBoilerplateDescription":
            image, present = obj.image()
            elements_kind = _read_smi(
                image, present, self.parsed.tagged_size, self.parsed.tagged_size
            )
            constant_elements = obj.references.get(2 * self.parsed.tagged_size)
            record.update(
                elements_kind=elements_kind,
                constant_elements=self._reference(constant_elements),
            )
        elif object_type == "ObjectBoilerplateDescription":
            self._populate_object_boilerplate(record, obj)
        elif object_type == "ScopeInfo":
            self._populate_scope_info(record, obj)
        self._put(_object_address(obj.index), record)

    def _tagged_value(
        self, obj: SerializedObject, slot: int
    ) -> dict[str, Any] | None:
        tagged_size = self.parsed.tagged_size
        offset = slot * tagged_size
        reference = obj.references.get(offset)
        if reference is not None:
            return self._value(reference)
        image, present = obj.image()
        value = _read_smi(image, present, offset, tagged_size)
        if value is not None:
            return self._value(value)
        end = offset + tagged_size
        if end <= len(image) and all(present[offset:end]):
            raw = int.from_bytes(image[offset:end], "little")
            return self._value(Reference("raw", (raw,)))
        return None

    def _populate_object_boilerplate(
        self, record: dict[str, Any], obj: SerializedObject
    ) -> None:
        layout = self.parsed.profile.object_boilerplate_layout
        tagged_size = self.parsed.tagged_size
        image, present = obj.image()
        capacity = _read_smi(
            image, present, layout.capacity_slot * tagged_size, tagged_size
        )
        flags = _read_smi(
            image, present, layout.flags_slot * tagged_size, tagged_size
        )
        if capacity is None or capacity < 0 or flags is None:
            return

        if layout.backing_store_size_in_tail:
            value_count = max(0, capacity - 1)
            has_backing_store_size = bool(value_count % 2)
            entry_value_count = value_count - int(has_backing_store_size)
            backing_store_size = entry_value_count // 2
            if has_backing_store_size:
                tail = self._tagged_value(
                    obj, layout.elements_slot + entry_value_count
                )
                if tail and tail.get("kind") == "smi":
                    backing_store_size = tail["value"]
        else:
            entry_value_count = capacity
            backing_store_size = _read_smi(
                image,
                present,
                (layout.backing_store_size_slot or 0) * tagged_size,
                tagged_size,
            )

        entries = [
            value
            for index in range(entry_value_count)
            if (value := self._tagged_value(obj, layout.elements_slot + index))
            is not None
        ]
        if len(entries) != entry_value_count:
            return
        record.update(
            capacity=capacity,
            backing_store_size=backing_store_size,
            flags=flags,
            entries=entries,
        )

    def _populate_scope_info(
        self, record: dict[str, Any], obj: SerializedObject
    ) -> None:
        tagged_size = self.parsed.tagged_size
        layout = self.parsed.profile.scope_info_layout
        image, present = obj.image()
        if layout.flags_encoding == "smi":
            flags = _read_smi(image, present, tagged_size, tagged_size)
        else:
            flags = _read_u32(image, present, tagged_size)
        parameter_count = _read_smi(image, present, 2 * tagged_size, tagged_size)
        context_count = _read_smi(image, present, 3 * tagged_size, tagged_size)
        if (
            flags is None
            or context_count is None
            or context_count < 0
            or context_count > obj.size // tagged_size
        ):
            return

        scope_type_value = (
            flags >> layout.scope_type_shift
        ) & layout.scope_type_mask
        scope_type = (
            layout.scope_type_names[scope_type_value]
            if scope_type_value < len(layout.scope_type_names)
            else f"SCOPE_TYPE_{scope_type_value}"
        )
        extended = bool(flags & (1 << layout.context_extension_slot_bit))
        context_header_length = (
            layout.min_context_extended_slots
            if extended
            else layout.min_context_slots
        )

        slot = layout.variable_part_slot
        if layout.module_count_before_locals and scope_type_value == layout.module_scope_value:
            slot += 1
        inlined = context_count < layout.max_inlined_local_names
        names: list[dict[str, Any]] = []
        names_container = None
        if inlined:
            for local_index in range(context_count):
                name = self._reference(obj.references.get((slot + local_index) * tagged_size))
                names.append(
                    {
                        "local_index": local_index,
                        "context_slot": context_header_length + local_index,
                        "name": name,
                    }
                )
            info_slot = slot + context_count
        else:
            names_container = self._reference(obj.references.get(slot * tagged_size))
            info_slot = slot + 1

        for local_index, local in enumerate(names):
            local["info"] = _read_smi(
                image,
                present,
                (info_slot + local_index) * tagged_size,
                tagged_size,
            )
        record.update(
            flags=flags,
            scope_type=scope_type,
            scope_type_value=scope_type_value,
            parameter_count=parameter_count,
            context_local_count=context_count,
            context_header_length=context_header_length,
            context_locals=names,
            context_local_names_inlined=inlined,
            context_local_names_container=names_container,
        )

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
        }
        if reference.object_index is not None:
            result["object_index"] = reference.object_index

        address = _reference_address(reference)
        if address is not None:
            result["address"] = _address(address)

        target = _target_object(reference, self.objects)
        if target is not None:
            result["target_type"] = self._object_type(target)
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
            result.update(target_type="String", description=f"<String[{len(value)}]>")
            if address is not None:
                self._put(
                    address,
                    {
                        "type": "String",
                        "value": value,
                        "length": len(value),
                        "external": True,
                        "reference_kind": reference.kind,
                    },
                )
        elif literal is not None:
            result.update(target_type="Primitive", literal=literal)
            result["description"] = f"<{literal}>"
            if address is not None:
                self._put(
                    address,
                    {
                        "type": "Primitive",
                        "value": literal,
                        "external": True,
                        "reference_kind": reference.kind,
                    },
                )
        elif address is not None:
            target_type = "RootObject" if reference.kind == "root" else "ReadOnlyObject"
            description = root_name or target_type
            result.update(target_type=target_type, description=f"<{description}>")
            self._put(
                address,
                {
                    "type": target_type,
                    "name": root_name,
                    "external": True,
                    "reference_kind": reference.kind,
                    "reference_values": list(reference.values),
                },
            )
        else:
            values = ",".join(str(value) for value in reference.values)
            suffix = f"_{values}" if values else ""
            result["description"] = f"<{reference.kind}{suffix}>"
        return result


def disassembly_to_dict(parsed: ParsedDisassembly) -> dict[str, Any]:
    return _GraphBuilder(parsed).build()
