from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import json
import re
from typing import Any, Dict, Iterable, List, Optional

from .objects import (
    V8Address,
    V8BytecodeArray,
    V8HeapObject,
    V8ScopeInfo,
    V8SharedFunctionInfo,
    V8String,
    V8TrustedFixedArray,
    V8Smi,
)
from .instruction import Instruction
from .context_flow import ContextFlow
from .normalization import (
    lifted_body_scopes,
    DefaultParameterInitializer,
    LexicalDeclaration,
    find_default_parameter_initializers,
    prologue_initialized_names,
)
from .value_formatter import ValueFormatter


IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
RESERVED_WORDS = frozenset("""
await break case catch class const continue debugger default delete do else enum
export extends false finally for function if implements import in instanceof
interface let new null package private protected public return static super switch
this throw true try typeof var void while with yield
""".split())
CONSTANT_INDEX_RE = re.compile(r"^\[(-?\d+)\]$")


@dataclass
class ConstantPoolEntry:
    index: int
    raw: Any
    display: str


@dataclass(frozen=True)
class ContextBinding:
    name: str
    slot: int
    scope_address: int
    defining_bytecode_address: int
    definition_offset: Optional[int]


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
        self.scope_owners: Dict[int, int] = {}
        self.function_children: Dict[int, List[V8BytecodeArray]] = {}
        self.function_parent: Dict[int, int] = {}
        self.function_creation_offsets: Dict[int, int] = {}
        self.function_names: Dict[int, str] = {}
        self.context_bindings: Dict[tuple[int, int], ContextBinding] = {}
        self.lifted_scopes: set[int] = set()
        self.bytecode_initialized_names: Dict[int, frozenset[str]] = {}
        self.bytecode_parameter_names: Dict[int, Dict[int, str]] = {}
        self.bytecode_parameter_defaults: Dict[int, Dict[int, str]] = {}
        self.bytecode_parameter_initializers: Dict[
            int, List[DefaultParameterInitializer]
        ] = {}
        self._value_formatter = ValueFormatter(self)
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
                        self.scope_owners.setdefault(
                            scope.address, obj.trusted_function_data.address
                        )
        self._build_function_names()
        self._build_scope_and_closure_indexes()
        self.context_flow = ContextFlow(self)
        self._build_context_bindings()
        self._infer_parameter_names()
        self._infer_parameter_defaults()
        for obj in self.objects:
            if isinstance(obj, V8BytecodeArray):
                self.lifted_scopes.update(lifted_body_scopes(self, obj))

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
        lexical_names = {
            name for scope in self.objects if isinstance(scope, V8ScopeInfo)
            for slot in scope.context_slot_names
            if (name := self._scope_slot_name(scope, slot)) is not None
        }
        for function, base in zip(functions, bases):
            seen[base] += 1
            candidate = (
                f"{base}_{seen[base]}" if counts[base] > 1 else base
            )
            suffix = 2
            unique = candidate
            # Method temporaries are synthetic bindings, not source declarations.
            is_method = function.func_kind in {"ConciseMethod", "GetterFunction", "SetterFunction"}
            while unique in used or (is_method and unique in lexical_names):
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
        if cleaned[0].isdigit() or cleaned in RESERVED_WORDS:
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
                constant_index = self._scope_constant_index(instruction)
                if constant_index is not None:
                    target = self._constant_target(obj, constant_index)
                    if isinstance(target, V8ScopeInfo):
                        scopes = self.bytecode_scopes.setdefault(obj.address, [])
                        if target not in scopes:
                            scopes.append(target)
                        self.scope_owners.setdefault(target.address, obj.address)

                constant_index = self._instruction_constant_index(instruction)
                if constant_index is None:
                    continue
                target = self._constant_target(obj, constant_index)
                if (
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
                    self.function_creation_offsets[child.address] = instruction.offset
                    children = self.function_children.setdefault(obj.address, [])
                    if child not in children:
                        children.append(child)

    def _scope_constant_index(
        self, instruction: Instruction
    ) -> Optional[int]:
        scope_arg = {
            "CreateBlockContext": 0,
            "CreateCatchContext": 1,
            "CreateClassContext": 0,
            "CreateFunctionContext": 0,
            "CreateWithContext": 1,
        }.get(instruction.mnemonic)
        if scope_arg is None or len(instruction.args) <= scope_arg:
            return None
        return self._bracket_index(instruction.args[scope_arg])

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

    def _build_context_bindings(self) -> None:
        used_names: Dict[int, Counter[str]] = {}
        for bytecode_address, scopes in self.bytecode_scopes.items():
            bytecode = self.get_object(bytecode_address)
            if not isinstance(bytecode, V8BytecodeArray):
                continue
            owner_names = used_names.setdefault(bytecode_address, Counter())
            for scope in scopes:
                for slot in sorted(scope.context_slot_names):
                    strict_name = self._scope_slot_name(scope, slot)
                    base = strict_name or (
                        f"context_{scope.address:012x}_{slot}"
                    )
                    owner_names[base] += 1
                    name = (
                        base
                        if owner_names[base] == 1
                        else f"{base}_scope_{scope.address:012x}"
                    )
                    self.context_bindings[(scope.address, slot)] = ContextBinding(
                        name=name,
                        slot=slot,
                        scope_address=scope.address,
                        defining_bytecode_address=bytecode_address,
                        definition_offset=self._context_definition_offset(
                            bytecode, slot, scope.address
                        ),
                    )

    def _context_definition_offset(
        self, bytecode: V8BytecodeArray, slot: int, scope_address: int
    ) -> Optional[int]:
        instructions = [
            Instruction.from_codeline(line) for line in bytecode.instructions
        ]
        stores = {
            "StaCurrentContextSlot",
            "StaCurrentScriptContextSlot",
        }
        for index, instruction in enumerate(instructions):
            if (
                instruction.mnemonic not in stores
                or not instruction.args
                or self._bracket_index(instruction.args[0]) != slot
                or self.context_flow.at(bytecode, instruction.offset).get("context", ())[:1] != (scope_address,)
            ):
                continue
            previous = instructions[index - 1] if index else None
            if previous is not None and previous.mnemonic == "LdaTheHole":
                continue
            return instruction.offset
        return None

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
            lexical_slots = {
                (self.context_flow.at(obj, store.offset).get("context", ())[:1], slot)
                for load, store in zip(instructions, instructions[1:])
                if load.mnemonic == "LdaTheHole"
                and store.mnemonic in storing
                and store.args
                and (slot := self._bracket_index(store.args[0])) is not None
            }
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
                chain = self.context_flow.at(obj, store.offset).get("context", ())
                if slot is None or (chain[:1], slot) in lexical_slots:
                    continue
                name = self.context_slot_name(obj, slot, offset=store.offset)
                if name and IDENT_RE.match(name):
                    names[int(parameter[1:])] = name
            if names:
                self.bytecode_parameter_names[obj.address] = names

    def _infer_parameter_defaults(self) -> None:
        for obj in self.objects:
            if not isinstance(obj, V8BytecodeArray):
                continue
            instructions = [
                Instruction.from_codeline(line) for line in obj.instructions
            ]
            initializers = find_default_parameter_initializers(
                instructions,
                lambda instruction: self._literal_load(obj, instruction),
            )
            if not initializers:
                continue
            self.bytecode_parameter_initializers[obj.address] = initializers
            self.bytecode_parameter_defaults[obj.address] = {
                initializer.parameter_index: initializer.value
                for initializer in initializers
            }

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

    def parameter_initializers(
        self, bytecode: V8BytecodeArray
    ) -> List[DefaultParameterInitializer]:
        return list(self.bytecode_parameter_initializers.get(bytecode.address, ()))

    def literal_load(
        self, bytecode: V8BytecodeArray, instruction: Instruction
    ) -> Optional[str]:
        return self._literal_load(bytecode, instruction)

    def prologue_initialized_names(self, bytecode_address: int) -> frozenset[str]:
        if bytecode_address not in self.bytecode_initialized_names:
            bytecode = self.get_object(bytecode_address)
            self.bytecode_initialized_names[bytecode_address] = prologue_initialized_names(self, bytecode)
        return self.bytecode_initialized_names[bytecode_address]

    def scope_for_instruction(
        self, bytecode: V8BytecodeArray, instruction: Instruction
    ) -> Optional[V8ScopeInfo]:
        constant_index = self._scope_constant_index(instruction)
        if constant_index is None:
            return None
        target = self._constant_target(bytecode, constant_index)
        return target if isinstance(target, V8ScopeInfo) else None

    def constant_object_for_instruction(
        self, bytecode: V8BytecodeArray, instruction: Instruction
    ) -> Optional[V8HeapObject]:
        constant_index = self._instruction_constant_index(instruction)
        if constant_index is None:
            return None
        return self._constant_target(bytecode, constant_index)

    def scope_slot_name(self, scope: V8ScopeInfo, slot: int) -> Optional[str]:
        binding = self.context_bindings.get((scope.address, slot))
        return binding.name if binding is not None else self._scope_slot_name(scope, slot)

    def child_functions(self, bytecode: V8BytecodeArray) -> List[V8BytecodeArray]:
        return list(self.function_children.get(bytecode.address, ()))

    def is_nested_function(self, bytecode: V8BytecodeArray) -> bool:
        return bytecode.address in self.function_parent

    def is_script(self, bytecode: V8BytecodeArray) -> bool:
        return any(
            scope.scope_type == "SCRIPT_SCOPE"
            for scope in self.bytecode_scopes.get(bytecode.address, ())
        )

    def script_context_declarations(self, bytecode: V8BytecodeArray) -> List[LexicalDeclaration]:
        declarations: List[LexicalDeclaration] = []
        for scope in self.bytecode_scopes.get(bytecode.address, ()):
            if scope.scope_type != "SCRIPT_SCOPE":
                continue
            for slot in sorted(scope.context_slot_names):
                name = self.scope_slot_name(scope, slot)
                if name and IDENT_RE.match(name):
                    needs_initialization = scope.context_slot_initialization.get(slot)
                    initializer = (
                        "HOLE" if needs_initialization else "undefined"
                    ) if needs_initialization is not None else f"unresolved_initialization({json.dumps(name)})"
                    declaration = LexicalDeclaration(name, initializer)
                    if declaration not in declarations:
                        declarations.append(declaration)
        return declarations

    def constant_pool_entries(self, bytecode: V8BytecodeArray) -> List[ConstantPoolEntry]:
        pool = self.bytecode_constant_pools.get(bytecode.address)
        if not pool or not pool.elements:
            return []

        entries: List[ConstantPoolEntry] = []
        for idx, raw in enumerate(pool.elements):
            entries.append(ConstantPoolEntry(idx, raw, self.format_value(raw)))
        return entries

    def format_value(self, raw: Any) -> str:
        return self._value_formatter.format(raw)

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
        offset: int | None = None,
        context_register: str = "context",
    ) -> Optional[str]:
        binding = self.context_slot_binding(
            bytecode,
            slot,
            depth,
            own_scope_only=own_scope_only,
            offset=offset,
            context_register=context_register,
        )
        if binding and self.uses_scope_cell(binding.scope_address):
            return f"{self.scope_variable(binding.scope_address)}.{binding.name}"
        return binding.name if binding is not None else None

    def context_slot_binding(
        self,
        bytecode: V8BytecodeArray,
        slot: int,
        depth: int = 0,
        *,
        own_scope_only: bool = False,
        offset: int | None = None,
        context_register: str = "context",
    ) -> Optional[ContextBinding]:
        if offset is not None:
            chain = self.context_flow.at(bytecode, offset).get(
                self.context_flow.token(context_register), ()
            )
            if 0 <= depth < len(chain):
                return self.context_bindings.get((chain[depth], slot))
            return None
        scopes = self._context_scope_chain(
            bytecode, own_scope_only=own_scope_only
        )
        if depth < 0 or depth >= len(scopes):
            return None
        return self.context_bindings.get((scopes[depth].address, slot))

    def uses_scope_cell(self, address: int) -> bool:
        scope = self.get_object(address)
        return (isinstance(scope, V8ScopeInfo) and bool(scope.context_slot_names)
                and address not in self.lifted_scopes
                and scope.scope_type in {"BLOCK_SCOPE", "CATCH_SCOPE", "CLASS_SCOPE"})

    @staticmethod
    def scope_variable(address: int) -> str:
        return f"scope_{address:x}"

    def closure_scope_variables(self, bytecode: V8BytecodeArray) -> List[str]:
        return [self.scope_variable(address) for address in self.context_flow.entry(bytecode)
                if self.uses_scope_cell(address)]

    def _context_scope_chain(
        self,
        bytecode: V8BytecodeArray,
        *,
        own_scope_only: bool = False,
    ) -> List[V8ScopeInfo]:
        chain: List[V8ScopeInfo] = []
        current: Optional[V8BytecodeArray] = bytecode
        while current is not None:
            scopes = [
                scope
                for scope in self.bytecode_scopes.get(current.address, ())
                if scope.context_slot_names
            ]
            chain.extend(reversed(scopes))
            if own_scope_only:
                break
            parent_address = self.function_parent.get(current.address)
            parent = self.get_object(parent_address) if parent_address else None
            if parent is None:
                function = self.get_function_for_bytecode(current)
                scope = self.get_object(function.scope_info.address) if function and function.scope_info else None
                seen = {item.address for item in chain}
                while isinstance(scope, V8ScopeInfo) and scope.outer_scope_info:
                    scope = self.get_object(scope.outer_scope_info.address)
                    if not isinstance(scope, V8ScopeInfo) or scope.address in seen:
                        break
                    seen.add(scope.address)
                    if scope.context_slot_names:
                        chain.append(scope)
            current = parent if isinstance(parent, V8BytecodeArray) else None
        return chain

    def captured_context_bindings(
        self, bytecode: V8BytecodeArray
    ) -> List[ContextBinding]:
        found: Dict[tuple[int, int], ContextBinding] = {}
        current_ops = {
            "LdaCurrentContextSlot",
            "LdaCurrentScriptContextSlot",
            "LdaImmutableCurrentContextSlot",
            "StaCurrentContextSlot",
            "StaCurrentScriptContextSlot",
        }
        depth_ops = {
            "LdaContextSlot",
            "LdaImmutableContextSlot",
            "StaContextSlot",
        }
        for raw in bytecode.instructions:
            instruction = Instruction.from_codeline(raw)
            slot: Optional[int] = None
            depth = 0
            if instruction.mnemonic in current_ops and instruction.args:
                slot = self._bracket_index(instruction.args[0])
            elif (
                instruction.mnemonic in depth_ops
                and len(instruction.args) >= 3
                and instruction.args[0].strip() in {"<context>", "context"}
            ):
                slot = self._bracket_index(instruction.args[1])
                parsed_depth = self._bracket_index(instruction.args[2])
                if parsed_depth is None:
                    continue
                depth = parsed_depth
            if slot is None:
                continue
            binding = self.context_slot_binding(bytecode, slot, depth, offset=instruction.offset)
            if (
                binding is not None
                and binding.defining_bytecode_address != bytecode.address
            ):
                found[(binding.scope_address, binding.slot)] = binding
        return list(found.values())

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
            return (
                value
                if isinstance(value, str) and IDENT_RE.match(value)
                else None
            )
        if isinstance(raw, V8Address):
            match = re.search(r"#([^>]+)", raw.desc)
            if match:
                return match.group(1)
        return name if IDENT_RE.match(name) else None
