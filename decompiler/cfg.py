from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from instruction import Instruction
from utils import parse_jump_target


UNCONDITIONAL_JUMPS = {"Jump", "JumpConstant"}
LOOP_JUMPS = {"JumpLoop", "JumpLoopConstant"}


def is_conditional(mnemonic: str) -> bool:
    return mnemonic.startswith("JumpIf")


def is_loop_jump(mnemonic: str) -> bool:
    return mnemonic in LOOP_JUMPS


def is_unconditional_jump(mnemonic: str) -> bool:
    return mnemonic in UNCONDITIONAL_JUMPS


@dataclass
class BasicBlock:
    start: int
    end: Optional[int]
    instructions: List[Instruction]

    @property
    def terminator(self) -> Optional[Instruction]:
        return self.instructions[-1] if self.instructions else None


@dataclass
class LoopRegion:
    start: int
    end: int


def build_basic_blocks(instructions: List[Instruction]) -> List[BasicBlock]:
    if not instructions:
        return []

    offset_to_index: Dict[int, int] = {
        instr.offset: idx for idx, instr in enumerate(instructions) if instr.offset >= 0
    }
    sorted_offsets = sorted(offset_to_index.keys())
    leaders: Set[int] = set(sorted_offsets[:1])

    def next_offset(idx: int) -> Optional[int]:
        for nxt in instructions[idx + 1 :]:
            if nxt.offset >= 0:
                return nxt.offset
        return None

    for idx, instr in enumerate(instructions):
        if instr.offset < 0:
            continue
        if is_unconditional_jump(instr.mnemonic) or is_loop_jump(instr.mnemonic):
            target = parse_jump_target(instr)
            if target is not None:
                leaders.add(target)
            nxt = next_offset(idx)
            if nxt is not None:
                leaders.add(nxt)
        elif is_conditional(instr.mnemonic):
            target = parse_jump_target(instr)
            if target is not None:
                leaders.add(target)
            nxt = next_offset(idx)
            if nxt is not None:
                leaders.add(nxt)

    all_leaders = sorted(leaders)
    blocks: List[BasicBlock] = []
    for i, start in enumerate(all_leaders):
        block_instrs: List[Instruction] = []
        idx = offset_to_index.get(start)
        if idx is None:
            continue
        end_offset = all_leaders[i + 1] if i + 1 < len(all_leaders) else None
        while idx < len(instructions):
            instr = instructions[idx]
            if instr.offset < 0:
                idx += 1
                continue
            if end_offset is not None and instr.offset >= end_offset:
                break
            block_instrs.append(instr)
            idx += 1
        if end_offset is None and block_instrs:
            end_offset = block_instrs[-1].offset + 1
        blocks.append(BasicBlock(start=start, end=end_offset, instructions=block_instrs))
    return blocks


def find_loop_regions(blocks: List[BasicBlock]) -> Dict[int, LoopRegion]:
    regions: Dict[int, LoopRegion] = {}
    for block in blocks:
        term = block.terminator
        if term and is_loop_jump(term.mnemonic):
            target = parse_jump_target(term)
            if target is None or block.end is None:
                continue
            regions[target] = LoopRegion(start=target, end=block.end)
    return regions
