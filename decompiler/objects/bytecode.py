from typing import Optional
import re

from objects.base import *


class CodeLine:
    def __init__(self, offset: int, bytestr: str, mnemonic: str, operands: str, raw: str):
        self.offset = offset          # 指令偏移（如 0）
        self.bytestr = bytestr        # 原始字节串（如 "0b 04"）
        self.mnemonic = mnemonic      # 助记符（如 "Ldar"）
        self.operands = operands      # 操作数（如 "a1"）
        self.raw = raw                # 原始整行文本

    @classmethod
    def from_text(cls, line: str) -> "CodeLine":
        # 例: "0x18336d7c0110 @    0 : 0b 04             Ldar a1"
        try:
            after_at = line.split("@", 1)[1].strip()
            offset_str, rest = after_at.split(":", 1)
            offset = int(offset_str.strip())
            rest = rest.strip()
            # 字节码 bytes 部分和指令分隔：助记符一般是第一个非 hex token
            parts = rest.split()
            # 先取 hex 部分
            bytes_list = []
            while parts and all(c in "0123456789abcdef" for c in parts[0].lower()):
                bytes_list.append(parts.pop(0))
            bytestr = " ".join(bytes_list)
            mnemonic = parts[0] if parts else ""
            operands = " ".join(parts[1:]) if len(parts) > 1 else ""
            return cls(offset, bytestr, mnemonic, operands, line)
        except Exception:
            return cls(-1, "", "", "", line)

    def __repr__(self):
        return f"<CodeLine offset={self.offset} {self.mnemonic} {self.operands}>"


class HandlerEntry:
    def __init__(self, start: int, end: int, handler: int, prediction: int, data: int):
        self.start = start
        self.end = end
        self.handler = handler
        self.prediction = prediction
        self.data = data

    @classmethod
    def from_text(cls, line: str) -> "HandlerEntry":
        # example: (  19,  65)  ->    71 (prediction=0, data=10)
        m = re.match(
            r"\(\s*(\d+),\s*(\d+)\)\s*->\s*(\d+)\s*\(prediction=(\d+),\s*data=(\d+)\)",
            line.strip()
        )
        if m:
            return cls(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5)),
            )
        return cls(-1, -1, -1, -1, -1)

    def __repr__(self):
        return f"<HandlerEntry from={self.start} to={self.end} -> {self.handler} pred={self.prediction} data={self.data}>"


class V8BytecodeArray(V8HeapObject):
    def __init__(self, address: int, i_type: str, lines: List[str]):
        super().__init__(address, i_type, lines)
        self.parameter_count: Optional[int] = None
        self.register_count: Optional[int] = None
        self.frame_size: Optional[int] = None
        self.constant_pool_size: Optional[int] = None
        self.handler_table_size: Optional[int] = None
        self.source_position_table_size: Optional[int] = None
        self.instructions: List[CodeLine] = []
        self.handler_entries: List[HandlerEntry] = []

    def parse(self):
        in_handler_table = False
        for ln in self.raw_asm_lines:
            s = ln.strip()
            if s.startswith("Parameter count"):
                self.parameter_count = int(s.split()[-1])
            elif s.startswith("Register count"):
                self.register_count = int(s.split()[-1])
            elif s.startswith("Frame size"):
                self.frame_size = int(s.split()[-1])
            elif "Constant pool (size =" in s:
                self.constant_pool_size = int(s.split("=")[1].split(")")[0])
                in_handler_table = False
            elif "Handler Table (size =" in s:
                self.handler_table_size = int(s.split("=")[1].split(")")[0])
                in_handler_table = True
            elif "Source Position Table (size =" in s:
                self.source_position_table_size = int(s.split("=")[1].split(")")[0])
                in_handler_table = False
            elif s.startswith("0x") and "@" in s:
                self.instructions.append(CodeLine.from_text(s))
            elif in_handler_table and s.startswith("("):
                entry = HandlerEntry.from_text(s)
                self.handler_entries.append(entry)
            else:
                pass

    def __repr__(self):
        return (f"<V8BytecodeArray: 0x{self.address:012x} "
                f"params={self.parameter_count} regs={self.register_count} "
                f"frame={self.frame_size} instrs={len(self.instructions)} "
                f"const_pool_size={self.constant_pool_size} "
                f"handler_table_size={self.handler_table_size} "
                f"sptable_size={self.source_position_table_size}>")