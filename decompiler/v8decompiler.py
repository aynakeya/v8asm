from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from objects.bytecode import V8BytecodeArray

from context import DecompilerContext
from instruction import Instruction
from parser import parse_objects
from translator import InstructionTranslator


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


def decompile_bytecode(ctx: DecompilerContext, bytecode: V8BytecodeArray) -> str:
    owner = ctx.get_function_for_bytecode(bytecode)
    if owner:
        fn_name = ctx.get_function_name(owner)
    else:
        fn_name = f"bytecode_0x{bytecode.address:012x}"

    header = f"function {fn_name}({_format_params(bytecode)}) {{"
    metadata = (
        f"  // Bytecode 0x{bytecode.address:012x} "
        f"params={bytecode.parameter_count} "
        f"regs={bytecode.register_count} frame={bytecode.frame_size}"
    )

    translator = InstructionTranslator(ctx, bytecode)
    body_lines = []
    for raw in bytecode.instructions:
        instr = Instruction.from_codeline(raw)
        translated = translator.translate(instr)
        offset = instr.offset if instr.offset >= 0 else -1
        body_lines.append(f"  [{offset:4d}] {translated}")

    lines: List[str] = [header, metadata]
    lines.extend(_format_constant_pool(ctx, bytecode))
    lines.extend(body_lines)
    lines.append("}")
    return "\n".join(lines)


def decompile_file(path: Path) -> str:
    data = path.read_text().splitlines()
    objects = parse_objects(data)
    ctx = DecompilerContext(objects)

    outputs: List[str] = []
    for obj in objects:
        if isinstance(obj, V8BytecodeArray):
            outputs.append(decompile_bytecode(ctx, obj))
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
    args = parser.parse_args()
    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"{path} does not exist")
    print(decompile_file(path))


if __name__ == "__main__":
    main()
