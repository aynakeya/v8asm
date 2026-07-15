from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .cache import CacheHeader, parse_header
from .profiles import Opcode, Profile, ProfileSet, load_profiles
from .serializer import ObjectStreamParser, ParseError, Reference, SerializedObject
from .snapshot import ReadOnlySnapshot


@dataclass(frozen=True)
class Instruction:
    offset: int
    raw: bytes
    name: str
    operands: tuple[tuple[str, int], ...]
    scale: int
    jump_mode: str | None


@dataclass(frozen=True)
class BytecodeArray:
    object_index: int
    file_offset: int
    object_offset: int
    bytecode_offset: int
    data: bytes
    instructions: tuple[Instruction, ...]
    parameter_count: int
    register_count: int
    frame_size: int
    constant_pool: tuple[int | Reference, ...]
    handler_table_size: int
    handler_entries: tuple[tuple[int, int, int, int, int], ...]
    source_position_table_size: int


@dataclass(frozen=True)
class FunctionInfo:
    sfi_object_index: int
    array_object_index: int
    name_reference: Reference | None
    name_value: str | None


def _operand_size(kind: str, scale: int, profiles: ProfileSet) -> int:
    if kind in profiles.scalable_signed or kind in profiles.scalable_unsigned:
        return scale
    try:
        return profiles.fixed_sizes[kind]
    except KeyError as exc:
        raise ValueError(f"unknown operand type {kind}") from exc


def decode_instructions(
    data: bytes, profile: Profile, profiles: ProfileSet
) -> tuple[Instruction, ...]:
    opcodes = profile.opcode_by_value
    instructions: list[Instruction] = []
    offset = 0
    while offset < len(data):
        start = offset
        raw_opcode = data[offset]
        offset += 1
        scale = 1
        if raw_opcode in (0, 1):
            scale = 2 if raw_opcode == 0 else 4
            if offset >= len(data):
                raise ValueError("truncated Wide/ExtraWide instruction")
            raw_opcode = data[offset]
            offset += 1
        opcode = opcodes.get(raw_opcode)
        if opcode is None:
            raise ValueError(f"unknown opcode 0x{raw_opcode:02x} at {start}")
        operands: list[tuple[str, int]] = []
        for kind in opcode.operands:
            size = _operand_size(kind, scale, profiles)
            if offset + size > len(data):
                raise ValueError(f"truncated {opcode.name} at {start}")
            signed = kind in profiles.scalable_signed
            value = int.from_bytes(data[offset : offset + size], "little", signed=signed)
            offset += size
            operands.append((kind, value))
        suffix = "Wide" if scale == 2 else "ExtraWide"
        name = opcode.name if scale == 1 else f"{opcode.name}.{suffix}"
        instructions.append(
            Instruction(
                start,
                data[start:offset],
                name,
                tuple(operands),
                scale,
                opcode.jump_mode,
            )
        )
    return tuple(instructions)


def _read_smi(image: bytes, present: bytes, offset: int, tagged_size: int) -> int | None:
    end = offset + tagged_size
    if offset < 0 or end > len(image) or not all(present[offset:end]):
        return None
    raw = int.from_bytes(image[offset:end], "little", signed=True)
    if tagged_size == 4:
        return raw >> 1 if not raw & 1 else None
    return raw >> 32 if raw & 0xFFFFFFFF == 0 else None


def _smi_lengths(
    image: bytes, present: bytes, tagged_size: int
) -> tuple[tuple[int, int], ...]:
    lengths: list[tuple[int, int]] = []
    # BytecodeArray extends HeapObject in older builds and ExposedTrustedObject
    # in sandbox builds. The latter inserts a self-indirect-pointer after map.
    for slot in (1, 2):
        offset = slot * tagged_size
        value = _read_smi(image, present, offset, tagged_size)
        if value is not None:
            lengths.append((offset, value))
    return tuple(lengths)


def _read_i32(image: bytes, present: bytes, offset: int) -> int | None:
    end = offset + 4
    if offset < 0 or end > len(image) or not all(present[offset:end]):
        return None
    return int.from_bytes(image[offset:end], "little", signed=True)


def _read_u32(image: bytes, present: bytes, offset: int) -> int | None:
    end = offset + 4
    if offset < 0 or end > len(image) or not all(present[offset:end]):
        return None
    return int.from_bytes(image[offset:end], "little")


def _target_object(
    reference: Reference | None, objects: list[SerializedObject]
) -> SerializedObject | None:
    if reference is None or reference.object_index is None:
        return None
    if not 0 <= reference.object_index < len(objects):
        return None
    return objects[reference.object_index]


def _fixed_array_values(
    reference: Reference | None,
    objects: list[SerializedObject],
    tagged_size: int,
) -> tuple[int | Reference, ...]:
    obj = _target_object(reference, objects)
    if obj is None:
        return ()
    image, present = obj.image()
    length = _read_smi(image, present, tagged_size, tagged_size)
    if length is None or length < 0 or 2 * tagged_size + length * tagged_size > obj.size:
        return ()
    values: list[int | Reference] = []
    for index in range(length):
        offset = (index + 2) * tagged_size
        element_reference = obj.references.get(offset)
        if element_reference is not None:
            values.append(element_reference)
            continue
        smi = _read_smi(image, present, offset, tagged_size)
        if smi is not None:
            values.append(smi)
        else:
            raw = int.from_bytes(image[offset : offset + tagged_size], "little")
            values.append(Reference("raw", (raw,)))
    return tuple(values)


def _byte_array_data(
    reference: Reference | None,
    objects: list[SerializedObject],
    tagged_size: int,
) -> bytes:
    obj = _target_object(reference, objects)
    if obj is None:
        return b""
    image, present = obj.image()
    length = _read_smi(image, present, tagged_size, tagged_size)
    start = 2 * tagged_size
    if length is None or length < 0 or start + length > obj.size:
        return b""
    if not all(present[start : start + length]):
        return b""
    return image[start : start + length]


def _handler_entries(data: bytes) -> tuple[tuple[int, int, int, int, int], ...]:
    if len(data) % 16:
        return ()
    entries: list[tuple[int, int, int, int, int]] = []
    for offset in range(0, len(data), 16):
        start, end, encoded, context = (
            int.from_bytes(data[index : index + 4], "little", signed=True)
            for index in range(offset, offset + 16, 4)
        )
        prediction = encoded & 0x7
        handler = (encoded & 0xFFFFFFFF) >> 4
        entries.append((start, end, handler, prediction, context))
    return tuple(entries)


def _array_metadata(
    obj: SerializedObject,
    objects: list[SerializedObject],
    profile: Profile,
    tagged_size: int,
    length_offset: int,
) -> tuple[
    int,
    int,
    int,
    tuple[int | Reference, ...],
    bytes,
    bytes,
] | None:
    image, present = obj.image()
    layout = profile.bytecode_array_layout
    # Reading from the final bytecode offset is ambiguous because V8 pads the
    # header differently with and without pointer compression. The scalar
    # fields have stable offsets relative to the length field instead.
    fields_start = length_offset + layout.frame_size_slot_delta * tagged_size

    frame_size = _read_i32(image, present, fields_start)
    if frame_size is None or frame_size < 0 or frame_size % 8:
        return None
    if layout.parameter_encoding == "count_u16":
        parameter_offset = fields_start + 4
        if parameter_offset + 2 > len(image) or not all(
            present[parameter_offset : parameter_offset + 2]
        ):
            return None
        parameter_count = int.from_bytes(
            image[parameter_offset : parameter_offset + 2], "little"
        )
    elif layout.parameter_encoding == "size_i32":
        parameter_size = _read_i32(image, present, fields_start + 4)
        if parameter_size is None or parameter_size < 0 or parameter_size % 8:
            return None
        parameter_count = parameter_size // 8
    else:
        raise ValueError(f"unknown parameter encoding {layout.parameter_encoding}")

    constant_reference = obj.references.get(
        length_offset + layout.constant_pool_slot_delta * tagged_size
    )
    handler_reference = obj.references.get(
        length_offset + layout.handler_table_slot_delta * tagged_size
    )
    source_reference = obj.references.get(
        length_offset + layout.source_position_table_slot_delta * tagged_size
    )

    return (
        parameter_count,
        frame_size // 8,
        frame_size,
        _fixed_array_values(constant_reference, objects, tagged_size),
        _byte_array_data(handler_reference, objects, tagged_size),
        _byte_array_data(source_reference, objects, tagged_size),
    )


def _terminal(instructions: tuple[Instruction, ...]) -> bool:
    if not instructions:
        return False
    return instructions[-1].name.split(".", 1)[0] in {
        "Abort",
        "ReThrow",
        "Return",
        "SuspendGenerator",
        "Throw",
    }


def find_bytecode_arrays(
    objects: list[SerializedObject],
    profile: Profile,
    profiles: ProfileSet,
    tagged_size: int,
    payload_file_offset: int,
) -> list[BytecodeArray]:
    arrays: list[BytecodeArray] = []
    for obj in objects:
        image, present = obj.image()
        found = False
        for length_offset, length in _smi_lengths(image, present, tagged_size):
            if length <= 0 or length > obj.size:
                continue
            # kHeaderSize is not necessarily tagged-aligned (for example it is
            # 34 bytes in V8 10.8). Object allocation only pads the tail.
            for padding in range(8):
                start = obj.size - length - padding
                if start < 2 * tagged_size or start + length > obj.size:
                    continue
                if not all(present[start : start + length]):
                    continue
                bytecode = image[start : start + length]
                try:
                    instructions = decode_instructions(bytecode, profile, profiles)
                except ValueError:
                    continue
                if not _terminal(instructions):
                    continue
                metadata = _array_metadata(
                    obj,
                    objects,
                    profile,
                    tagged_size,
                    length_offset,
                )
                if metadata is None:
                    continue
                (
                    parameter_count,
                    register_count,
                    frame_size,
                    constant_pool,
                    handler_data,
                    source_position_data,
                ) = metadata
                payload_offset = None
                for chunk in obj.raw_chunks:
                    if chunk.object_offset <= start < chunk.object_offset + len(chunk.data):
                        payload_offset = chunk.payload_offset + start - chunk.object_offset
                        break
                if payload_offset is None:
                    continue
                arrays.append(
                    BytecodeArray(
                        object_index=obj.index,
                        file_offset=payload_file_offset + payload_offset,
                        object_offset=payload_file_offset + obj.payload_offset,
                        bytecode_offset=start,
                        data=bytecode,
                        instructions=instructions,
                        parameter_count=parameter_count,
                        register_count=register_count,
                        frame_size=frame_size,
                        constant_pool=constant_pool,
                        handler_table_size=len(handler_data),
                        handler_entries=_handler_entries(handler_data),
                        source_position_table_size=len(source_position_data),
                    )
                )
                found = True
                break
            if found:
                break
    return arrays


def _register_name(operand: int, profile: Profile) -> str:
    if operand == -1:
        return "<context>"
    if operand == -2:
        return "<closure>"
    if operand >= 2:
        parameter_index = operand - 2
        return "<this>" if parameter_index == 0 else f"a{parameter_index - 1}"
    index = profile.register_file_start - operand
    return f"r{index}"


def _format_operands(
    instruction: Instruction, profile: Profile, runtime_names: tuple[str, ...]
) -> str:
    values: list[str] = []
    index = 0
    while index < len(instruction.operands):
        kind, value = instruction.operands[index]
        if kind in {"Idx", "UImm", "Imm"}:
            values.append(f"[{value}]")
        elif kind in {"Flag8", "Flag16"}:
            values.append(f"#{value}")
        elif kind == "RuntimeId":
            name = runtime_names[value] if value < len(runtime_names) else value
            values.append(f"[{name}]")
        elif kind == "IntrinsicId":
            name = (
                profile.intrinsic_names[value]
                if value < len(profile.intrinsic_names)
                else value
            )
            values.append(f"[{name}]")
        elif kind == "NativeContextIndex":
            values.append(f"[{value}]")
        elif kind in {"Reg", "RegOut", "RegInOut"}:
            values.append(_register_name(value, profile))
        elif kind in {"RegPair", "RegOutPair", "RegOutTriple"}:
            count = 3 if kind == "RegOutTriple" else 2
            first = _register_name(value, profile)
            last = _register_name(value - count + 1, profile)
            values.append(f"{first}-{last}")
        elif kind in {"RegList", "RegOutList"}:
            count = instruction.operands[index + 1][1]
            first = _register_name(value, profile)
            last = _register_name(value - count + 1, profile)
            values.append(f"{first}-{last}")
            index += 1
        elif kind != "RegCount":
            values.append(str(value))
        index += 1
    return ", ".join(values)


def _object_address(index: int) -> int:
    return 0xF00000000000 + index * 0x100


def _root_address(index: int) -> int:
    return 0xE00000000000 + index * 0x10


def _decode_string(obj: SerializedObject, tagged_size: int) -> str | None:
    image, present = obj.image()
    header_size = tagged_size + 8
    if header_size > obj.size or not all(present[tagged_size:header_size]):
        return None
    length = int.from_bytes(image[tagged_size + 4 : header_size], "little")
    if length > 16 * 1024 * 1024:
        return None

    candidates: list[tuple[int, str]] = []
    for width, encoding in ((1, "latin-1"), (2, "utf-16-le")):
        end = header_size + length * width
        allocated_size = (end + 7) & ~7
        if allocated_size != obj.size or end > obj.size or not all(present[header_size:end]):
            continue
        if any(image[end:obj.size]):
            continue
        try:
            value = image[header_size:end].decode(encoding)
        except UnicodeDecodeError:
            continue
        score = sum(character.isprintable() or character in "\t\r\n" for character in value)
        candidates.append((score, value))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], -len(item[1])))[1]


def _profile_string(
    reference: Reference,
    profile: Profile,
    snapshot: ReadOnlySnapshot | None,
) -> str | None:
    if reference.kind == "root" and reference.values:
        return profile.root_strings.get(reference.values[0])
    if reference.kind == "read_only" and len(reference.values) == 2:
        page, offset = reference.values
        if snapshot is not None:
            value = snapshot.string_at(page, offset)
            if value is not None:
                return value
        if page == 0:
            return profile.read_only_strings.get(offset)
    return None


def _map_type(obj: SerializedObject, profile: Profile) -> str | None:
    reference = obj.map_reference
    if reference is None or reference.kind != "root" or not reference.values:
        return None
    index = reference.values[0]
    if index >= len(profile.root_names):
        return None
    return profile.root_names[index].replace("_", "").lower()


def _reference_string(
    reference: Reference | None,
    profile: Profile,
    objects: list[SerializedObject],
    tagged_size: int,
    snapshot: ReadOnlySnapshot | None,
) -> str | None:
    if reference is None:
        return None
    target = _target_object(reference, objects)
    if target is not None:
        return _decode_string(target, tagged_size)
    return _profile_string(reference, profile, snapshot)


def _scope_function_name(
    obj: SerializedObject,
    profile: Profile,
    objects: list[SerializedObject],
    tagged_size: int,
    snapshot: ReadOnlySnapshot | None,
) -> tuple[Reference | None, str | None]:
    image, present = obj.image()
    layout = profile.scope_info_layout
    flags_offset = tagged_size
    if layout.flags_encoding == "smi":
        flags = _read_smi(image, present, flags_offset, tagged_size)
    else:
        flags = _read_u32(image, present, flags_offset)
    context_count = _read_smi(image, present, 3 * tagged_size, tagged_size)
    if flags is None or context_count is None or not 0 <= context_count <= obj.size // tagged_size:
        return None, None

    slot = layout.variable_part_slot
    scope_type = (flags >> layout.scope_type_shift) & layout.scope_type_mask
    if layout.module_count_before_locals and scope_type == layout.module_scope_value:
        slot += 1
    slot += context_count if context_count < layout.max_inlined_local_names else 1
    slot += context_count
    if flags & (1 << layout.saved_class_variable_bit):
        slot += 1

    function_variable = (
        flags >> layout.function_variable_shift
    ) & layout.function_variable_mask
    name_reference = None
    if function_variable:
        name_reference = obj.references.get(slot * tagged_size)
        slot += 2
        name = _reference_string(
            name_reference, profile, objects, tagged_size, snapshot
        )
        if name:
            return name_reference, name
        if (
            name is None
            and name_reference is not None
            and name_reference.kind == "read_only"
        ):
            return name_reference, None
        if name is None:
            name_reference = None

    if flags & (1 << layout.inferred_function_name_bit):
        inferred_reference = obj.references.get(slot * tagged_size)
        inferred = _reference_string(
            inferred_reference, profile, objects, tagged_size, snapshot
        )
        if inferred_reference is not None and (
            inferred is not None or inferred_reference.kind == "read_only"
        ):
            return inferred_reference, inferred
    return name_reference, _reference_string(
        name_reference, profile, objects, tagged_size, snapshot
    )


def _function_infos(
    objects: list[SerializedObject],
    arrays: list[BytecodeArray],
    profile: Profile,
    tagged_size: int,
    snapshot: ReadOnlySnapshot | None,
) -> dict[int, FunctionInfo]:
    arrays_by_object = {array.object_index: array for array in arrays}
    infos: dict[int, FunctionInfo] = {}
    layout = profile.shared_function_info_layout
    for obj in objects:
        if _map_type(obj, profile) != "sharedfunctioninfomap":
            continue
        array = None
        for slot in layout.function_data_slots:
            target = _target_object(obj.references.get(slot * tagged_size), objects)
            if target is not None and target.index in arrays_by_object:
                array = arrays_by_object[target.index]
                break
        if array is None:
            continue

        name_reference = None
        name_value = None
        for slot in layout.name_or_scope_info_slots:
            reference = obj.references.get(slot * tagged_size)
            target = _target_object(reference, objects)
            if target is not None and _map_type(target, profile) == "scopeinfomap":
                name_reference, name_value = _scope_function_name(
                    target, profile, objects, tagged_size, snapshot
                )
                break
            value = _reference_string(
                reference, profile, objects, tagged_size, snapshot
            )
            if reference is not None and value is not None:
                name_reference, name_value = reference, value
                break
        infos[obj.index] = FunctionInfo(
            obj.index, array.object_index, name_reference, name_value
        )
    return infos


def _format_reference(
    reference: Reference,
    profile: Profile,
    objects: list[SerializedObject],
    tagged_size: int,
    snapshot: ReadOnlySnapshot | None,
    functions: dict[int, FunctionInfo] | None = None,
) -> str:
    target = _target_object(reference, objects)
    if target is not None:
        address = _object_address(target.index)
        string = _decode_string(target, tagged_size)
        function = functions.get(target.index) if functions is not None else None
        if string is not None:
            description = f"<String[{len(string)}]>"
        elif function is not None:
            suffix = f" {function.name_value}" if function.name_value else ""
            description = f"<SharedFunctionInfo{suffix}>"
        else:
            description = f"<object_{target.index}>"
        return f"0x{address:012x} {description}"
    profile_string = _profile_string(reference, profile, snapshot)
    if profile_string is not None:
        if reference.kind == "root":
            address = _root_address(reference.values[0])
        else:
            address = _root_address(0x20000 + reference.values[1])
        return f"0x{address:012x} <String[{len(profile_string)}]>"
    if reference.kind == "root" and reference.values:
        index = reference.values[0]
        names = {4: "undefined", 6: "null", 7: "true", 8: "false"}
        root_name = profile.root_names[index] if index < len(profile.root_names) else None
        description = names.get(index, root_name or f"root_{index}")
        return f"0x{_root_address(index):012x} <{description}>"
    values = ",".join(str(value) for value in reference.values)
    identity = sum((index + 1) * value for index, value in enumerate(reference.values))
    address = _root_address(0x10000 + (identity & 0xFFFF))
    description = reference.kind + (f"_{values}" if values else "")
    return f"0x{address:012x} <{description}>"


def _render_constant_pool(
    array: BytecodeArray,
    objects: list[SerializedObject],
    profile: Profile,
    tagged_size: int,
    rendered_strings: set[tuple[str, int]],
    functions: dict[int, FunctionInfo],
    snapshot: ReadOnlySnapshot | None,
) -> list[str]:
    if not array.constant_pool:
        return []
    pool_address = 0xD00000000000 + array.object_index * 0x100
    lines = [
        f"0x{pool_address:012x}: [TrustedFixedArray]",
        f" - length: {len(array.constant_pool)}",
    ]
    string_indexes: list[int] = []
    profile_strings: list[tuple[int, str]] = []
    for index, value in enumerate(array.constant_pool):
        if isinstance(value, Reference):
            rendered = _format_reference(
                value, profile, objects, tagged_size, snapshot, functions
            )
            if value.object_index is not None:
                target = objects[value.object_index]
                if _decode_string(target, tagged_size) is not None:
                    string_indexes.append(target.index)
            else:
                profile_string = _profile_string(value, profile, snapshot)
                if profile_string is not None:
                    address = (
                        _root_address(value.values[0])
                        if value.kind == "root"
                        else _root_address(0x20000 + value.values[1])
                    )
                    profile_strings.append((address, profile_string))
        else:
            rendered = str(value)
        lines.append(f"{index:12d}: {rendered}")
    for object_index in string_indexes:
        key = ("object", object_index)
        if key in rendered_strings:
            continue
        value = _decode_string(objects[object_index], tagged_size)
        if value is None:
            continue
        rendered_strings.add(key)
        lines.append(
            f"0x{_object_address(object_index):012x}: [String]: "
            f"{json.dumps(value, ensure_ascii=True)}"
        )
    for address, value in profile_strings:
        key = ("profile", address)
        if key in rendered_strings:
            continue
        rendered_strings.add(key)
        lines.append(
            f"0x{address:012x}: [String]: {json.dumps(value, ensure_ascii=True)}"
        )
    return lines


def _render_function_infos(
    functions: dict[int, FunctionInfo],
    arrays: list[BytecodeArray],
    objects: list[SerializedObject],
    profile: Profile,
    tagged_size: int,
    rendered_strings: set[tuple[str, int]],
    snapshot: ReadOnlySnapshot | None,
) -> list[str]:
    arrays_by_object = {array.object_index: array for array in arrays}
    lines: list[str] = []
    for function in functions.values():
        array = arrays_by_object[function.array_object_index]
        lines.extend(
            [
                "",
                f"0x{_object_address(function.sfi_object_index):012x}: "
                "[SharedFunctionInfo]",
            ]
        )
        if function.name_reference is not None:
            lines.append(
                " - name: "
                + _format_reference(
                    function.name_reference,
                    profile,
                    objects,
                    tagged_size,
                    snapshot,
                )
            )
        lines.extend(
            [
                f" - formal_parameter_count: {array.parameter_count}",
                f" - trusted_function_data: 0x{array.object_offset:08x} "
                f"<BytecodeArray[{len(array.data)}]>",
            ]
        )
        reference = function.name_reference
        if reference is None or function.name_value is None:
            continue
        target = _target_object(reference, objects)
        if target is not None:
            key = ("object", target.index)
            address = _object_address(target.index)
        elif reference.kind == "root":
            key = ("profile", _root_address(reference.values[0]))
            address = key[1]
        elif reference.kind == "read_only" and len(reference.values) == 2:
            key = ("profile", _root_address(0x20000 + reference.values[1]))
            address = key[1]
        else:
            continue
        if key in rendered_strings:
            continue
        rendered_strings.add(key)
        lines.append(
            f"0x{address:012x}: [String]: "
            f"{json.dumps(function.name_value, ensure_ascii=True)}"
        )
    return lines


def _jump_target(instruction: Instruction, array: BytecodeArray) -> int | None:
    if instruction.jump_mode is None or not instruction.operands:
        return None
    value = instruction.operands[0][1]
    if instruction.jump_mode == "forward_constant":
        if value >= len(array.constant_pool):
            return None
        constant = array.constant_pool[value]
        if not isinstance(constant, int):
            return None
        relative = constant
    elif instruction.jump_mode == "backward_immediate":
        relative = -value
    elif instruction.jump_mode == "forward_immediate":
        relative = value
    else:
        return None
    target = instruction.offset + relative + (1 if instruction.scale != 1 else 0)
    return target if 0 <= target <= len(array.data) else None


def _render(
    header: CacheHeader,
    profile: Profile,
    tagged_size: int,
    objects: list[SerializedObject],
    arrays: list[BytecodeArray],
    runtime_variant: str | None,
    snapshot: ReadOnlySnapshot | None,
) -> str:
    lines = [
        f"# disassembler V8 {profile.version}",
        f"# magic=0x{header.magic:08x} "
        f"version_hash=0x{header.version_hash:08x} tagged_size={tagged_size}",
        f"# bytecode_arrays={len(arrays)}",
    ]
    runtime_names = profile.runtime_names_for(header.flags_hash, runtime_variant)
    rendered_strings: set[tuple[str, int]] = set()
    functions = _function_infos(objects, arrays, profile, tagged_size, snapshot)
    for array in arrays:
        lines.extend(
            [
                "",
                f"0x{array.object_offset:08x}: [BytecodeArray]",
                f"Parameter count {array.parameter_count}",
                f"Register count {array.register_count}",
                f"Frame size {array.frame_size}",
            ]
        )
        for instruction in array.instructions:
            raw = " ".join(f"{value:02x}" for value in instruction.raw)
            operands = _format_operands(instruction, profile, runtime_names)
            suffix = f" {operands}" if operands else ""
            target = _jump_target(instruction, array)
            if target is not None:
                suffix += f" (0x{array.file_offset + target:08x} @ {target})"
            lines.append(
                f"         0x{array.file_offset + instruction.offset:08x} "
                f"@ {instruction.offset:4d} : "
                f"{raw:<20} {instruction.name}{suffix}"
            )
        lines.extend(
            [
                f"Constant pool (size = {len(array.constant_pool)})",
                f"Handler Table (size = {array.handler_table_size})",
            ]
        )
        if array.handler_entries:
            lines.append("   from   to       hdlr (prediction,   data)")
            for start, end, handler, prediction, data in array.handler_entries:
                lines.append(
                    f"  ({start:4d},{end:4d})  ->  {handler:4d} "
                    f"(prediction={prediction}, data={data})"
                )
        lines.append(
            f"Source Position Table (size = {array.source_position_table_size})"
        )
        lines.extend(
            _render_constant_pool(
                array,
                objects,
                profile,
                tagged_size,
                rendered_strings,
                functions,
                snapshot,
            )
        )
    lines.extend(
        _render_function_infos(
            functions,
            arrays,
            objects,
            profile,
            tagged_size,
            rendered_strings,
            snapshot,
        )
    )
    return "\n".join(lines) + "\n"


def disassemble_bytes(
    data: bytes,
    version: str | None = None,
    runtime_variant: str | None = None,
    snapshot_blob: bytes | None = None,
) -> str:
    profiles = load_profiles()
    header, profile = parse_header(data, profiles, version)
    payload = data[header.header_size : header.header_size + header.payload_length]
    failures: list[str] = []
    for tagged_size in (4, 8):
        try:
            objects = ObjectStreamParser(payload, profile, tagged_size).parse()
            arrays = find_bytecode_arrays(
                objects, profile, profiles, tagged_size, header.header_size
            )
        except (ParseError, ValueError) as exc:
            failures.append(f"tagged_size={tagged_size}: {exc}")
            continue
        if arrays:
            snapshot = None
            if snapshot_blob is not None:
                snapshot = ReadOnlySnapshot.parse(
                    snapshot_blob, profile, tagged_size
                )
                if snapshot.magic != header.magic:
                    raise ValueError(
                        f"snapshot magic 0x{snapshot.magic:08x} does not match "
                        f"cached data 0x{header.magic:08x}"
                    )
                if (
                    header.ro_snapshot_checksum is not None
                    and snapshot.checksum != header.ro_snapshot_checksum
                ):
                    raise ValueError(
                        f"snapshot read-only checksum 0x{snapshot.checksum:08x} "
                        "does not match cached data "
                        f"0x{header.ro_snapshot_checksum:08x}"
                    )
            return _render(
                header,
                profile,
                tagged_size,
                objects,
                arrays,
                runtime_variant,
                snapshot,
            )
        failures.append(f"tagged_size={tagged_size}: no BytecodeArray candidates")
    raise ValueError("unable to parse V8 cached data: " + "; ".join(failures))


def disassemble_file(
    path: str | Path,
    version: str | None = None,
    runtime_variant: str | None = None,
    snapshot_blob: str | Path | None = None,
) -> str:
    snapshot_data = (
        Path(snapshot_blob).read_bytes() if snapshot_blob is not None else None
    )
    return disassemble_bytes(
        Path(path).read_bytes(), version, runtime_variant, snapshot_data
    )
