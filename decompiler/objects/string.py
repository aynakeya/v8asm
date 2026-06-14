import ast
from typing import Optional

from objects.base import *


# 0x35c2300818c1: [String] in ReadOnlySpace: #value
# 0x0551140004d1: [String]: #AAAAAAAAAAAAAAAAAAAAAAAA
# 0x2bf200103831: [String]: "document.body...\x0a..."
class V8String(V8HeapObject):
    def __init__(self, address:int, i_type:str, lines:List[str]):
        super().__init__(address,i_type,lines)
        self.length: int = 0
        self.value: str = ''
        self.in_readonly_space = False

    def parse(self):
        assert len(self.raw_asm_lines) == 1
        line = self.raw_asm_lines[0]
        payload = _string_payload(line)
        if payload is None:
            self.value = f"unknown_string_{self.address:012x}"
        elif payload.startswith("#"):
            self.value = payload[1:].strip()
        elif payload.startswith('"') and payload.endswith('"'):
            try:
                self.value = ast.literal_eval(payload)
            except (SyntaxError, ValueError):
                self.value = payload[1:-1]
        else:
            self.value = payload
        self.length = len(self.value)
        self.in_readonly_space = "in ReadOnlySpace" in line

    def __repr__(self):
        return f"<V8String: 0x{self.address:012x} [{'RO' if self.in_readonly_space else 'RW'}] len={self.length} value='{self.value if self.length <= 20 else self.value[:17] + '...'}'>"

    def __str__(self):
        return self.__repr__()


def _string_payload(line: str) -> Optional[str]:
    string_pos = line.find("[String")
    if string_pos == -1:
        return None
    type_end = line.find("]", string_pos)
    if type_end == -1:
        return None
    payload_sep = line.find(":", type_end)
    if payload_sep == -1:
        return None
    payload = line[payload_sep + 1 :].strip()
    return payload or None
