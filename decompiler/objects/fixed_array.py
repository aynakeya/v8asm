from typing import Optional, Any
from objects.base import V8HeapObject, V8Address, V8Smi


class V8FixedArray(V8HeapObject):
    def __init__(self, address: int, i_type: str, lines: list[str]):
        super().__init__(address, i_type, lines)
        self.length: Optional[int] = None
        self.elements: list[Any] = []

    def parse(self):
        for ln in self.raw_asm_lines:
            if "- length:" in ln:
                self.length = int(ln.split(":", 1)[1].strip())
            elif ":" in ln and ln.strip()[0].isdigit():
                # e.g. "0: 0x12345 <SharedFunctionInfo foo>" or "0: 3"
                idx, rest = ln.split(":", 1)
                rest = rest.strip()
                # case 1: address
                if rest.startswith("0x"):
                    self.elements.append(V8Address.from_text(rest))
                # case 2: smi (integer literal)
                elif rest.lstrip("-").isdigit():
                    self.elements.append(V8Smi(int(rest)))
                # case 3: fallback to raw string
                else:
                    self.elements.append(rest)

    def __repr__(self):
        return (f"<V8FixedArray: 0x{self.address:012x} "
                f"len={self.length} elems={len(self.elements)}>")


class V8TrustedFixedArray(V8FixedArray):
    def __repr__(self):
        return (f"<V8TrustedFixedArray: 0x{self.address:012x} "
                f"len={self.length} elems={len(self.elements)}>")