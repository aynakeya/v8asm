from typing import Optional

from objects.fixed_array import V8FixedArray
from objects.base import *

class V8ArrayBoilerplateDescription(V8HeapObject):
    def __init__(self, address: int, i_type: str, lines: list[str]):
        super().__init__(address, i_type, lines)
        self.elements_kind: Optional[str] = None
        self.constant_elements: Optional[V8Address[V8FixedArray]] = None

    def parse(self):
        for ln in self.raw_asm_lines:
            if "elements kind:" in ln:
                self.elements_kind = ln.split(":", 1)[1].strip()
            elif "constant elements:" in ln:
                payload = ln.split(":", 1)[1].strip()
                self.constant_elements = V8Address[V8FixedArray].from_text(payload)

    def __repr__(self):
        return (f"<V8ArrayBoilerplateDescription: 0x{self.address:012x} "
                f"kind={self.elements_kind} "
                f"const={self.constant_elements}>")