from __future__ import annotations

from dataclasses import dataclass

from .cache import CacheHeader
from .profiles import Profile
from .serializer import Reference, SerializedObject
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
    scope_info_object_index: int | None
    name_reference: Reference | None
    name_value: str | None


@dataclass(frozen=True)
class ParsedDisassembly:
    header: CacheHeader
    profile: Profile
    tagged_size: int
    objects: tuple[SerializedObject, ...]
    arrays: tuple[BytecodeArray, ...]
    functions: dict[int, FunctionInfo]
    runtime_variant: str | None
    snapshot: ReadOnlySnapshot | None
