from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import List, Optional

from objects import V8Address
from objects.bytecode import V8BytecodeArray

from context import DecompilerContext
from instruction import Instruction
from parser import parse_objects
from postprocess import simplify_lines
from postprocess_file import postprocess_level4_file
from structurer import decompile_to_statements
from translator import InstructionTranslator
from utils import parse_jump_target

IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
INDENT = "  "


def _format_params(bytecode: V8BytecodeArray) -> str:
    count = bytecode.parameter_count or 0
    user_params = max(0, count - 1)
    return ", ".join(f"arg{i}" for i in range(user_params))


def _format_constant_pool(ctx: DecompilerContext, bytecode: V8BytecodeArray) -> List[str]:
    entries = ctx.constant_pool_entries(bytecode)
    if not entries:
        return []
    lines = ["  // Constant pool:"]
    for entry in entries:
        lines.append(f"  //   [{entry.index}] = {entry.display}")
    return lines


def _sanitize_identifier(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_$]", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return fallback
    if not IDENT_RE.match(cleaned):
        if cleaned[0].isdigit():
            cleaned = f"fn_{cleaned}"
        if not IDENT_RE.match(cleaned):
            return fallback
    return cleaned


def _format_register_locals(bytecode: V8BytecodeArray) -> List[str]:
    lines = ["  let ACCU = undefined;"]
    reg_count = bytecode.register_count or 0
    if reg_count <= 0:
        return lines
    regs = ", ".join(f"r{i}" for i in range(reg_count))
    lines.append(f"  let {regs};")
    return lines


def _runtime_prelude() -> str:
    return """const HOLE = Symbol("hole");
const __v8ctx = { slots: [] };
const context_slot = __v8ctx.slots;
const script_context = __v8ctx.slots;
let context = null;
let closure = undefined;

function truthy(v) { return !!v; }
function isNullish(v) { return v === null || v === undefined; }
function isJSReceiver(v) {
  const t = typeof v;
  return (t === "object" && v !== null) || t === "function";
}
function create_array_literal(v) { return Array.isArray(v) ? v.slice() : []; }
function create_object_literal(v) { return v && typeof v === "object" ? { ...v } : {}; }
function create_closure(fn) { return typeof fn === "function" ? fn : function () { return undefined; }; }
function create_function_context(scope, slots) { return { scope, slots: new Array(Number(slots) || 0) }; }
function create_block_context(scope) { return { scope, slots: [] }; }
function create_catch_context(value, scope) { return { value, scope, slots: [value] }; }
function pushContext(v) {
  const prev = context;
  context = v;
  return prev;
}
function GetIterator(v) { return v[Symbol.iterator](); }
function DeclareGlobals() { return undefined; }
function ensureDefined(name) {
  if (!(name in globalThis) && context_slot[name] === HOLE) {
    throw new ReferenceError(String(name));
  }
}
function ThrowIteratorResultNotAnObject(v) {
  throw new TypeError("Iterator result is not an object: " + String(v));
}
function _CopyDataPropertiesWithExcludedPropertiesOnStack(source, ...keys) {
  const out = {};
  for (const key of Object.keys(Object(source))) {
    if (!keys.includes(key)) out[key] = source[key];
  }
  return out;
}
"""


def render_level1(translator: InstructionTranslator, instructions: List[Instruction]) -> List[str]:
    lines: List[str] = []
    for instr in instructions:
        translated = translator.translate(instr)
        offset = instr.offset if instr.offset >= 0 else -1
        lines.append(f"  [{offset:4d}] {translated}")
    return lines


def render_level2(translator: InstructionTranslator, instructions: List[Instruction]) -> List[str]:
    statements = decompile_to_statements(translator, instructions)
    lines: List[str] = []
    for stmt in statements:
        lines.extend(stmt.render(1))
    return lines


def render_level3(translator: InstructionTranslator, instructions: List[Instruction]) -> List[str]:
    return simplify_lines(render_level2(translator, instructions), recover_structures=False)


def _render_level4_fragment(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[str]:
    return simplify_lines(render_level2(translator, instructions), recover_structures=True)


def _indent_lines(lines: List[str]) -> List[str]:
    return [f"{INDENT}{line}" if line else line for line in lines]


def _instruction_index_at_or_after(
    instructions: List[Instruction], offset: int
) -> Optional[int]:
    for idx, instr in enumerate(instructions):
        if instr.offset >= offset:
            return idx
    return None


def _accu_load_expr(translator: InstructionTranslator, instr: Instruction) -> Optional[str]:
    text = translator.translate(instr).strip()
    match = re.match(r"^ACCU\s*=\s*(.+)$", text)
    if not match:
        return None
    expr = match.group(1).strip()
    if "ACCU" in expr:
        return None
    return expr


def _branch_path_condition(
    translator: InstructionTranslator,
    branch: Instruction,
    *,
    branch_taken: bool,
) -> Optional[str]:
    info = translator.branch_condition(branch)
    if not info:
        return None
    expr, branch_on_true = info
    if branch_taken == branch_on_true:
        return expr
    return f"!({expr})"


def _condition_with_load(condition: str, expr: str) -> Optional[str]:
    if not condition or not expr or "ACCU" in expr:
        return None
    return re.sub(r"\bACCU\b", expr, condition)


def _match_short_circuit_try_alternate(
    translator: InstructionTranslator,
    instructions: List[Instruction],
    prefix_instrs: List[Instruction],
    guarded_entry_offset: int,
    suffix_start_idx: Optional[int],
) -> Optional[tuple[List[Instruction], str, List[Instruction], List[Instruction]]]:
    if suffix_start_idx is None or suffix_start_idx >= len(instructions):
        return None
    if len(prefix_instrs) < 4:
        return None

    first_load, first_jump, second_load, second_jump = prefix_instrs[-4:]
    if parse_jump_target(first_jump) != guarded_entry_offset:
        return None
    alternate_offset = parse_jump_target(second_jump)
    if alternate_offset is None:
        return None

    after_try_jump = instructions[suffix_start_idx]
    if after_try_jump.mnemonic not in {"Jump", "JumpConstant"}:
        return None
    final_offset = parse_jump_target(after_try_jump)
    if final_offset is None:
        return None

    alternate_start_idx = _instruction_index_at_or_after(instructions, alternate_offset)
    final_suffix_idx = _instruction_index_at_or_after(instructions, final_offset)
    if (
        alternate_start_idx is None
        or final_suffix_idx is None
        or not (suffix_start_idx < alternate_start_idx < final_suffix_idx)
    ):
        return None

    first_expr = _accu_load_expr(translator, first_load)
    second_expr = _accu_load_expr(translator, second_load)
    first_condition = _branch_path_condition(
        translator, first_jump, branch_taken=True
    )
    second_condition = _branch_path_condition(
        translator, second_jump, branch_taken=False
    )
    if (
        first_expr is None
        or second_expr is None
        or first_condition is None
        or second_condition is None
    ):
        return None

    first_condition = _condition_with_load(first_condition, first_expr)
    second_condition = _condition_with_load(second_condition, second_expr)
    if first_condition is None or second_condition is None:
        return None

    setup_instrs = prefix_instrs[:-4]
    alternate_instrs = instructions[alternate_start_idx:final_suffix_idx]
    final_suffix_instrs = instructions[final_suffix_idx:]
    return (
        setup_instrs,
        f"{first_condition} || {second_condition}",
        alternate_instrs,
        final_suffix_instrs,
    )


def _catch_binding_name(
    ctx: DecompilerContext,
    translator: InstructionTranslator,
    instr: Instruction,
) -> str:
    if len(instr.args) < 2:
        return "e"
    token = instr.args[1].strip()
    if not (token.startswith("[") and token.endswith("]")):
        return "e"
    try:
        idx = int(token[1:-1])
    except ValueError:
        return "e"
    entry = translator.constants.get(idx)
    if not entry or not isinstance(entry.raw, V8Address):
        return "e"
    name = ctx.scope_context_name(entry.raw)
    if name and IDENT_RE.match(name):
        return name
    if name:
        match = re.search(r"#([^>]+)", name)
        if match and IDENT_RE.match(match.group(1)):
            return match.group(1)
    return name or "e"


def _render_single_try_catch(
    ctx: DecompilerContext,
    translator: InstructionTranslator,
    instructions: List[Instruction],
    entry,
) -> Optional[List[str]]:
    try_start_idx = _instruction_index_at_or_after(instructions, entry.start)
    try_end_idx = _instruction_index_at_or_after(instructions, entry.end)
    handler_idx = _instruction_index_at_or_after(instructions, entry.handler)
    if try_start_idx is None or try_end_idx is None or handler_idx is None:
        return None

    prefix_end_idx = try_start_idx
    if try_start_idx > 0:
        scaffold = instructions[try_start_idx - 1]
        if (
            scaffold.mnemonic == "Mov"
            and scaffold.args
            and scaffold.args[0] == "<context>"
        ):
            prefix_end_idx = try_start_idx - 1

    skip_jump_idx = (
        try_end_idx
        if try_end_idx < len(instructions)
        and instructions[try_end_idx].mnemonic in {"Jump", "JumpConstant"}
        else None
    )
    resume_offset = (
        parse_jump_target(instructions[skip_jump_idx]) if skip_jump_idx is not None else None
    )
    suffix_start_idx = (
        _instruction_index_at_or_after(instructions, resume_offset)
        if resume_offset is not None
        else len(instructions)
    )

    try_instrs = instructions[try_start_idx:try_end_idx]
    if not try_instrs:
        return None
    if skip_jump_idx is None and try_instrs[-1].mnemonic != "Return":
        return None
    catch_instrs = instructions[
        handler_idx : suffix_start_idx if suffix_start_idx is not None else len(instructions)
    ]
    if not try_instrs or not catch_instrs:
        return None

    push_idx = next(
        (idx for idx, instr in enumerate(catch_instrs) if instr.mnemonic == "PushContext"),
        None,
    )
    if push_idx is None:
        return None
    pop_idx = next(
        (
            idx
            for idx, instr in enumerate(catch_instrs[push_idx + 1 :], start=push_idx + 1)
            if instr.mnemonic == "PopContext"
        ),
        None,
    )
    catch_body_instrs = catch_instrs[push_idx + 1 : pop_idx if pop_idx is not None else len(catch_instrs)]
    if not catch_body_instrs:
        return None

    prefix_instrs = instructions[:prefix_end_idx]
    suffix_instrs = instructions[suffix_start_idx:] if suffix_start_idx is not None else []
    guard_condition: Optional[str] = None
    prefix_lines: Optional[List[str]] = None
    if prefix_instrs and resume_offset is not None:
        guard = prefix_instrs[-1]
        guarded_prefix_offsets = {instr.offset for instr in prefix_instrs[:-1]}
        guard_is_branch_target = any(
            parse_jump_target(instr) == guard.offset for instr in prefix_instrs[:-1]
        )
        prefix_has_external_jump = any(
            (target := parse_jump_target(instr)) is not None
            and target not in guarded_prefix_offsets
            for instr in prefix_instrs[:-1]
        )
        if (
            not guard_is_branch_target
            and not prefix_has_external_jump
            and guard.mnemonic.startswith("JumpIf")
            and parse_jump_target(guard) == resume_offset
        ):
            guard_condition = translator.fallthrough_condition(guard)
            if guard_condition:
                prefix_instrs = prefix_instrs[:-1]
                if "ACCU" in guard_condition and prefix_instrs:
                    last_prefix_text = translator.translate(prefix_instrs[-1]).strip()
                    last_accu = re.match(r"^ACCU\s*=\s*(.+)$", last_prefix_text)
                    if last_accu:
                        accu_expr = last_accu.group(1).strip()
                        prefix_instrs = prefix_instrs[:-1]
                        if "ACCU" not in accu_expr:
                            guard_condition = re.sub(
                                r"\bACCU\b", accu_expr, guard_condition
                            )
                        else:
                            prefix_lines = _render_level4_fragment(
                                translator, prefix_instrs
                            )
                            prefix_lines.append(f"{INDENT}{last_prefix_text}")

    catch_ctx_instr = next(
        (instr for instr in catch_instrs[:push_idx] if instr.mnemonic == "CreateCatchContext"),
        None,
    )
    if catch_ctx_instr is None:
        return None
    catch_name = (
        _catch_binding_name(ctx, translator, catch_ctx_instr)
    )

    try_lines = _render_level4_fragment(translator, try_instrs)
    catch_lines = _render_level4_fragment(translator, catch_body_instrs)
    if not try_lines or not catch_lines:
        return None

    try_catch_lines: List[str] = []
    try_catch_lines.append(f"{INDENT}try {{")
    try_catch_lines.extend(_indent_lines(try_lines))
    try_catch_lines.append(f"{INDENT}}} catch ({catch_name}) {{")
    try_catch_lines.extend(_indent_lines(catch_lines))
    try_catch_lines.append(f"{INDENT}}}")
    out: List[str] = []
    guarded_entry_offset = instructions[prefix_end_idx].offset
    alternate = _match_short_circuit_try_alternate(
        translator,
        instructions,
        prefix_instrs,
        guarded_entry_offset,
        suffix_start_idx,
    )
    if alternate is not None:
        setup_instrs, condition, alternate_instrs, final_suffix_instrs = alternate
        if setup_instrs:
            out.extend(_render_level4_fragment(translator, setup_instrs))
        out.append(f"{INDENT}if ({condition}) {{")
        out.extend(_indent_lines(try_catch_lines))
        out.append(f"{INDENT}}} else {{")
        out.extend(_indent_lines(_render_level4_fragment(translator, alternate_instrs)))
        out.append(f"{INDENT}}}")
        if final_suffix_instrs:
            out.extend(_render_level4_fragment(translator, final_suffix_instrs))
        return out
    if prefix_lines is not None:
        out.extend(prefix_lines)
    elif prefix_instrs:
        out.extend(_render_level4_fragment(translator, prefix_instrs))
    if guard_condition:
        out.append(f"{INDENT}if ({guard_condition}) {{")
        out.extend(_indent_lines(try_catch_lines))
        out.append(f"{INDENT}}}")
    else:
        out.extend(try_catch_lines)
    if suffix_instrs:
        out.extend(_render_level4_fragment(translator, suffix_instrs))
    return out


def _render_simple_try_catch(
    ctx: DecompilerContext,
    bytecode: V8BytecodeArray,
    translator: InstructionTranslator,
    instructions: List[Instruction],
) -> Optional[List[str]]:
    for entry in bytecode.handler_entries:
        rendered = _render_single_try_catch(ctx, translator, instructions, entry)
        if rendered is not None:
            return rendered
    return None


def render_level4(
    ctx: DecompilerContext,
    bytecode: V8BytecodeArray,
    translator: InstructionTranslator,
    instructions: List[Instruction],
) -> List[str]:
    recovered = _render_simple_try_catch(ctx, bytecode, translator, instructions)
    if recovered is not None:
        return recovered
    return _render_level4_fragment(translator, instructions)


def decompile_bytecode(ctx: DecompilerContext, bytecode: V8BytecodeArray, level: int) -> str:
    owner = ctx.get_function_for_bytecode(bytecode)
    if owner:
        raw_name = ctx.get_function_name(owner)
        fallback = f"fn_{bytecode.address:012x}"
        fn_name = _sanitize_identifier(raw_name, fallback)
    else:
        fn_name = f"bytecode_{bytecode.address:012x}"

    header = f"function {fn_name}({_format_params(bytecode)}) {{"
    metadata = (
        f"  // Bytecode 0x{bytecode.address:012x} "
        f"params={bytecode.parameter_count} "
        f"regs={bytecode.register_count} frame={bytecode.frame_size}"
    )

    translator = InstructionTranslator(ctx, bytecode)
    instructions = [Instruction.from_codeline(raw) for raw in bytecode.instructions]

    note: List[str] = []
    try:
        if level == 1:
            body_lines = render_level1(translator, instructions)
        elif level == 2:
            body_lines = render_level2(translator, instructions)
        elif level == 3:
            body_lines = render_level3(translator, instructions)
        else:
            body_lines = render_level4(ctx, bytecode, translator, instructions)
    except RecursionError:
        note.append("  // WARNING: structurer recursion overflow, fallback to level-1 linear output")
        body_lines = render_level1(translator, instructions)
    except Exception as exc:
        note.append(f"  // WARNING: decompile error ({type(exc).__name__}), fallback to level-1 linear output")
        body_lines = render_level1(translator, instructions)

    lines: List[str] = [header, metadata]
    lines.extend(_format_register_locals(bytecode))
    lines.extend(note)
    lines.extend(_format_constant_pool(ctx, bytecode))
    lines.extend(body_lines)
    lines.append("}")
    return "\n".join(lines)


def _read_disassembly_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def decompile_file(path: Path, level: int, runtime: bool = False) -> str:
    data = _read_disassembly_lines(path)
    objects = parse_objects(data)
    ctx = DecompilerContext(objects)

    outputs: List[str] = []
    if runtime:
        outputs.append(_runtime_prelude().rstrip())
    for obj in objects:
        if isinstance(obj, V8BytecodeArray):
            outputs.append(decompile_bytecode(ctx, obj, level))
    output = "\n\n".join(outputs)
    if level >= 4:
        output = postprocess_level4_file(output)
    return output


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_input = script_dir.parent / "samples" / "main.d8.jsc.txt"
    parser = argparse.ArgumentParser(description="V8 bytecode decompiler")
    parser.add_argument(
        "input",
        nargs="?",
        default=str(default_input),
        help="path to disassembled bytecode dump",
    )
    parser.add_argument(
        "--level",
        type=int,
        choices=(1, 2, 3, 4),
        default=3,
        help=(
            "Select decompilation level: "
            "1 = linear bytecode-aligned, "
            "2 = structured CFG, "
            "3 = structured + safe simplifications, "
            "4 = high-level JS-like recovery"
        ),
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Emit a lightweight JS runtime prelude to make pseudo code easier to run",
    )
    args = parser.parse_args()
    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"{path} does not exist")
    print(decompile_file(path, args.level, runtime=args.runtime))


if __name__ == "__main__":
    main()
