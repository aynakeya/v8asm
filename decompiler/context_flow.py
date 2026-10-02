"""Track context identities through register moves and control-flow joins."""

from collections import deque

from .instruction import Instruction
from .objects import V8ScopeInfo, V8Smi
from .utils import parse_jump_target


class ContextFlow:
    def __init__(self, context):
        self.context = context
        self.states = {}
        self.entries = {}

    def entry(self, bytecode):
        if bytecode.address in self.entries:
            return self.entries[bytecode.address]
        parent_address = self.context.function_parent.get(bytecode.address)
        if parent_address is not None:
            parent = self.context.get_object(parent_address)
            offset = self.context.function_creation_offsets[bytecode.address]
            chain = self.at(parent, offset).get("context", ())
        else:
            owner = self.context.get_function_for_bytecode(bytecode)
            scope = self.context.get_object(owner.scope_info.address) if owner and owner.scope_info else None
            chain = ()
            if isinstance(scope, V8ScopeInfo):
                if scope.scope_type == "SCRIPT_SCOPE":
                    chain = (scope.address,)
                seen = set(chain)
                while scope.outer_scope_info:
                    scope = self.context.get_object(scope.outer_scope_info.address)
                    if not isinstance(scope, V8ScopeInfo) or scope.address in seen:
                        break
                    seen.add(scope.address)
                    if scope.context_slot_names:
                        chain += (scope.address,)
        self.entries[bytecode.address] = chain
        return chain

    def at(self, bytecode, offset):
        if bytecode.address not in self.states:
            self._analyze(bytecode)
        return self.states[bytecode.address].get(offset, {})

    @staticmethod
    def token(value):
        return "context" if value in {"<context>", "context"} else value

    def _analyze(self, bytecode):
        instructions = [Instruction.from_codeline(line) for line in bytecode.instructions]
        states = {}
        self.states[bytecode.address] = states
        if not instructions:
            return
        by_offset = {item.offset: index for index, item in enumerate(instructions)}
        states[instructions[0].offset] = {"context": self.entry(bytecode)}
        pending = deque([instructions[0].offset])

        def merge(offset, state):
            if offset not in by_offset:
                return
            old = states.get(offset)
            joined = state if old is None else {
                key: value for key, value in old.items() if state.get(key) == value
            }
            if old != joined:
                states[offset] = dict(joined)
                pending.append(offset)

        while pending:
            offset = pending.popleft()
            index = by_offset[offset]
            item = instructions[index]
            before = states[offset]
            state = dict(before)
            op, args = item.mnemonic, item.args

            def assign(target, source):
                state.pop(target, None)
                if source in before:
                    state[target] = before[source]

            if op.startswith("Create") and op.endswith("Context"):
                scope = self.context.scope_for_instruction(bytecode, item)
                state.pop("ACCU", None)
                if scope is not None and "context" in before:
                    state["ACCU"] = (scope.address, *before["context"])
            elif op == "PushContext":
                assign(args[0], "context")
                assign("context", "ACCU")
            elif op == "PopContext":
                assign("context", args[0])
            elif op == "Mov":
                assign(args[1], self.token(args[0]))
            elif op == "Star" or (op.startswith("Star") and op[4:].isdigit()):
                assign(args[0] if op == "Star" else f"r{op[4:]}", "ACCU")
            elif op == "Ldar":
                assign("ACCU", self.token(args[0]))
            elif not op.startswith(("Sta", "Jump", "Switch", "Set", "Define")):
                state.pop("ACCU", None)

            target = parse_jump_target(item)
            if op in {"Jump", "JumpConstant", "JumpLoop", "JumpLoopConstant"}:
                merge(target, state)
            elif op not in {"Return", "Throw", "ReThrow", "Abort"}:
                if index + 1 < len(instructions):
                    merge(instructions[index + 1].offset, state)
                if op.startswith("JumpIf"):
                    merge(target, state)
                if op.startswith("SwitchOn"):
                    operand = 1 if op == "SwitchOnGeneratorState" else 0
                    start = self.context._bracket_index(args[operand])
                    count = self.context._bracket_index(args[operand + 1])
                    pool = self.context.constant_pool_entries(bytecode)
                    if start is not None and count is not None:
                        for entry in pool[start:start + count]:
                            if isinstance(entry.raw, V8Smi):
                                merge(offset + item.prefix_size + entry.raw.value, state)
            for handler in bytecode.handler_entries:
                if handler.start <= offset < handler.end:
                    caught = dict(before)
                    caught.pop("ACCU", None)
                    caught.pop("context", None)
                    if f"r{handler.data}" in before:
                        caught["context"] = before[f"r{handler.data}"]
                    merge(handler.handler, caught)
