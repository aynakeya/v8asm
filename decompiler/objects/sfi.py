# objects/shared_function_info.py
from typing import Optional
from objects.base import *
from objects.string import V8String
from objects.bytecode import V8BytecodeArray

class V8SharedFunctionInfo(V8HeapObject):
    def __init__(self, address: int, i_type: str, lines: list[str]):
        super().__init__(address, i_type, lines)
        self.name: Optional[V8Address[V8String]] = None
        self.formal_parameter_count: Optional[int] = None
        self.language_mode: Optional[str] = None
        self.trusted_function_data: Optional[V8Address[V8BytecodeArray]] = None
        self.script_addr: Optional[int] = None
        self.func_kind: Optional[str] = None
        self.syntax_kind: Optional[str] = None

    def __parse_address(self, line: str) -> V8Address:
        parts = line.split(":", 1)[1].strip().split(" ", maxsplit=1)
        return V8Address(int(parts[0], 16), parts[1])

    def parse(self):
        for ln in self.raw_asm_lines:
            if ln.startswith(" - name: "):
                self.name = self.__parse_address(ln)
            elif ln.startswith(" - formal_parameter_count:"):
                self.formal_parameter_count = int(parse_string_after_colon(ln))
            elif " - language_mode:" in ln:
                self.language_mode = parse_string_after_colon(ln)
            elif " - kind:" in ln:
                self.func_kind = parse_string_after_colon(ln)
            elif "syntax kind" in ln:
                self.syntax_kind = parse_string_after_colon(ln)
            elif " - trusted_function_data:" in ln:
                self.trusted_function_data = V8Address.from_text(ln.split(": ", 1)[1].strip())
    def __repr__(self):
        return (f"<V8SharedFunctionInfo: 0x{self.address:012x} "
                f"name={self.name} "
                f"params={self.formal_parameter_count} "
                f"trusted_data={self.trusted_function_data} "
                f"language_mode={self.language_mode}>")
