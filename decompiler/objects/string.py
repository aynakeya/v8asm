from objects.base import *


# 0x35c2300818c1: [String] in ReadOnlySpace: #value
# 0x0551140004d1: [String]: #AAAAAAAAAAAAAAAAAAAAAAAA
class V8String(V8HeapObject):
    def __init__(self, address:int, i_type:str, lines:List[str]):
        super().__init__(address,i_type,lines)
        self.length: int = 0
        self.value: str = ''
        self.in_readonly_space = False

    def parse(self):
        assert len(self.raw_asm_lines) == 1
        str_start = self.raw_asm_lines[0].find("#")
        if str_start == -1:
            raise ValueError(f"String object at 0x{self.address:012x} does not contain a value.")
        self.value = self.raw_asm_lines[0][str_start+1:].strip()
        self.length = len(self.value)
        self.in_readonly_space = "in ReadOnlySpace" in self.raw_asm_lines[0]

    def __repr__(self):
        return f"<V8String: 0x{self.address:012x} [{'RO' if self.in_readonly_space else 'RW'}] len={self.length} value='{self.value if self.length <= 20 else self.value[:17] + '...'}'>"

    def __str__(self):
        return self.__repr__()

