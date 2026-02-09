from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, List, Optional

from objects import (
    V8Address,
    V8ArrayBoilerplateDescription,
    V8BytecodeArray,
    V8FixedArray,
    V8HeapObject,
    V8SharedFunctionInfo,
    V8String,
    V8TrustedFixedArray,
    V8Smi,
)


@dataclass
class ConstantPoolEntry:
    index: int
    raw: Any
    display: str


class DecompilerContext:
    """Holds cross-object metadata used during decompilation."""

    def __init__(self, objects: Iterable[V8HeapObject]):
        self.objects: List[V8HeapObject] = list(objects)
        self.by_address: Dict[int, V8HeapObject] = {
            obj.address: obj for obj in self.objects
        }
        self.bytecode_constant_pools: Dict[int, V8TrustedFixedArray] = {}
        self.bytecode_functions: Dict[int, V8SharedFunctionInfo] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for idx, obj in enumerate(self.objects):
            if isinstance(obj, V8BytecodeArray) and obj.constant_pool_size:
                nxt = self.objects[idx + 1] if idx + 1 < len(self.objects) else None
                if (
                    isinstance(nxt, V8TrustedFixedArray)
                    and nxt.length == obj.constant_pool_size
                ):
                    self.bytecode_constant_pools[obj.address] = nxt

        for obj in self.objects:
            if isinstance(obj, V8SharedFunctionInfo) and obj.trusted_function_data:
                self.bytecode_functions[obj.trusted_function_data.address] = obj

    def get_object(self, address: int) -> Optional[V8HeapObject]:
        return self.by_address.get(address)

    def get_function_for_bytecode(
        self, bytecode: V8BytecodeArray
    ) -> Optional[V8SharedFunctionInfo]:
        return self.bytecode_functions.get(bytecode.address)

    def get_function_name(self, sfi: V8SharedFunctionInfo) -> str:
        if sfi.name:
            ref = self.get_object(sfi.name.address)
            if isinstance(ref, V8String):
                return ref.value or "<anonymous>"
            if sfi.name.desc:
                return sfi.name.desc.strip("<>")
        return f"0x{sfi.address:012x}"

    def constant_pool_entries(self, bytecode: V8BytecodeArray) -> List[ConstantPoolEntry]:
        pool = self.bytecode_constant_pools.get(bytecode.address)
        if not pool or not pool.elements:
            return []

        entries: List[ConstantPoolEntry] = []
        for idx, raw in enumerate(pool.elements):
            entries.append(ConstantPoolEntry(idx, raw, self.format_value(raw)))
        return entries

    def format_value(self, raw: Any) -> str:
        if isinstance(raw, V8Smi):
            return str(raw.value)

        if isinstance(raw, V8Address):
            target = self.get_object(raw.address)
            if isinstance(target, V8String):
                return json.dumps(target.value)
            if isinstance(target, V8SharedFunctionInfo):
                return self.get_function_name(target)
            if isinstance(target, V8ArrayBoilerplateDescription):
                return self._format_array_boilerplate(target)
            if isinstance(target, V8FixedArray):
                return self._format_fixed_array(target)
            if isinstance(target, V8BytecodeArray):
                owner = self.bytecode_functions.get(target.address)
                if owner:
                    return f"<bytecode {self.get_function_name(owner)}>"
                return f"<Bytecode 0x{target.address:012x}>"
            if target:
                return json.dumps(f"<{target.i_type} 0x{target.address:012x}>")
            return json.dumps(raw.desc or f"0x{raw.address:012x}")

        if isinstance(raw, str):
            return json.dumps(raw)

        if raw is None:
            return "undefined"

        return str(raw)

    def _format_fixed_array(self, arr: V8FixedArray) -> str:
        parts = [self.format_value(el) for el in arr.elements]
        return "[" + ", ".join(parts) + "]"

    def _format_array_boilerplate(
        self, boilerplate: V8ArrayBoilerplateDescription
    ) -> str:
        if not boilerplate.constant_elements:
            return f"<ArrayBoilerplate {boilerplate.elements_kind}>"

        const = self.get_object(boilerplate.constant_elements.address)
        if isinstance(const, V8FixedArray):
            return self._format_fixed_array(const)
        return f"<ArrayBoilerplate {boilerplate.elements_kind}>"
