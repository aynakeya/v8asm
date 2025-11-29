from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from objects.bytecode import V8BytecodeArray

from context import ConstantPoolEntry, DecompilerContext
from instruction import Instruction
from utils import parse_jump_target

CONST_INDEX_RE = re.compile(r"^\[(\-?\d+)\]$")
RANGE_RE = re.compile(r"^([ra])(\d+)-([ra])(\d+)$")

CONDITION_MAP: Dict[str, Tuple[str, bool]] = {
    "JumpIfTrue": ("truthy(ACCU)", True),
    "JumpIfFalse": ("truthy(ACCU)", False),
    "JumpIfToBooleanTrue": ("truthy(ACCU)", True),
    "JumpIfToBooleanFalse": ("truthy(ACCU)", False),
    "JumpIfToBooleanTrueConstant": ("truthy(ACCU)", True),
    "JumpIfToBooleanFalseConstant": ("truthy(ACCU)", False),
    "JumpIfUndefinedOrNull": ("isNullish(ACCU)", True),
    "JumpIfUndefinedOrNullConstant": ("isNullish(ACCU)", True),
    "JumpIfJSReceiver": ("isJSReceiver(ACCU)", True),
    "JumpIfJSReceiverConstant": ("isJSReceiver(ACCU)", True),
}


def _parse_bracket_number(token: str) -> Optional[int]:
    m = CONST_INDEX_RE.match(token.strip())
    if not m:
        return None
    return int(m.group(1))


class InstructionTranslator:
    def __init__(self, context: DecompilerContext, bytecode: V8BytecodeArray):
        self.context = context
        self.bytecode = bytecode
        self.constants: Dict[int, ConstantPoolEntry] = {
            entry.index: entry for entry in context.constant_pool_entries(bytecode)
        }

    def translate(self, instr: Instruction) -> str:
        handler = getattr(self, f"_op_{instr.mnemonic}", None)
        if handler:
            return handler(instr)

        if instr.mnemonic.startswith("Star") and instr.mnemonic[4:].isdigit():
            reg_id = int(instr.mnemonic[4:])
            return f"{self._reg_name(f'r{reg_id}')} = ACCU"

        if instr.mnemonic == "Star" and instr.args:
            return f"{self._reg_name(instr.args[0])} = ACCU"

        if instr.mnemonic.startswith("Ldar") and instr.mnemonic[4:].isdigit():
            reg_id = int(instr.mnemonic[4:])
            return f"ACCU = {self._reg_name(f'r{reg_id}')}"

        return f"// {instr.raw_line.strip()}"

    def branch_condition(self, instr: Instruction) -> Optional[Tuple[str, bool]]:
        info = CONDITION_MAP.get(instr.mnemonic)
        if not info:
            return None
        return info

    def fallthrough_condition(self, instr: Instruction) -> Optional[str]:
        info = self.branch_condition(instr)
        if not info:
            return None
        expr, branch_on_true = info
        if branch_on_true:
            return f"!({expr})"
        return expr

    def _const(self, idx: int) -> str:
        entry = self.constants.get(idx)
        if entry:
            return entry.display
        return f"Const[{idx}]"

    def _const_token(self, token: str) -> str:
        idx = _parse_bracket_number(token)
        if idx is None:
            return token
        return self._const(idx)

    def _reg_name(self, token: str) -> str:
        token = token.strip()
        if token.startswith("<") and token.endswith(">"):
            inner = token.strip("<>")
            if not inner:
                return token
            return inner.replace(" ", "_")
        if token.startswith("a") and token[1:].isdigit():
            return f"arg{int(token[1:])}"
        if token.startswith("r") and token[1:].isdigit():
            return token
        if token.startswith("CASE_"):
            return token
        return token

    def _expand_range(self, token: str) -> List[str]:
        token = token.strip()
        match = RANGE_RE.match(token)
        if not match:
            return [self._reg_name(token)]
        prefix, start, prefix2, end = match.groups()
        if prefix != prefix2:
            return [self._reg_name(token)]
        start_idx, end_idx = int(start), int(end)
        step = 1 if end_idx >= start_idx else -1
        result = []
        for i in range(start_idx, end_idx + step, step):
            result.append(self._reg_name(f"{prefix}{i}"))
        return result

    def _drop_feedback(self, args: List[str], expected: int) -> List[str]:
        if len(args) >= expected and _parse_bracket_number(args[-1]) is not None:
            return args[:-1]
        return args

    def _format_call(self, callee: str, args: List[str]) -> str:
        arg_text = ", ".join(self._reg_name(arg) for arg in args)
        return f"ACCU = {self._reg_name(callee)}({arg_text})"

    def _op_LdaConstant(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = Const[?]"
        idx = _parse_bracket_number(instr.args[0])
        if idx is None:
            return f"ACCU = {instr.args[0]}"
        return f"ACCU = {self._const(idx)}"

    def _op_CreateArrayLiteral(self, instr: Instruction) -> str:
        if len(instr.args) < 1:
            return "ACCU = create_array_literal(?)"
        const_repr = self._const_token(instr.args[0])
        depth = instr.args[1] if len(instr.args) > 1 else "[0]"
        flags = instr.args[2] if len(instr.args) > 2 else "#0"
        return f"ACCU = create_array_literal({const_repr}, depth={depth}, flags={flags})"

    def _op_LdaGlobal(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = global[?]"
        name = self._const_token(instr.args[0])
        return f"ACCU = global[{name}]"

    def _op_LdaGlobalInsideTypeof(self, instr: Instruction) -> str:
        return self._op_LdaGlobal(instr)

    def _op_LdaGlobalNoFeedback(self, instr: Instruction) -> str:
        return self._op_LdaGlobal(instr)

    def _op_LdaImmutableCurrentContextSlot(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = context_slot[?]"
        idx = _parse_bracket_number(instr.args[0]) or 0
        return f"ACCU = context_slot[{idx}]"

    def _op_LdaCurrentContextSlot(self, instr: Instruction) -> str:
        return self._op_LdaImmutableCurrentContextSlot(instr)

    def _op_LdaImmutableContextSlot(self, instr: Instruction) -> str:
        return self._op_LdaImmutableCurrentContextSlot(instr)

    def _op_LdaCurrentScriptContextSlot(self, instr: Instruction) -> str:
        return self._op_LdaImmutableCurrentContextSlot(instr)

    def _op_LdaZero(self, instr: Instruction) -> str:
        return "ACCU = 0"

    def _op_LdaUndefined(self, instr: Instruction) -> str:
        return "ACCU = undefined"

    def _op_LdaTrue(self, instr: Instruction) -> str:
        return "ACCU = true"

    def _op_LdaFalse(self, instr: Instruction) -> str:
        return "ACCU = false"

    def _op_LdaNull(self, instr: Instruction) -> str:
        return "ACCU = null"

    def _op_LdaTheHole(self, instr: Instruction) -> str:
        return "ACCU = <hole>"

    def _op_LdaSmi(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = 0"
        val = _parse_bracket_number(instr.args[0])
        return f"ACCU = {val if val is not None else instr.args[0]}"

    def _op_Ldar(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = ACCU"
        return f"ACCU = {self._reg_name(instr.args[0])}"

    def _op_StaCurrentScriptContextSlot(self, instr: Instruction) -> str:
        if not instr.args:
            return "script_context[?] = ACCU"
        idx = _parse_bracket_number(instr.args[0]) or 0
        return f"script_context[{idx}] = ACCU"

    def _op_StaCurrentContextSlot(self, instr: Instruction) -> str:
        return self._op_StaCurrentScriptContextSlot(instr)

    def _op_GetNamedProperty(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 2)
        if len(args) < 2:
            return "ACCU = <named-property>"
        obj = self._reg_name(args[0])
        prop = self._const_token(args[1])
        return f"ACCU = {obj}[{prop}]"

    def _op_GetIterator(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = GetIterator(?)"
        source = self._reg_name(instr.args[0])
        return f"ACCU = GetIterator({source})"

    def _op_CallRuntime(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = CallRuntime(?)"
        runtime_name = instr.args[0].strip("[]")
        arg_regs: List[str] = []
        if len(instr.args) > 1:
            arg_regs = self._expand_range(instr.args[1])
        arg_text = ", ".join(arg_regs)
        return f"ACCU = {runtime_name}({arg_text})"

    def _op_CallUndefinedReceiver0(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 2)
        callee = self._reg_name(args[0]) if args else "func"
        return f"ACCU = {callee}()"

    def _op_CallUndefinedReceiver1(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "ACCU = call(undefined, ?)"
        callee = self._reg_name(args[0])
        arg = self._reg_name(args[1])
        return f"ACCU = {callee}({arg})"

    def _op_CallUndefinedReceiver2(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 4)
        if len(args) < 3:
            return "ACCU = call(undefined, ?, ?)"
        callee = self._reg_name(args[0])
        arg1 = self._reg_name(args[1])
        arg2 = self._reg_name(args[2])
        return f"ACCU = {callee}({arg1}, {arg2})"

    def _op_CallProperty0(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "ACCU = callProperty(?, receiver=?)"
        callee = self._reg_name(args[0])
        receiver = self._reg_name(args[1])
        return f"ACCU = callProperty({callee}, receiver={receiver})"

    def _op_CallProperty2(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 5)
        if len(args) < 4:
            return "ACCU = callProperty(?, receiver=?, ...)"
        callee = self._reg_name(args[0])
        receiver = self._reg_name(args[1])
        arg1 = self._reg_name(args[2])
        arg2 = self._reg_name(args[3])
        return (
            f"ACCU = callProperty({callee}, receiver={receiver}, args=[{arg1}, {arg2}])"
        )

    def _op_Add(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 1)
        if not args:
            return "ACCU = ACCU + ?"
        left = self._reg_name(args[0])
        return f"ACCU = ({left} + ACCU)"

    def _op_AddSmi(self, instr: Instruction) -> str:
        value = _parse_bracket_number(instr.args[0]) if instr.args else None
        return f"ACCU = (ACCU + {value})"

    def _op_Mov(self, instr: Instruction) -> str:
        if len(instr.args) < 2:
            return "ACCU = ACCU"
        src = self._reg_name(instr.args[0])
        dest = self._reg_name(instr.args[1])
        return f"{dest} = {src}"

    def _op_Return(self, instr: Instruction) -> str:
        return "return ACCU"

    def _op_Jump(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "// jump ?"
        return f"goto offset_{target}"

    def _op_JumpLoop(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "// jump_loop ?"
        return f"loop goto offset_{target}"

    def _op_JumpIfToBooleanTrue(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (ACCU) goto ?"
        return f"if (truthy(ACCU)) goto offset_{target}"

    def _op_JumpIfToBooleanFalse(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (!ACCU) goto ?"
        return f"if (!truthy(ACCU)) goto offset_{target}"

    def _op_JumpIfTrue(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (ACCU) goto ?"
        return f"if (ACCU) goto offset_{target}"

    def _op_JumpIfFalse(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (!ACCU) goto ?"
        return f"if (!ACCU) goto offset_{target}"

    def _op_JumpIfUndefinedOrNull(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (ACCU == nullish) goto ?"
        return f"if (ACCU == null || ACCU == undefined) goto offset_{target}"

    def _op_JumpIfJSReceiver(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (isJSReceiver(ACCU)) goto ?"
        return f"if (isJSReceiver(ACCU)) goto offset_{target}"

    def _op_JumpIfToBooleanTrueConstant(self, instr: Instruction) -> str:
        return self._op_JumpIfToBooleanTrue(instr)

    def _op_JumpIfToBooleanFalseConstant(self, instr: Instruction) -> str:
        return self._op_JumpIfToBooleanFalse(instr)

    def _op_JumpIfJSReceiverConstant(self, instr: Instruction) -> str:
        return self._op_JumpIfJSReceiver(instr)

    def _op_JumpIfUndefinedOrNullConstant(self, instr: Instruction) -> str:
        return self._op_JumpIfUndefinedOrNull(instr)

    def _op_LdaGlobalInsideTypeofIC(self, instr: Instruction) -> str:
        return self._op_LdaGlobal(instr)

    def _find_target(self, instr: Instruction) -> Optional[int]:
        return parse_jump_target(instr)

    def _op_TestReferenceEqual(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = (ACCU === ?)"
        ref = self._reg_name(instr.args[0])
        return f"ACCU = ({ref} === ACCU)"

    def _op_SetPendingMessage(self, instr: Instruction) -> str:
        return "// SetPendingMessage"

    def _op_ReThrow(self, instr: Instruction) -> str:
        return "throw ACCU"

    def _op_ThrowReferenceErrorIfHole(self, instr: Instruction) -> str:
        if not instr.args:
            return "// ThrowReferenceErrorIfHole"
        idx = _parse_bracket_number(instr.args[0])
        target = self._const(idx) if idx is not None else instr.args[0]
        return f"ensureDefined({target})"
