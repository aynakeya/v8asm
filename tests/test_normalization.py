from __future__ import annotations

from types import SimpleNamespace
import unittest

from decompiler.instruction import Instruction
from decompiler.normalization import (
    find_default_parameter_initializers,
    normalize_source_instructions,
)
from decompiler.objects import V8BytecodeArray, V8Smi
from decompiler.objects.bytecode import HandlerEntry


def instruction(
    offset: int,
    mnemonic: str,
    *args: str,
    jump_target: int | None = None,
) -> Instruction:
    return Instruction(offset, mnemonic, list(args), "", jump_target)


class FakeContext:
    def __init__(
        self,
        initializers=(),
        constant='"value"',
        scope=None,
        initialized=(),
    ) -> None:
        self.initializers = list(initializers)
        self.constant = constant
        self.scope = scope
        self.initialized = frozenset(initialized)

    def parameter_initializers(self, _bytecode):
        return list(self.initializers)

    def context_slot_name(self, _bytecode, slot, depth=0):
        return "value" if (slot, depth) == (2, 0) else None

    def context_slot_binding(self, _bytecode, slot, depth=0, *, offset=None):
        if (slot, depth) == (2, 0):
            return SimpleNamespace(name="value", defining_bytecode_address=0x1000)
        return None

    def prologue_initialized_names(self, _address):
        return self.initialized

    def constant_pool_entries(self, _bytecode):
        return [SimpleNamespace(display=self.constant)]

    def child_functions(self, _bytecode):
        return []

    def is_nested_function(self, _bytecode):
        return False

    def get_object(self, _address):
        return None

    def constant_object_for_instruction(self, _bytecode, _instruction):
        return None

    def scope_for_instruction(self, _bytecode, _instruction):
        return self.scope

    def scope_slot_name(self, scope, slot):
        return scope.context_slot_names.get(slot)

    def parameter_name(self, _bytecode, index):
        return f"arg{index}"

    def literal_load(self, _bytecode, item):
        return "0" if item.mnemonic == "LdaZero" else None


class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bytecode = V8BytecodeArray(0x1000, "BytecodeArray", [])
        self.default_sequence = [
            instruction(0, "Ldar", "a0"),
            instruction(
                2,
                "JumpIfNotUndefined",
                "[5]",
                jump_target=7,
            ),
            instruction(4, "LdaZero"),
            instruction(5, "Jump", "[4]", jump_target=9),
            instruction(7, "Ldar", "a0"),
            instruction(9, "Star0"),
        ]

    def test_default_parameter_requires_matching_control_flow(self) -> None:
        initializers = find_default_parameter_initializers(
            self.default_sequence,
            lambda item: "0" if item.mnemonic == "LdaZero" else None,
        )
        self.assertEqual(len(initializers), 1)
        self.assertEqual(initializers[0].parameter_index, 0)
        self.assertEqual(initializers[0].value, "0")

        mismatched = list(self.default_sequence)
        mismatched[1] = instruction(
            2,
            "JumpIfNotUndefined",
            "[6]",
            jump_target=8,
        )
        self.assertEqual(
            find_default_parameter_initializers(
                mismatched,
                lambda item: "0" if item.mnemonic == "LdaZero" else None,
            ),
            [],
        )

    def test_default_initializer_is_lowered_to_parameter_register_copy(self) -> None:
        initializers = find_default_parameter_initializers(
            self.default_sequence,
            lambda item: "0" if item.mnemonic == "LdaZero" else None,
        )
        normalized = normalize_source_instructions(
            FakeContext(initializers), self.bytecode, self.default_sequence
        )
        self.assertEqual(
            [item.mnemonic for item in normalized.instructions],
            ["Ldar", "Star0"],
        )
        self.assertEqual(normalized.instructions[0].args, ["a0"])

    def test_hole_check_requires_initialization_proof(self) -> None:
        instructions = [
            instruction(0, "LdaCurrentContextSlot", "[2]"),
            instruction(2, "ThrowReferenceErrorIfHole", "[0]"),
            instruction(4, "Return"),
        ]
        normalized = normalize_source_instructions(
            FakeContext(initialized={"value"}), self.bytecode, instructions
        )
        self.assertEqual(
            [item.mnemonic for item in normalized.instructions],
            ["LdaCurrentContextSlot", "Return"],
        )

        for context in (FakeContext(), FakeContext(constant='"other"', initialized={"value"})):
            with self.subTest(context=context):
                normalized = normalize_source_instructions(context, self.bytecode, instructions)
                self.assertEqual(normalized.instructions, instructions)

    def test_global_typeof_cannot_absorb_other_entry_points(self) -> None:
        class SwitchContext(FakeContext):
            def constant_pool_entries(self, _bytecode):
                return [SimpleNamespace(raw=V8Smi(4), display="4")]

        pair = [instruction(2, "LdaGlobalInsideTypeof", "[0]", "[0]"), instruction(4, "TypeOf", "[2]")]
        for predecessor in (
            instruction(0, "Jump", "[4]", jump_target=4),
            instruction(0, "SwitchOnSmiNoFeedback", "[0]", "[1]", "[0]"),
            instruction(0, "SwitchOnGeneratorState", "r0", "[0]", "[1]"),
        ):
            with self.subTest(predecessor=predecessor.mnemonic):
                with self.assertRaisesRegex(ValueError, "single-entry"):
                    normalize_source_instructions(SwitchContext(), self.bytecode, [predecessor, *pair])

        self.bytecode.handler_entries = [HandlerEntry(2, 4, 9, 0, 0)]
        with self.assertRaisesRegex(ValueError, "single-entry"):
            normalize_source_instructions(FakeContext(), self.bytecode, pair)

        self.bytecode.handler_entries = []
        normalized = normalize_source_instructions(FakeContext(), self.bytecode, pair)
        self.assertEqual([item.mnemonic for item in normalized.instructions], ["TypeOfGlobal"])

    def test_parameter_body_context_becomes_initialized_lexical_declaration(
        self,
    ) -> None:
        initializers = find_default_parameter_initializers(
            self.default_sequence,
            lambda item: "0" if item.mnemonic == "LdaZero" else None,
        )
        scope = SimpleNamespace(
            scope_type="BLOCK_SCOPE",
            context_slot_names={2: "value"},
        )
        instructions = self.default_sequence + [
            instruction(10, "CreateBlockContext", "[0]"),
            instruction(12, "PushContext", "r1"),
            instruction(14, "LdaTheHole"),
            instruction(15, "StaCurrentContextSlot", "[2]"),
            instruction(17, "Ldar", "r0"),
            instruction(19, "StaCurrentContextSlot", "[2]"),
            instruction(21, "Return"),
        ]
        normalized = normalize_source_instructions(
            FakeContext(initializers, scope=scope),
            self.bytecode,
            instructions,
        )
        self.assertEqual(
            [item.mnemonic for item in normalized.instructions],
            ["Ldar", "Star0", "Return"],
        )
        self.assertEqual(len(normalized.lexical_declarations), 1)
        declaration = normalized.lexical_declarations[0]
        self.assertEqual((declaration.name, declaration.initializer), ("value", "arg0"))

    def test_function_context_local_is_distinct_from_parameter(self) -> None:
        scope = SimpleNamespace(
            address=0x2000,
            scope_type="FUNCTION_SCOPE",
            context_slot_names={2: "value"},
        )
        instructions = [
            instruction(0, "CreateFunctionContext", "[0]", "[1]"),
            instruction(3, "PushContext", "r0"),
            instruction(5, "LdaTheHole"),
            instruction(6, "StaCurrentContextSlot", "[2]"),
            instruction(8, "Ldar", "a0"),
            instruction(10, "StaCurrentContextSlot", "[2]"),
            instruction(12, "LdaCurrentContextSlot", "[2]"),
            instruction(14, "Return"),
        ]
        normalized = normalize_source_instructions(
            FakeContext(scope=scope), self.bytecode, instructions
        )

        self.assertEqual(
            [item.mnemonic for item in normalized.instructions],
            ["LdaCurrentContextSlot", "Return"],
        )
        self.assertEqual(len(normalized.lexical_declarations), 1)
        declaration = normalized.lexical_declarations[0]
        self.assertEqual((declaration.name, declaration.initializer), ("value", "arg0"))


if __name__ == "__main__":
    unittest.main()
