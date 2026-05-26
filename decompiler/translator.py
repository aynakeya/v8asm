from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from objects.bytecode import V8BytecodeArray

from context import ConstantPoolEntry, DecompilerContext
from instruction import Instruction
from utils import parse_jump_target

CONST_INDEX_RE = re.compile(r"^\[(\-?\d+)\]$")
RANGE_RE = re.compile(r"^([ra])(\d+)-([ra])(\d+)$")
IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

CONDITION_MAP: Dict[str, Tuple[str, bool]] = {
    "JumpIfTrue": ("truthy(ACCU)", True),
    "JumpIfFalse": ("truthy(ACCU)", False),
    "JumpIfToBooleanTrue": ("truthy(ACCU)", True),
    "JumpIfToBooleanFalse": ("truthy(ACCU)", False),
    "JumpIfToBooleanTrueConstant": ("truthy(ACCU)", True),
    "JumpIfToBooleanFalseConstant": ("truthy(ACCU)", False),
    "JumpIfUndefinedOrNull": ("isNullish(ACCU)", True),
    "JumpIfUndefinedOrNullConstant": ("isNullish(ACCU)", True),
    "JumpIfUndefined": ("ACCU === undefined", True),
    "JumpIfNotUndefined": ("ACCU !== undefined", True),
    "JumpIfJSReceiver": ("isJSReceiver(ACCU)", True),
    "JumpIfJSReceiverConstant": ("isJSReceiver(ACCU)", True),
}


def _parse_bracket_number(token: str) -> Optional[int]:
    m = CONST_INDEX_RE.match(token.strip())
    if not m:
        return None
    return int(m.group(1))


def _parse_number_token(token: str) -> Optional[int]:
    token = token.strip()
    bracket = _parse_bracket_number(token)
    if bracket is not None:
        return bracket
    if token.startswith("#") and token[1:].isdigit():
        return int(token[1:])
    if token.isdigit():
        return int(token)
    return None


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
            return self._display_to_expr(entry.display)
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

    def _identifier_from_literal(self, token: str) -> Optional[str]:
        token = token.strip()
        if len(token) < 2 or token[0] != '"' or token[-1] != '"':
            return None
        try:
            value = json.loads(token)
        except json.JSONDecodeError:
            return None
        if IDENT_RE.match(value):
            return value
        return None

    def _sanitize_identifier(self, token: str) -> Optional[str]:
        cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", token.strip())
        cleaned = re.sub(r"_+", "_", cleaned).strip("_")
        if not cleaned:
            return None
        if cleaned[0].isdigit():
            cleaned = f"fn_{cleaned}"
        if IDENT_RE.match(cleaned):
            return cleaned
        return None

    def _display_to_expr(self, display: str) -> str:
        token = display.strip()
        if not token:
            return "undefined"
        if token[0] in ('"', "'"):
            return token
        if token[0] in "[{":
            return token
        if token in {"true", "false", "null", "undefined", "HOLE"}:
            return token
        if re.fullmatch(r"[-+]?\d+", token):
            return token
        if IDENT_RE.match(token):
            return token
        sanitized = self._sanitize_identifier(token)
        if sanitized:
            return sanitized
        return json.dumps(token)

    def _format_property_access(self, obj_token: str, prop_token: str) -> str:
        obj = self._reg_name(obj_token)
        prop = self._const_token(prop_token)
        ident = self._identifier_from_literal(prop)
        if ident:
            return f"{obj}.{ident}"
        return f"{obj}[{prop}]"

    def _format_global_access(self, token: str) -> str:
        name = self._const_token(token)
        ident = self._identifier_from_literal(name)
        if ident:
            return ident
        return f"globalThis[{name}]"

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

    def _format_spread_args(self, args: List[str]) -> List[str]:
        if not args:
            return []
        fixed = [self._reg_name(arg) for arg in args[:-1]]
        return fixed + [f"...{self._reg_name(args[-1])}"]

    def _imm(self, token: str, fallback: str = "?") -> str:
        value = _parse_bracket_number(token)
        if value is None:
            return fallback if token is None else token
        return str(value)

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
        if const_repr.startswith("["):
            return f"ACCU = {const_repr}"
        return f"ACCU = create_array_literal({const_repr}) /* depth={depth}, flags={flags} */"

    def _op_CreateObjectLiteral(self, instr: Instruction) -> str:
        if len(instr.args) < 1:
            return "ACCU = create_object_literal({})"
        const_repr = self._const_token(instr.args[0])
        flags = self._imm(instr.args[1], "[0]") if len(instr.args) > 1 else "0"
        slot = instr.args[2] if len(instr.args) > 2 else "#0"
        if const_repr.startswith("{"):
            return f"ACCU = {const_repr}"
        return f"ACCU = create_object_literal({const_repr}) /* flags={flags}, slot={slot} */"

    def _op_CreateRegExpLiteral(self, instr: Instruction) -> str:
        if len(instr.args) < 1:
            return "ACCU = new RegExp(\"\")"
        pattern = self._const_token(instr.args[0])
        flags_value = _parse_number_token(instr.args[2]) if len(instr.args) > 2 else None
        flags = self._regexp_flags(flags_value)
        return f"ACCU = new RegExp({pattern}, {json.dumps(flags)})"

    def _op_CreateRestParameter(self, instr: Instruction) -> str:
        user_param_count = max(0, (self.bytecode.parameter_count or 1) - 1)
        return f"ACCU = Array.prototype.slice.call(arguments, {user_param_count})"

    def _op_CreateBlockContext(self, instr: Instruction) -> str:
        scope = self._const_token(instr.args[0]) if instr.args else "<ScopeInfo>"
        return f"ACCU = create_block_context({scope})"

    def _op_LdaGlobal(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = globalThis[undefined]"
        return f"ACCU = {self._format_global_access(instr.args[0])}"

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
        return "ACCU = HOLE"

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
        return f"ACCU = {self._format_property_access(args[0], args[1])}"

    def _op_GetKeyedProperty(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 2)
        if not args:
            return "ACCU = <keyed-property>"
        receiver = self._reg_name(args[0])
        return f"ACCU = {receiver}[ACCU]"

    def _op_SetNamedProperty(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "<named-property> = ACCU"
        return f"{self._format_property_access(args[0], args[1])} = ACCU"

    def _op_SetKeyedProperty(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "<keyed-property> = ACCU"
        receiver = self._reg_name(args[0])
        key = self._reg_name(args[1])
        return f"{receiver}[{key}] = ACCU"

    def _op_DefineNamedOwnProperty(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "<own-property> = ACCU"
        return f"{self._format_property_access(args[0], args[1])} = ACCU"

    def _op_DefineKeyedOwnProperty(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 4)
        if len(args) < 2:
            return "<own-keyed-property> = ACCU"
        receiver = self._reg_name(args[0])
        key = self._reg_name(args[1])
        return f"{receiver}[{key}] = ACCU"

    def _op_StaInArrayLiteral(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "<array-literal>[?] = ACCU"
        receiver = self._reg_name(args[0])
        index = self._reg_name(args[1])
        return f"{receiver}[{index}] = ACCU"

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

    def _op_InvokeIntrinsic(self, instr: Instruction) -> str:
        return self._op_CallRuntime(instr)

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

    def _op_CallUndefinedReceiver(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if not args:
            return "ACCU = call(undefined)"
        callee = self._reg_name(args[0])
        call_args = self._expand_range(args[1]) if len(args) > 1 else []
        return self._format_call(callee, call_args)

    def _op_CallWithSpread(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if not args:
            return "ACCU = callWithSpread(?)"
        callee = self._reg_name(args[0])
        call_args = self._expand_range(args[1]) if len(args) > 1 else []
        receiver = call_args[0] if call_args else "undefined"
        spread_args = self._format_spread_args(call_args[1:])
        arg_text = ", ".join(spread_args)
        if receiver == "undefined":
            return f"ACCU = {callee}({arg_text})"
        method_args = ", ".join([receiver] + spread_args)
        return f"ACCU = {callee}.call({method_args})"

    def _op_CallProperty0(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if len(args) < 2:
            return "ACCU = callProperty(?, receiver=?)"
        callee = self._reg_name(args[0])
        receiver = self._reg_name(args[1])
        return f"ACCU = {callee}.call({receiver})"

    def _op_CallProperty2(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 5)
        if len(args) < 4:
            return "ACCU = callProperty(?, receiver=?, ...)"
        callee = self._reg_name(args[0])
        receiver = self._reg_name(args[1])
        arg1 = self._reg_name(args[2])
        arg2 = self._reg_name(args[3])
        return f"ACCU = {callee}.call({receiver}, {arg1}, {arg2})"

    def _op_CallProperty1(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 4)
        if len(args) < 3:
            return "ACCU = callProperty(?, receiver=?, ?)"
        callee = self._reg_name(args[0])
        receiver = self._reg_name(args[1])
        arg1 = self._reg_name(args[2])
        return f"ACCU = {callee}.call({receiver}, {arg1})"

    def _op_Construct(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if not args:
            return "ACCU = new <constructor>()"
        callee = self._reg_name(args[0])
        call_args = self._expand_range(args[1]) if len(args) > 1 else []
        arg_text = ", ".join(call_args)
        return f"ACCU = new {callee}({arg_text})"

    def _op_ConstructWithSpread(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 3)
        if not args:
            return "ACCU = new <constructor>(...?)"
        callee = self._reg_name(args[0])
        call_args = self._expand_range(args[1]) if len(args) > 1 else []
        arg_text = ", ".join(self._format_spread_args(call_args))
        return f"ACCU = new {callee}({arg_text})"

    def _op_Add(self, instr: Instruction) -> str:
        args = self._drop_feedback(instr.args, 1)
        if not args:
            return "ACCU = ACCU + ?"
        left = self._reg_name(args[0])
        return f"ACCU = ({left} + ACCU)"

    def _op_AddSmi(self, instr: Instruction) -> str:
        value = _parse_bracket_number(instr.args[0]) if instr.args else None
        return f"ACCU = (ACCU + {value})"

    def _op_Inc(self, instr: Instruction) -> str:
        return "ACCU = (ACCU + 1)"

    def _op_SubSmi(self, instr: Instruction) -> str:
        value = _parse_bracket_number(instr.args[0]) if instr.args else None
        return f"ACCU = (ACCU - {value})"

    def _op_MulSmi(self, instr: Instruction) -> str:
        value = _parse_bracket_number(instr.args[0]) if instr.args else None
        return f"ACCU = (ACCU * {value})"

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

    def _op_JumpIfUndefined(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (ACCU === undefined) goto ?"
        return f"if (ACCU === undefined) goto offset_{target}"

    def _op_JumpIfNotUndefined(self, instr: Instruction) -> str:
        target = self._find_target(instr)
        if target is None:
            return "if (ACCU !== undefined) goto ?"
        return f"if (ACCU !== undefined) goto offset_{target}"

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

    def _op_SwitchOnGeneratorState(self, instr: Instruction) -> str:
        generator = self._reg_name(instr.args[0]) if instr.args else "generator"
        return f"// SwitchOnGeneratorState {generator}"

    def _op_SuspendGenerator(self, instr: Instruction) -> str:
        generator = self._reg_name(instr.args[0]) if instr.args else "generator"
        state = self._imm(instr.args[-1], "?") if instr.args else "?"
        return f"// SuspendGenerator {generator}, state={state}"

    def _op_ResumeGenerator(self, instr: Instruction) -> str:
        generator = self._reg_name(instr.args[0]) if instr.args else "generator"
        return f"ACCU = ResumeGenerator({generator})"

    def _op_SwitchOnSmiNoFeedback(self, instr: Instruction) -> str:
        args = ", ".join(instr.args)
        suffix = f" {args}" if args else ""
        return f"// SwitchOnSmiNoFeedback ACCU{suffix}"

    def _op_LdaGlobalInsideTypeofIC(self, instr: Instruction) -> str:
        return self._op_LdaGlobal(instr)

    def _find_target(self, instr: Instruction) -> Optional[int]:
        return parse_jump_target(instr)

    def _op_CreateClosure(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = create_closure(<anonymous>)"
        callee = self._const_token(instr.args[0])
        return f"ACCU = create_closure({callee})"

    def _op_PushContext(self, instr: Instruction) -> str:
        dest = self._reg_name(instr.args[0]) if instr.args else "context"
        return f"{dest} = pushContext(ACCU)"

    def _op_PopContext(self, instr: Instruction) -> str:
        source = self._reg_name(instr.args[0]) if instr.args else "context"
        return f"context = {source}"

    def _op_CreateFunctionContext(self, instr: Instruction) -> str:
        scope = self._const_token(instr.args[0]) if instr.args else "<ScopeInfo>"
        slots = self._imm(instr.args[1], "?") if len(instr.args) > 1 else "?"
        return f"ACCU = create_function_context({scope}, {slots})"

    def _op_CreateCatchContext(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = create_catch_context(ACCU, <ScopeInfo>)"
        exc = self._reg_name(instr.args[0])
        scope = self._const_token(instr.args[1]) if len(instr.args) > 1 else "<ScopeInfo>"
        return f"ACCU = create_catch_context({exc}, {scope})"

    def _op_TestReferenceEqual(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = (ACCU === ?)"
        ref = self._reg_name(instr.args[0])
        return f"ACCU = ({ref} === ACCU)"

    def _op_TestEqualStrict(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = (ACCU === ?)"
        ref = self._reg_name(instr.args[0])
        return f"ACCU = ({ref} === ACCU)"

    def _op_TestGreaterThan(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = (ACCU > ?)"
        ref = self._reg_name(instr.args[0])
        return f"ACCU = ({ref} > ACCU)"

    def _op_TestLessThan(self, instr: Instruction) -> str:
        if not instr.args:
            return "ACCU = (ACCU < ?)"
        ref = self._reg_name(instr.args[0])
        return f"ACCU = ({ref} < ACCU)"

    def _op_SetPendingMessage(self, instr: Instruction) -> str:
        return "// SetPendingMessage"

    def _op_ReThrow(self, instr: Instruction) -> str:
        return "throw ACCU"

    def _op_Throw(self, instr: Instruction) -> str:
        return "throw ACCU"

    def _op_ThrowReferenceErrorIfHole(self, instr: Instruction) -> str:
        if not instr.args:
            return "// ThrowReferenceErrorIfHole"
        idx = _parse_bracket_number(instr.args[0])
        target = self._const(idx) if idx is not None else instr.args[0]
        return f"ensureDefined({target})"

    def _op_ToString(self, instr: Instruction) -> str:
        return "ACCU = String(ACCU)"

    def _regexp_flags(self, value: Optional[int]) -> str:
        if value is None:
            return ""
        flags = []
        for bit, flag in (
            (1, "g"),
            (2, "i"),
            (4, "m"),
            (8, "s"),
            (16, "u"),
            (32, "y"),
            (64, "d"),
            (128, "v"),
        ):
            if value & bit:
                flags.append(flag)
        return "".join(flags)
