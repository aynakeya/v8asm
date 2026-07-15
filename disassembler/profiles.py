from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Opcode:
    value: int
    name: str
    operands: tuple[str, ...]
    jump_mode: str | None


@dataclass(frozen=True)
class BytecodeArrayLayout:
    constant_pool_slot_delta: int
    handler_table_slot_delta: int
    source_position_table_slot_delta: int
    frame_size_slot_delta: int
    parameter_encoding: str


@dataclass(frozen=True)
class SharedFunctionInfoLayout:
    function_data_slots: tuple[int, ...]
    name_or_scope_info_slots: tuple[int, ...]


@dataclass(frozen=True)
class ScopeInfoLayout:
    flags_encoding: str
    variable_part_slot: int
    module_count_before_locals: bool
    module_scope_value: int
    max_inlined_local_names: int
    scope_type_shift: int
    scope_type_mask: int
    saved_class_variable_bit: int
    function_variable_shift: int
    function_variable_mask: int
    inferred_function_name_bit: int


@dataclass(frozen=True)
class Profile:
    version: str
    version_hash: int
    register_file_start: int
    has_ro_snapshot_checksum: bool
    snapshot_spaces: int
    serializer_tags: dict[str, int]
    bytecode_array_layout: BytecodeArrayLayout
    shared_function_info_layout: SharedFunctionInfoLayout
    scope_info_layout: ScopeInfoLayout
    runtime_default_variant: str
    runtime_variants: dict[str, tuple[str, ...]]
    runtime_variant_by_flags_hash: dict[int, str]
    intrinsic_names: tuple[str, ...]
    root_names: tuple[str, ...]
    root_strings: dict[int, str]
    read_only_strings: dict[int, str]
    static_root_maps: dict[int, str]
    static_root_area_start: int | None
    opcodes: tuple[Opcode, ...]

    @property
    def opcode_by_value(self) -> dict[int, Opcode]:
        return {opcode.value: opcode for opcode in self.opcodes}

    def runtime_names_for(
        self, flags_hash: int, variant: str | None = None
    ) -> tuple[str, ...]:
        selected = variant or self.runtime_variant_by_flags_hash.get(
            flags_hash, self.runtime_default_variant
        )
        try:
            return self.runtime_variants[selected]
        except KeyError as exc:
            choices = ", ".join(sorted(self.runtime_variants))
            raise ValueError(f"unknown runtime variant {selected}; choose from {choices}") from exc


@dataclass(frozen=True)
class ProfileSet:
    profiles: tuple[Profile, ...]
    scalable_signed: frozenset[str]
    scalable_unsigned: frozenset[str]
    fixed_sizes: dict[str, int]

    def by_version(self, version: str) -> Profile:
        clean = version.removesuffix("-electron.0").split("-", 1)[0]
        for profile in self.profiles:
            if profile.version == clean:
                return profile
        raise ValueError(f"unsupported V8 version: {version}")

    def by_hash(self, value: int) -> Profile:
        for profile in self.profiles:
            if profile.version_hash == value:
                return profile
        raise ValueError(f"unknown V8 version hash: 0x{value:08x}; pass --version")


@lru_cache(maxsize=1)
def load_profiles() -> ProfileSet:
    directory = Path(__file__).with_name("profiles")
    raw = json.loads((directory / "index.json").read_text())
    profile_data = [
        json.loads((directory / f"{version}.json").read_text())
        for version in raw["versions"]
    ]
    profiles = tuple(
        Profile(
            version=item["version"],
            version_hash=item["version_hash"],
            register_file_start=item["register_file_start"],
            has_ro_snapshot_checksum=item["has_ro_snapshot_checksum"],
            snapshot_spaces=item["snapshot_spaces"],
            serializer_tags=item["serializer_tags"],
            bytecode_array_layout=BytecodeArrayLayout(**item["bytecode_array_layout"]),
            shared_function_info_layout=SharedFunctionInfoLayout(
                function_data_slots=tuple(
                    item["shared_function_info_layout"]["function_data_slots"]
                ),
                name_or_scope_info_slots=tuple(
                    item["shared_function_info_layout"]["name_or_scope_info_slots"]
                ),
            ),
            scope_info_layout=ScopeInfoLayout(**item["scope_info_layout"]),
            runtime_default_variant=item["runtime_default_variant"],
            runtime_variants={
                name: tuple(names) for name, names in item["runtime_variants"].items()
            },
            runtime_variant_by_flags_hash={
                int(value, 0): name
                for value, name in item["runtime_variant_by_flags_hash"].items()
            },
            intrinsic_names=tuple(item["intrinsic_names"]),
            root_names=tuple(item["root_names"]),
            root_strings={int(index): value for index, value in item["root_strings"].items()},
            read_only_strings={
                int(offset): value for offset, value in item["read_only_strings"].items()
            },
            static_root_maps={
                int(pointer): name
                for pointer, name in item["static_root_maps"].items()
            },
            static_root_area_start=item["static_root_area_start"],
            opcodes=tuple(
                Opcode(
                    entry["opcode"],
                    entry["name"],
                    tuple(entry["operands"]),
                    entry["jump_mode"],
                )
                for entry in item["bytecodes"]
            ),
        )
        for item in profile_data
    )
    encoding = raw["operand_encoding"]
    return ProfileSet(
        profiles=profiles,
        scalable_signed=frozenset(encoding["scalable_signed"]),
        scalable_unsigned=frozenset(encoding["scalable_unsigned"]),
        fixed_sizes=encoding["fixed_sizes"],
    )
