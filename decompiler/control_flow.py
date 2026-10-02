"""Executable fallback for control flow that cannot yet be structured safely."""

from .cfg import build_basic_blocks
from .objects import V8Smi, V8String
from .utils import parse_jump_target


def switch_targets(translator, instruction):
    start, count, base = (int(token.strip("[]")) for token in instruction.args[:3])
    targets = {}
    for index in range(count):
        value = translator.constants[start + index].raw
        if not isinstance(value, V8Smi):
            continue
        targets[base + index] = instruction.offset + instruction.prefix_size + value.value
    return targets


def render_dispatch(translator, instructions):
    entries = translator.bytecode.handler_entries
    leaders = set()
    switches = {}
    for entry in entries:
        leaders.update((entry.start, entry.end, entry.handler))
    for index, item in enumerate(instructions):
        if item.mnemonic == "SwitchOnSmiNoFeedback":
            switches[item.offset] = switch_targets(translator, item)
            leaders.update(switches[item.offset].values())
        if item.mnemonic in {"SwitchOnSmiNoFeedback", "Return", "Throw", "ReThrow"}:
            if index + 1 < len(instructions):
                leaders.add(instructions[index + 1].offset)
    blocks = build_basic_blocks(instructions, leaders)
    offsets = {block.start for block in blocks}
    if not blocks:
        return []
    used_names = {obj.value for obj in translator.context.objects if isinstance(obj, V8String)}
    pc = "__v8_pc"
    while pc in used_names:
        pc += "_"

    def jump(target, indent="      "):
        if target not in offsets:
            raise ValueError(f"unresolved control-flow target {target}")
        return [f"{indent}{pc} = {target};", f"{indent}continue dispatch;"]

    output = ["  // Explicit control flow preserves exception completion and nested jumps.",
              f"  let {pc} = {blocks[0].start};", "  dispatch: while (true) {", f"    switch ({pc}) {{"]
    for index, block in enumerate(blocks):
        output.append(f"    case {block.start}: {{")
        active = [entry for entry in entries if entry.start <= block.start < entry.end]
        handler = min(active, key=lambda entry: entry.end - entry.start) if active else None
        lines = []
        for item in block.instructions[:-1]:
            lines.extend(f"      {line}" for line in translator.translate(item).splitlines())
        term = block.instructions[-1]
        target = parse_jump_target(term)
        next_offset = blocks[index + 1].start if index + 1 < len(blocks) else None
        if term.mnemonic.startswith("JumpIf"):
            condition = translator.branch_expression(term, taken=True)
            if condition is None:
                raise ValueError(f"unsupported branch condition {term.mnemonic}")
            if target not in offsets or next_offset not in offsets:
                raise ValueError("unresolved branch target")
            lines.extend([f"      {pc} = {condition} ? {target} : {next_offset};", "      continue dispatch;"])
        elif term.mnemonic in {"Jump", "JumpConstant", "JumpLoop", "JumpLoopConstant"}:
            lines.extend(jump(target))
        elif term.offset in switches:
            lines.append("      switch (ACCU) {")
            for value, destination in switches[term.offset].items():
                lines.append(f"      case {value}:")
                lines.extend(jump(destination, "        "))
            lines.append("      }")
            lines.extend(jump(next_offset))
        else:
            lines.extend(f"      {line}" for line in translator.translate(term).splitlines())
            if term.mnemonic not in {"Return", "Throw", "ReThrow", "Abort"}:
                lines.extend(jump(next_offset) if next_offset is not None else ["      return;"])
        if handler is not None:
            output.append("      try {")
            output.extend("  " + line for line in lines)
            output.extend(["      } catch (exception) {", "        ACCU = exception;",
                           f"        context = r{handler.data};"])
            output.extend(jump(handler.handler, "        "))
            output.append("      }")
        else:
            output.extend(lines)
        output.append("    }")
    output.extend(["    }", "  }"])
    return output
