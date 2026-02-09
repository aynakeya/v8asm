from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import List

from objects.bytecode import V8BytecodeArray

from context import DecompilerContext
from instruction import Instruction
from parser import parse_objects
from postprocess import simplify_lines
from structurer import decompile_to_statements
from translator import InstructionTranslator

IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


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
function create_closure(fn) { return typeof fn === "function" ? fn : function () { return undefined; }; }
function pushContext(v) { context = v; return context; }
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


def render_level4(translator: InstructionTranslator, instructions: List[Instruction]) -> List[str]:
    return simplify_lines(render_level2(translator, instructions), recover_structures=True)


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
            body_lines = render_level4(translator, instructions)
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


def decompile_file(path: Path, level: int, runtime: bool = False) -> str:
    data = path.read_text().splitlines()
    objects = parse_objects(data)
    ctx = DecompilerContext(objects)

    outputs: List[str] = []
    if runtime:
        outputs.append(_runtime_prelude().rstrip())
    for obj in objects:
        if isinstance(obj, V8BytecodeArray):
            outputs.append(decompile_bytecode(ctx, obj, level))
    return "\n\n".join(outputs)


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
