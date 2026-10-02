from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .cfg import (
    BasicBlock,
    build_basic_blocks,
    find_loop_regions,
    is_conditional,
    is_loop_jump,
    is_unconditional_jump,
)
from .instruction import Instruction
from .statements import IfStatement, LoopStatement, SimpleStatement, Statement
from .translator import InstructionTranslator
from .utils import parse_jump_target, strip_trailing_goto


class Structurer:
    def __init__(self, translator: InstructionTranslator, blocks: List[BasicBlock]):
        self.translator = translator
        self.blocks = blocks
        self.offset_to_index: Dict[int, int] = {
            block.start: idx for idx, block in enumerate(blocks)
        }
        self.loop_regions = find_loop_regions(blocks)
        self.active_loops: Set[int] = set()
        self.active_if_builds: Set[int] = set()
        self.pending_raw_branch_targets: Set[int] = set()

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
        seen_indices: Set[int] = set()
        while idx < len(self.blocks):
            if idx in seen_indices:
                break
            seen_indices.add(idx)
            block = self.blocks[idx]
            if stop_offset is not None and block.start >= stop_offset:
                break
            produced, idx = self._emit_block(idx)
            if idx in seen_indices:
                idx += 1
            statements.extend(produced)
        return statements, idx

    def _emit_block(self, block_idx: int) -> Tuple[List[Statement], int]:
        block = self.blocks[block_idx]
        statements: List[Statement] = []
        self.pending_raw_branch_targets.discard(block.start)

        loop_region = self.loop_regions.get(block.start)
        if loop_region and block.start not in self.active_loops:
            self.active_loops.add(block.start)
            body, _ = self._emit_region(loop_region.start, loop_region.end)
            self.active_loops.remove(block.start)
            if (
                body and isinstance(body[-1], SimpleStatement)
                and body[-1].text == f"continue loop_{block.start}"
            ):
                body.pop()
            loop_stmt = LoopStatement(condition="true", body=body, label=f"loop_{block.start}")
            next_idx = self.offset_to_index.get(loop_region.end, len(self.blocks))
            return [loop_stmt], next_idx

        instructions = block.instructions
        if not instructions:
            return statements, block_idx + 1

        term = instructions[-1]
        for instr in instructions[:-1]:
            text = self.translator.translate(instr)
            if text:
                statements.append(SimpleStatement(text))

        if is_conditional(term.mnemonic):
            target = parse_jump_target(term)
            loop_jump = self._loop_transfer(target)
            if loop_jump:
                condition = self.translator.branch_expression(term, taken=True)
                if condition is None:
                    raise ValueError(f"unsupported branch condition {term.mnemonic}")
                statements.append(IfStatement(condition, [SimpleStatement(loop_jump)]))
                return statements, block_idx + 1
            if not self._is_pending_raw_dispatch_target(block.start, target):
                built = self._build_if(block_idx)
                if built:
                    stmt, next_idx = built
                    statements.append(stmt)
                    return statements, next_idx

        if term.mnemonic == "Return":
            statements.append(SimpleStatement(self.translator.translate(term)))
            return statements, block_idx + 1

        if is_loop_jump(term.mnemonic):
            transfer = self._loop_transfer(parse_jump_target(term))
            if transfer:
                statements.append(SimpleStatement(transfer))
            return statements, block_idx + 1

        if is_unconditional_jump(term.mnemonic):
            target = parse_jump_target(term)
            if target is not None:
                transfer = self._loop_transfer(target)
                if transfer:
                    statements.append(SimpleStatement(transfer))
                    return statements, block_idx + 1
                statements.append(SimpleStatement(f"goto offset_{target}"))
                if self._has_pending_raw_target_between(block.start, target):
                    self.pending_raw_branch_targets.add(target)
                    return statements, block_idx + 1
                next_idx = self.offset_to_index.get(target, block_idx + 1)
                return statements, next_idx

        if term.mnemonic.startswith("JumpIf"):
            # Fallback when structure reconstruction failed.
            statements.append(SimpleStatement(self.translator.translate(term)))
            target = parse_jump_target(term)
            if target is not None and target > block.start:
                self.pending_raw_branch_targets.add(target)
            return statements, block_idx + 1

        text = self.translator.translate(term)
        if text:
            statements.append(SimpleStatement(text))
        return statements, block_idx + 1

    def _loop_transfer(self, target: Optional[int]) -> Optional[str]:
        for start in sorted(self.active_loops, reverse=True):
            region = self.loop_regions[start]
            if target == region.end:
                return f"break loop_{start}"
            if target == region.start:
                return f"continue loop_{start}"
        return None

    def _build_if(self, block_idx: int) -> Optional[Tuple[Statement, int]]:
        if block_idx in self.active_if_builds:
            return None
        self.active_if_builds.add(block_idx)
        try:
            return self._build_if_inner(block_idx)
        finally:
            self.active_if_builds.remove(block_idx)

    def _build_if_inner(self, block_idx: int) -> Optional[Tuple[Statement, int]]:
        block = self.blocks[block_idx]
        term = block.terminator
        if term is None:
            return None
        target = parse_jump_target(term)
        if target is None or target <= block.start:
            return None

        condition = self.translator.branch_expression(term, taken=False)
        if not condition:
            return None

        fallthrough_idx = block_idx + 1
        if fallthrough_idx >= len(self.blocks):
            return None
        fallthrough_start = self.blocks[fallthrough_idx].start

        then_statements, then_end_idx = self._emit_region(fallthrough_start, target)
        else_statements: Optional[List[Statement]] = None
        join_offset = target

        # A nested branch may already cover the original target and its merge.
        # Resume after that whole region, not inside its shared branch body.
        if then_end_idx < len(self.blocks):
            join_offset = max(join_offset, self.blocks[then_end_idx].start)

        last_idx = self._block_index_before(target)
        if last_idx is not None:
            last_block = self.blocks[last_idx]
            last_term = last_block.terminator
            if last_term and is_unconditional_jump(last_term.mnemonic):
                join_candidate = parse_jump_target(last_term)
                if (
                    join_candidate and join_candidate > target
                    and not self._loop_transfer(join_candidate)
                ):
                    join_offset = max(join_offset, join_candidate)

        if join_offset > target:
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

    def _has_pending_raw_target_between(self, start: int, end: int) -> bool:
        if end <= start:
            return False
        return any(start < target < end for target in self.pending_raw_branch_targets)

    def _is_pending_raw_dispatch_target(
        self, start: int, target: Optional[int]
    ) -> bool:
        if target is None or target <= start or not self.pending_raw_branch_targets:
            return False
        first_pending = min(self.pending_raw_branch_targets)
        return target >= first_pending


def decompile_to_statements(
    translator: InstructionTranslator, instructions: List[Instruction]
) -> List[Statement]:
    blocks = build_basic_blocks(instructions)
    structurer = Structurer(translator, blocks)
    return structurer.build()
