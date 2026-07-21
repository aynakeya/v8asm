from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import json
import re
from typing import Any, Dict, Iterable, List, Optional

from .objects import (
    V8Address,
    V8ArrayBoilerplateDescription,
    V8BytecodeArray,
    V8FixedArray,
    V8HeapObject,
    V8ObjectBoilerplateDescription,
    V8ScopeInfo,
    V8SharedFunctionInfo,
    V8String,
    V8TrustedFixedArray,
    V8Smi,
)
from .instruction import Instruction
from .utils import parse_jump_target


IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
CONSTANT_INDEX_RE = re.compile(r"^\[(-?\d+)\]$")


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
        self.bytecode_scopes: Dict[int, List[V8ScopeInfo]] = {}
        self.function_children: Dict[int, List[V8BytecodeArray]] = {}
        self.function_parent: Dict[int, int] = {}
        self.function_names: Dict[int, str] = {}
        self.bytecode_parameter_names: Dict[int, Dict[int, str]] = {}
        self.bytecode_parameter_defaults: Dict[int, Dict[int, str]] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for idx, obj in enumerate(self.objects):
            if not isinstance(obj, V8BytecodeArray):
                continue
            if obj.constant_pool_address is not None:
                pool = self.by_address.get(obj.constant_pool_address)
                if isinstance(pool, V8TrustedFixedArray):
                    self.bytecode_constant_pools[obj.address] = pool
                    continue
            if obj.constant_pool_size:
                nxt = self.objects[idx + 1] if idx + 1 < len(self.objects) else None
                if (
                    isinstance(nxt, V8TrustedFixedArray)
                    and nxt.length == obj.constant_pool_size
                ):
                    self.bytecode_constant_pools[obj.address] = nxt

        for obj in self.objects:
            if isinstance(obj, V8SharedFunctionInfo) and obj.trusted_function_data:
                self.bytecode_functions[obj.trusted_function_data.address] = obj
                if obj.scope_info is not None:
                    scope = self.get_object(obj.scope_info.address)
                    if isinstance(scope, V8ScopeInfo):
                        self.bytecode_scopes.setdefault(
                            obj.trusted_function_data.address, []
                        ).append(scope)
        self._build_function_names()
        self._build_scope_and_closure_indexes()
        self._infer_parameter_names()
        self._infer_parameter_defaults()

    def _build_function_names(self) -> None:
        functions = [
            obj
            for obj in self.objects
            if isinstance(obj, V8SharedFunctionInfo)
            and obj.trusted_function_data is not None
        ]
        bases = [self._function_name_base(function) for function in functions]
        counts = Counter(bases)
        seen: Counter[str] = Counter()
        used: set[str] = set()
        for function, base in zip(functions, bases):
            seen[base] += 1
            candidate = (
                f"{base}_{seen[base]}" if counts[base] > 1 else base
            )
            suffix = 2
            unique = candidate
            while unique in used:
                unique = f"{candidate}_{suffix}"
                suffix += 1
            used.add(unique)
            self.function_names[function.address] = unique

    def _function_name_base(self, sfi: V8SharedFunctionInfo) -> str:
        raw_name = sfi.name_value
        if raw_name is None and sfi.name:
            target = self.get_object(sfi.name.address)
            if isinstance(target, V8String):
                raw_name = target.value
            elif sfi.name.desc not in {"<ReadOnlyObject>", "<RootObject>"}:
                raw_name = sfi.name.desc.strip("<>")
        if not raw_name or raw_name == "<anonymous>":
            return "anonymous"
        cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", raw_name.strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            return "anonymous"
        if cleaned[0].isdigit():
            cleaned = f"fn_{cleaned}"
        return cleaned if IDENT_RE.match(cleaned) else "anonymous"

    def _build_scope_and_closure_indexes(self) -> None:
        for obj in self.objects:
            if not isinstance(obj, V8BytecodeArray):
                continue
            instructions = [
                Instruction.from_codeline(line) for line in obj.instructions
            ]
            for instruction in instructions:
                constant_index = self._instruction_constant_index(instruction)
                if constant_index is None:
                    continue
                target = self._constant_target(obj, constant_index)
                if (
                    instruction.mnemonic
                    in {"CreateFunctionContext", "CreateBlockContext"}
                    and isinstance(target, V8ScopeInfo)
                ):
                    scopes = self.bytecode_scopes.setdefault(obj.address, [])
                    if target not in scopes:
                        scopes.append(target)
                elif (
                    instruction.mnemonic == "CreateClosure"
                    and isinstance(target, V8SharedFunctionInfo)
                    and target.trusted_function_data is not None
                ):
                    child = self.get_object(target.trusted_function_data.address)
                    if not isinstance(child, V8BytecodeArray) or child is obj:
                        continue
                    existing_parent = self.function_parent.get(child.address)
                    if existing_parent is not None and existing_parent != obj.address:
                        continue
                    self.function_parent[child.address] = obj.address
                    children = self.function_children.setdefault(obj.address, [])
                    if child not in children:
                        children.append(child)

    def _instruction_constant_index(self, instruction: Instruction) -> Optional[int]:
        if not instruction.args:
            return None
        match = CONSTANT_INDEX_RE.match(instruction.args[0].strip())
        return int(match.group(1)) if match else None

    def _constant_target(
        self, bytecode: V8BytecodeArray, index: int
    ) -> Optional[V8HeapObject]:
        pool = self.bytecode_constant_pools.get(bytecode.address)
        if pool is None or not 0 <= index < len(pool.elements):
            return None
        raw = pool.elements[index]
        if not isinstance(raw, V8Address):
            return None
        return self.get_object(raw.address)

    def _infer_parameter_names(self) -> None:
        storing = {
            "StaCurrentContextSlot",
            "StaCurrentScriptContextSlot",
        }
        for obj in self.objects:
            if not isinstance(obj, V8BytecodeArray):
                continue
            instructions = [
                Instruction.from_codeline(line) for line in obj.instructions
            ]
            names: Dict[int, str] = {}
            for load, store in zip(instructions, instructions[1:]):
                if load.mnemonic != "Ldar" or not load.args:
                    continue
                parameter = load.args[0].strip()
                if not parameter.startswith("a") or not parameter[1:].isdigit():
                    continue
                if store.mnemonic not in storing or not store.args:
                    continue
                slot = self._bracket_index(store.args[0])
                if slot is None:
                    continue
                name = self.context_slot_name(obj, slot, own_scope_only=True)
                if name and IDENT_RE.match(name):
                    names[int(parameter[1:])] = name
            if names:
                self.bytecode_parameter_names[obj.address] = names

    def _infer_parameter_defaults(self) -> None:
        conditional_jumps = {
            "JumpIfNotUndefined",
            "JumpIfNotUndefinedConstant",
        }
        unconditional_jumps = {"Jump", "JumpConstant"}
        for obj in self.objects:
            if not isinstance(obj, V8BytecodeArray):
                continue
            instructions = [
                Instruction.from_codeline(line) for line in obj.instructions
            ]
            defaults: Dict[int, str] = {}
            for index in range(len(instructions) - 5):
                load, branch, default_load, join, alternate, store = (
                    instructions[index : index + 6]
                )
                parameter_index = self._parameter_index(load)
                if parameter_index is None:
                    continue
                if branch.mnemonic not in conditional_jumps:
                    continue
                if join.mnemonic not in unconditional_jumps:
                    continue
                if self._parameter_index(alternate) != parameter_index:
                    continue
                if not store.mnemonic.startswith("Star"):
                    continue
                if parse_jump_target(branch) != alternate.offset:
                    continue
                if parse_jump_target(join) != store.offset:
                    continue
                default = self._literal_load(obj, default_load)
                if default is not None:
                    defaults.setdefault(parameter_index, default)
            if defaults:
                self.bytecode_parameter_defaults[obj.address] = defaults

    @staticmethod
    def _parameter_index(instruction: Instruction) -> Optional[int]:
        if instruction.mnemonic != "Ldar" or not instruction.args:
            return None
        parameter = instruction.args[0].strip()
        if not parameter.startswith("a") or not parameter[1:].isdigit():
            return None
        return int(parameter[1:])

    def _literal_load(
        self, bytecode: V8BytecodeArray, instruction: Instruction
    ) -> Optional[str]:
        literals = {
            "LdaZero": "0",
            "LdaUndefined": "undefined",
            "LdaNull": "null",
            "LdaTrue": "true",
            "LdaFalse": "false",
        }
        if instruction.mnemonic in literals:
            return literals[instruction.mnemonic]
        if instruction.mnemonic == "LdaSmi" and instruction.args:
            value = self._bracket_index(instruction.args[0])
            return str(value) if value is not None else None
        if instruction.mnemonic != "LdaConstant" or not instruction.args:
            return None
        constant_index = self._bracket_index(instruction.args[0])
        if constant_index is None:
            return None
        entries = self.constant_pool_entries(bytecode)
        if not 0 <= constant_index < len(entries):
            return None
        value = entries[constant_index].display
        if value in {"undefined", "null", "true", "false"}:
            return value
        if re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", value):
            return value
        if value.startswith('"') and value.endswith('"'):
            try:
                return value if isinstance(json.loads(value), str) else None
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _bracket_index(token: str) -> Optional[int]:
        match = CONSTANT_INDEX_RE.match(token.strip())
        return int(match.group(1)) if match else None

    def get_object(self, address: int) -> Optional[V8HeapObject]:
        return self.by_address.get(address)

    def get_function_for_bytecode(
        self, bytecode: V8BytecodeArray
    ) -> Optional[V8SharedFunctionInfo]:
        return self.bytecode_functions.get(bytecode.address)

    def get_function_name(self, sfi: V8SharedFunctionInfo) -> str:
        return self.function_names.get(sfi.address, self._function_name_base(sfi))

    def parameter_name(self, bytecode: V8BytecodeArray, index: int) -> str:
        return self.bytecode_parameter_names.get(bytecode.address, {}).get(
            index, f"arg{index}"
        )

    def parameter_declaration(self, bytecode: V8BytecodeArray, index: int) -> str:
        name = self.parameter_name(bytecode, index)
        default = self.bytecode_parameter_defaults.get(bytecode.address, {}).get(
            index
        )
        return f"{name} = {default}" if default is not None else name

    def child_functions(self, bytecode: V8BytecodeArray) -> List[V8BytecodeArray]:
        return list(self.function_children.get(bytecode.address, ()))

    def is_nested_function(self, bytecode: V8BytecodeArray) -> bool:
        return bytecode.address in self.function_parent

    def is_script(self, bytecode: V8BytecodeArray) -> bool:
        return any(
            scope.scope_type == "SCRIPT_SCOPE"
            for scope in self.bytecode_scopes.get(bytecode.address, ())
        )

    def script_context_names(self, bytecode: V8BytecodeArray) -> List[str]:
        names: List[str] = []
        for scope in self.bytecode_scopes.get(bytecode.address, ()):
            if scope.scope_type != "SCRIPT_SCOPE":
                continue
            for slot in sorted(scope.context_slot_names):
                name = self._scope_slot_name(scope, slot)
                if name and IDENT_RE.match(name) and name not in names:
                    names.append(name)
        return names

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
            if isinstance(target, V8ObjectBoilerplateDescription):
                return self._format_object_boilerplate(target)
            if isinstance(target, V8FixedArray):
                return self._format_fixed_array(target)
            if isinstance(target, V8BytecodeArray):
                owner = self.bytecode_functions.get(target.address)
                if owner:
                    return f"<bytecode {self.get_function_name(owner)}>"
                return f"<Bytecode 0x{target.address:012x}>"
            if isinstance(target, V8ScopeInfo):
                return self._format_scope_info(target)
            desc_value = self._format_address_desc(raw.desc)
            if desc_value is not None:
                return desc_value
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

    def _format_address_desc(self, desc: str) -> Optional[str]:
        text = desc.strip()
        if not text:
            return None
        if text.startswith("<") and text.endswith(">"):
            inner = text[1:-1]
        else:
            inner = text
        if inner in {"true", "false", "null", "undefined"}:
            return inner
        normalized = "".join(
            character for character in inner.lower() if character.isalpha()
        )
        if normalized == "uninitializedvalue":
            return "undefined"
        return None

    def _format_object_key(self, raw: Any) -> str:
        key = self.format_value(raw)
        if key.startswith('"') and key.endswith('"'):
            try:
                plain = json.loads(key)
            except json.JSONDecodeError:
                return key
            if plain.isidentifier():
                return plain
        return key

    def _format_object_boilerplate(
        self, boilerplate: V8ObjectBoilerplateDescription
    ) -> str:
        parts: List[str] = []
        entries = boilerplate.entries
        for idx in range(0, len(entries), 2):
            key = entries[idx]
            value = entries[idx + 1] if idx + 1 < len(entries) else None
            parts.append(f"{self._format_object_key(key)}: {self.format_value(value)}")
        return "{ " + ", ".join(parts) + " }"

    def _format_scope_info(self, scope: V8ScopeInfo) -> str:
        scope_type = scope.scope_type or "Scope"
        return f"<ScopeInfo {scope_type}>"

    def scope_context_name(self, raw: Any, index: int = 0) -> Optional[str]:
        if not isinstance(raw, V8Address):
            return None
        target = self.get_object(raw.address)
        if not isinstance(target, V8ScopeInfo):
            return None
        if index < 0 or index >= len(target.context_slots):
            return None
        name = self.format_value(target.context_slots[index])
        if name.startswith('"') and name.endswith('"'):
            try:
                return json.loads(name)
            except json.JSONDecodeError:
                return None
        slot = target.context_slots[index]
        if isinstance(slot, V8Address):
            match = re.search(r"#([^>]+)", slot.desc)
            if match:
                return match.group(1)
        return None

    def context_slot_name(
        self,
        bytecode: V8BytecodeArray,
        slot: int,
        depth: int = 0,
        *,
        own_scope_only: bool = False,
    ) -> Optional[str]:
        current: Optional[V8BytecodeArray] = bytecode
        scopes_to_skip = max(0, depth)
        while current is not None:
            scopes = self.bytecode_scopes.get(current.address, ())
            for scope in reversed(scopes):
                if scopes_to_skip:
                    scopes_to_skip -= 1
                    continue
                name = self._scope_slot_name(scope, slot)
                if name:
                    return name
            if own_scope_only:
                break
            parent_address = self.function_parent.get(current.address)
            parent = self.get_object(parent_address) if parent_address else None
            current = parent if isinstance(parent, V8BytecodeArray) else None
        return None

    def _scope_slot_name(self, scope: V8ScopeInfo, slot: int) -> Optional[str]:
        raw = scope.context_slot_names.get(slot)
        if raw is None:
            return None
        name = self.format_value(raw)
        if name.startswith('"') and name.endswith('"'):
            try:
                value = json.loads(name)
            except json.JSONDecodeError:
                return None
            return value if isinstance(value, str) else None
        if isinstance(raw, V8Address):
            match = re.search(r"#([^>]+)", raw.desc)
            if match:
                return match.group(1)
        return name if IDENT_RE.match(name) else None
