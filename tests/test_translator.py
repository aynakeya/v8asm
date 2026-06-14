from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECOMPILER = ROOT / "decompiler"
if str(DECOMPILER) not in sys.path:
    sys.path.insert(0, str(DECOMPILER))

from context import ConstantPoolEntry, DecompilerContext
from instruction import Instruction
from objects.bytecode import CodeLine, V8BytecodeArray
from translator import InstructionTranslator


class TranslatorOpcodeTests(unittest.TestCase):
    def setUp(self) -> None:
        bytecode = V8BytecodeArray(0x1000, "BytecodeArray", [])
        context = DecompilerContext([])
        self.translator = InstructionTranslator(context, bytecode)
        self.translator.constants = {
            0: ConstantPoolEntry(0, None, '"^(\\\\w+):(\\\\d+)$"'),
            1: ConstantPoolEntry(1, None, '"value"'),
        }

    def translate(self, mnemonic: str, args: list[str]) -> str:
        return self.translator.translate(Instruction(0, mnemonic, args, "raw"))

    def test_create_regexp_literal_decodes_flags(self) -> None:
        self.assertEqual(
            self.translate("CreateRegExpLiteral", ["[0]", "[0]", "#16"]),
            'ACCU = new RegExp("^(\\\\w+):(\\\\d+)$", "u")',
        )

    def test_define_named_own_property(self) -> None:
        self.assertEqual(
            self.translate("DefineNamedOwnProperty", ["r2", "[1]", "[3]"]),
            "r2.value = ACCU",
        )

    def test_operand_scale_suffix_reuses_base_opcode_translation(self) -> None:
        wide = Instruction(0, "LdaSmi.Wide", ["[248]"], "raw")
        extra_wide = Instruction(0, "DivSmi.ExtraWide", ["[86400000]", "[10]"], "raw")
        parsed = Instruction.from_codeline(
            CodeLine.from_text(
                "0x1 @ 0 : 00 0d f8 00       LdaSmi.Wide [248]"
            )
        )

        self.assertEqual(wide.mnemonic, "LdaSmi")
        self.assertEqual(extra_wide.mnemonic, "DivSmi")
        self.assertEqual(parsed.mnemonic, "LdaSmi")
        self.assertEqual(self.translator.translate(wide), "ACCU = 248")
        self.assertEqual(
            self.translator.translate(extra_wide),
            "ACCU = (ACCU / 86400000)",
        )

    def test_define_keyed_own_property(self) -> None:
        self.assertEqual(
            self.translate("DefineKeyedOwnProperty", ["<this>", "r0", "#0", "[0]"]),
            "this[r0] = ACCU",
        )

    def test_set_keyed_property_uses_operand_key_and_accumulator_value(self) -> None:
        self.assertEqual(
            self.translate("SetKeyedProperty", ["<this>", "r3", "[0]"]),
            "this[r3] = ACCU",
        )

    def test_atom_high_frequency_opcodes_have_translations(self) -> None:
        cases = {
            ("CreateEmptyObjectLiteral", ()): "ACCU = {}",
            ("CreateEmptyArrayLiteral", ("[171]",)): "ACCU = []",
            ("TestEqual", ("r7", "[103]")): "ACCU = (r7 == ACCU)",
            ("ToBooleanLogicalNot", ()): "ACCU = !truthy(ACCU)",
            ("LdaContextSlot", ("r0", "[16]", "[0]")): "ACCU = context_slot(r0, 16, 0)",
            ("StaContextSlot", ("r0", "[16]", "[0]")): "context_slot(r0, 16, 0) = ACCU",
            ("CallProperty", ("r7", "r8-r10", "[212]")): "ACCU = r7.call(r8, r9, r10)",
            ("TestTypeOf", ("#1",)): 'ACCU = (typeof ACCU === "string")',
            ("JumpIfForInDone", ("[61]", "r6", "r5")): "if (ForInDone(r6, r5)) goto ?",
            ("BitwiseAndSmi.Wide", ("[128]", "[10]")): "ACCU = (ACCU & 128)",
            ("ShiftRight", ("a0", "[13]")): "ACCU = (arg0 >> ACCU)",
            ("TestUndefined", ()): "ACCU = (ACCU === undefined)",
            ("CreateMappedArguments", ()): "ACCU = arguments",
            ("ForInNext", ("r2", "r6", "r3-r4", "[2]")): "ACCU = ForInNext(r2, r6, r3, r4, [2])",
            (
                "GetEnumeratedKeyedProperty",
                ("a0", "r6", "r3", "[12]"),
            ): "ACCU = GetEnumeratedKeyedProperty(arg0, r6, r3)",
            ("ForInStep", ("r6",)): "r6 = ForInStep(r6)",
            ("JumpIfFalseConstant", ("[34]",)): "if (!ACCU) goto ?",
            ("JumpIfUndefinedConstant", ("[20]",)): "if (ACCU === undefined) goto ?",
            ("JumpIfNull", ("[72]",)): "if (ACCU === null) goto ?",
            ("JumpIfForInDoneConstant", ("[33]", "r14", "r13")): "if (ForInDone(r14, r13)) goto ?",
        }
        for (mnemonic, args), expected in cases.items():
            with self.subTest(mnemonic=mnemonic):
                self.assertEqual(self.translate(mnemonic, list(args)), expected)

    def test_jump_if_undefined_branch_condition(self) -> None:
        instr = Instruction(
            0,
            "JumpIfUndefined",
            ["[10]"],
            "0x1 @ 0 : a6 0a JumpIfUndefined [10] (0x1 @ 10)",
        )

        self.assertEqual(
            self.translator.branch_condition(instr),
            ("ACCU === undefined", True),
        )

    def test_async_generator_state_opcodes_do_not_fall_back_to_raw_lines(self) -> None:
        for mnemonic, args in (
            ("SwitchOnGeneratorState", ["r0", "[0]", "[2]"]),
            ("SwitchOnSmiNoFeedback", ["[3]", "[2]", "[0]"]),
            ("SuspendGenerator", ["r0", "r0-r3", "[1]"]),
            ("ResumeGenerator", ["r0", "r0-r3"]),
            ("Throw", []),
        ):
            translated = self.translate(mnemonic, args)
            self.assertNotIn("@", translated)
            self.assertNotIn("0x", translated)

    def test_create_rest_parameter_uses_user_parameter_count(self) -> None:
        self.translator.bytecode.parameter_count = 3

        self.assertEqual(
            self.translate("CreateRestParameter", []),
            "ACCU = Array.prototype.slice.call(arguments, 2)",
        )

    def test_call_with_spread_keeps_operand_receiver_until_propagation(self) -> None:
        self.assertEqual(
            self.translate("CallWithSpread", ["r3", "r4-r6", "[12]"]),
            "ACCU = r3.call(r4, r5, ...r6)",
        )

    def test_call_with_spread_formats_receiver_call(self) -> None:
        self.assertEqual(
            self.translate("CallWithSpread", ["r4", "r5-r6", "[21]"]),
            "ACCU = r4.call(r5, ...r6)",
        )

    def test_construct_with_spread_formats_last_argument_as_spread(self) -> None:
        self.assertEqual(
            self.translate("ConstructWithSpread", ["r3", "r0-r0", "[4]"]),
            "ACCU = new r3(...r0)",
        )


if __name__ == "__main__":
    unittest.main()
