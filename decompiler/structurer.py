from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from cfg import (
    BasicBlock,
    LoopRegion,
    build_basic_blocks,
    find_loop_regions,
    is_conditional,
    is_loop_jump,
    is_unconditional_jump,
)
from statements import IfStatement, LoopStatement, SimpleStatement, Statement
from translator import InstructionTranslator
from utils import parse_jump_target, strip_trailing_goto


class Structurer:
    def __init__(self, translator: InstructionTranslator, blocks: List[BasicBlock]):
        self.translator = translator
        self.blocks = blocks
        self.offset_to_index: Dict[int, int] = {
            block.start: idx for idx, block in enumerate(blocks)
        }
        self.loop_regions = find_loop_regions(blocks)
        self.active_loops: Set[int] = set()

    def build(self) -> List[Statement]:
        if not self.blocks:
            return []
        start = self.blocks[0].start
        statements, _ = self._emit_region(start, None)
        return statements

    def _emit_region(
        self, start_offset: int, stop_offset: Optional[int]
    ) -> Tuple[List[Statement], int]:
        idx = self.offset_to_index.get(start_offset, 0)
        statements: List[Statement] = []
        while idx < len(self.blocks):
            block = self.blocks[idx]
            if stop_offset is not None and block.start >= stop_offset:
                break
            produced, idx = self._emit_block(idx, stop_offset)
            statements.extend(produced)
        return statements, idx

    def _emit_block(
        self, block_idx: int, stop_offset: Optional[int]
    ) -> Tuple[List[Statement], int]:
        block = self.blocks[block_idx]
        statements: List[Statement] = []

        if stop_offset is not None and block.start >= stop_offset:
            return statements, block_idx

        loop_region = self.loop_regions.get(block.start)
        if loop_region and block.start not in self.active_loops:
            self.active_loops.add(block.start)
            body, _ = self._emit_region(loop_region.start, loop_region.end)
            self.active_loops.remove(block.start)
            condition = self._loop_condition(loop_region)
            loop_stmt = LoopStatement(condition=condition, body=body)
            next_idx = self.offset_to_index.get(loop_region.end, len(self.blocks))
            return [loop_stmt], next_idx

        instructions = block.instructions[:]
        if not instructions:
            return statements, block_idx + 1

        term = instructions[-1]
        body_instrs = instructions[:-1] if len(instructions) > 1 else []
        for instr in body_instrs:
            text = self.translator.translate(instr)
            if text:
                statements.append(SimpleStatement(text))

        if term is None:
            return statements, block_idx + 1

        if is_conditional(term.mnemonic):
            built = self._build_if(block_idx, stop_offset)
            if built:
                stmt, next_idx = built
                statements.append(stmt)
                return statements, next_idx

        if term.mnemonic == "Return":
            statements.append(SimpleStatement(self.translator.translate(term)))
            return statements, block_idx + 1

        if is_loop_jump(term.mnemonic):
            # Closing jump of a loop – skip explicit goto.
            return statements, block_idx + 1

        if is_unconditional_jump(term.mnemonic):
            target = parse_jump_target(term)
            if target is not None:
                statements.append(SimpleStatement(f"goto offset_{target}"))
                next_idx = self.offset_to_index.get(target, block_idx + 1)
                return statements, next_idx

        if term.mnemonic.startswith("JumpIf"):
            # Fallback when structure reconstruction failed.
            statements.append(SimpleStatement(self.translator.translate(term)))
            target = parse_jump_target(term)
            next_idx = (
                self.offset_to_index.get(target, block_idx + 1)
                if target is not None
                else block_idx + 1
            )
            return statements, next_idx

        text = self.translator.translate(term)
        if text:
            statements.append(SimpleStatement(text))
        return statements, block_idx + 1

    def _loop_condition(self, region: LoopRegion) -> str:
        start_idx = self.offset_to_index.get(region.start, 0)
        end_idx = self.offset_to_index.get(region.end, len(self.blocks))
        for idx in range(start_idx, end_idx):
            block = self.blocks[idx]
            term = block.terminator
            if not term:
                continue
            target = parse_jump_target(term)
            if target == region.end and term.mnemonic.startswith("JumpIf"):
                info = self.translator.branch_condition(term)
                if info:
                    expr, branch_on_true = info
                    return f"!({expr})" if branch_on_true else expr
        return "true"

    def _build_if(
        self, block_idx: int, stop_offset: Optional[int]
    ) -> Optional[Tuple[Statement, int]]:
        block = self.blocks[block_idx]
        term = block.terminator
        if term is None:
            return None
        target = parse_jump_target(term)
        if target is None or target <= block.start:
            return None

        condition = self.translator.fallthrough_condition(term)
        if not condition:
            return None

        fallthrough_idx = block_idx + 1
        if fallthrough_idx >= len(self.blocks):
            return None
        fallthrough_start = self.blocks[fallthrough_idx].start

        then_statements, _ = self._emit_region(fallthrough_start, target)
        strip_trailing_goto(then_statements, target)
        else_statements: Optional[List[Statement]] = None
        join_offset = target

        last_idx = self._block_index_before(target)
        if last_idx is not None:
            last_block = self.blocks[last_idx]
            last_term = last_block.terminator
            if last_term and is_unconditional_jump(last_term.mnemonic):
                join_candidate = parse_jump_target(last_term)
                if join_candidate and join_candidate > target:
                    join_offset = join_candidate
                    else_statements, _ = self._emit_region(target, join_offset)
                    strip_trailing_goto(then_statements, join_offset)
                    if else_statements:
                        strip_trailing_goto(else_statements, join_offset)

        next_idx = self.offset_to_index.get(join_offset, len(self.blocks))
        stmt = IfStatement(
            condition=condition,
            then_branch=then_statements,
            else_branch=else_statements,
        )
        return stmt, next_idx

    def _block_index_before(self, offset: int) -> Optional[int]:
        result = None
        for idx, block in enumerate(self.blocks):
            if block.start < offset:
                result = idx
            else:
                break
        return result


def decompile_to_statements(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[Statement]:
    blocks = build_basic_blocks(instructions)
    structurer = Structurer(translator, blocks)
    return structurer.build()
