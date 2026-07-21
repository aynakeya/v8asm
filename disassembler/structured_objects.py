from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .disassembler import (
    _decode_string,
    _fixed_array_object_values,
    _map_name,
    _map_type,
    _read_smi,
    _read_u32,
)
from .model import BytecodeArray, ParsedDisassembly
from .serializer import Reference, SerializedObject


ReferenceEncoder = Callable[[Reference | None], dict[str, Any] | None]


class StructuredObjectEncoder:
    def __init__(
        self,
        parsed: ParsedDisassembly,
        arrays: dict[int, BytecodeArray],
        semantic_types: dict[int, str],
        encode_reference: ReferenceEncoder,
    ) -> None:
        self.parsed = parsed
        self.arrays = arrays
        self.semantic_types = semantic_types
        self.encode_reference = encode_reference

    def serializer_metadata(self, obj: SerializedObject) -> dict[str, Any]:
        return {
            "object_index": obj.index,
            "space": obj.space,
            "size": obj.size,
            "payload_offset": obj.payload_offset,
            "map": self.encode_reference(obj.map_reference),
            "references": {
                f"0x{offset:08x}": self.encode_reference(reference)
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

    def object_type(self, obj: SerializedObject) -> str:
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

    def encode(self, obj: SerializedObject) -> dict[str, Any]:
        record: dict[str, Any] = {
            "type": self.object_type(obj),
            "serializer": self.serializer_metadata(obj),
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
                constant_elements=self.encode_reference(constant_elements),
            )
        elif object_type == "ObjectBoilerplateDescription":
            self._populate_object_boilerplate(record, obj)
        elif object_type == "ScopeInfo":
            self._populate_scope_info(record, obj)
        return record

    def _value(self, value: int | Reference) -> dict[str, Any]:
        if isinstance(value, int):
            return {"kind": "smi", "value": value}
        reference = self.encode_reference(value)
        if reference is None:
            return {"kind": "unresolved"}
        return reference

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
        if (
            layout.module_count_before_locals
            and scope_type_value == layout.module_scope_value
        ):
            slot += 1
        inlined = context_count < layout.max_inlined_local_names
        names: list[dict[str, Any]] = []
        names_container = None
        if inlined:
            for local_index in range(context_count):
                name = self.encode_reference(
                    obj.references.get((slot + local_index) * tagged_size)
                )
                names.append(
                    {
                        "local_index": local_index,
                        "context_slot": context_header_length + local_index,
                        "name": name,
                    }
                )
            info_slot = slot + context_count
        else:
            names_container = self.encode_reference(
                obj.references.get(slot * tagged_size)
            )
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
