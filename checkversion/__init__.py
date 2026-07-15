from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import itertools
import multiprocessing
from pathlib import Path


_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF
_HASH_MULTIPLIER = 0xC6A4A7935BD1E995


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    build: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.build}.{self.patch}"


@lru_cache(maxsize=None)
def _hash_value_unsigned_32(value: int) -> int:
    value &= _MASK32
    value = (~value + (value << 15)) & _MASK32
    value = (value ^ (value >> 12)) & _MASK32
    value = (value + (value << 2)) & _MASK32
    value = (value ^ (value >> 4)) & _MASK32
    value = (value * 2057) & _MASK32
    return (value ^ (value >> 16)) & _MASK32


def _hash_combine_64(seed: int, value: int) -> int:
    value = (value * _HASH_MULTIPLIER) & _MASK64
    value ^= value >> 47
    value = (value * _HASH_MULTIPLIER) & _MASK64
    return ((seed ^ value) * _HASH_MULTIPLIER) & _MASK64


def calculate_version_hash(
    major: int, minor: int, build: int, patch: int
) -> int:
    parts = (major, minor, build, patch)
    if any(part < 0 for part in parts):
        raise ValueError("version components must be non-negative")
    if major < 12:
        parts = tuple(reversed(parts))
    seed = 0
    for part in parts:
        seed = _hash_combine_64(seed, _hash_value_unsigned_32(part))
    return seed & _MASK32


def parse_cached_data_hash(path: str | Path) -> int:
    data = Path(path).read_bytes()
    if len(data) < 8:
        raise ValueError("cached-data file is shorter than its version hash field")
    return int.from_bytes(data[4:8], "little")


def _search_task(
    task: tuple[int, int, tuple[int, int], tuple[int, int], int]
) -> Version | None:
    major, minor, build_range, patch_range, target = task
    builds = range(*build_range)
    patches = range(*patch_range)
    major_hash = _hash_value_unsigned_32(major)
    minor_hash = _hash_value_unsigned_32(minor)
    patch_hashes = tuple(
        (patch, _hash_value_unsigned_32(patch)) for patch in patches
    )

    if major >= 12:
        prefix = _hash_combine_64(0, major_hash)
        prefix = _hash_combine_64(prefix, minor_hash)
        for build in builds:
            seed = _hash_combine_64(prefix, _hash_value_unsigned_32(build))
            for patch, patch_hash in patch_hashes:
                if _hash_combine_64(seed, patch_hash) & _MASK32 == target:
                    return Version(major, minor, build, patch)
        return None

    patch_seeds = tuple(
        (patch, _hash_combine_64(0, patch_hash))
        for patch, patch_hash in patch_hashes
    )
    for build in builds:
        build_hash = _hash_value_unsigned_32(build)
        for patch, seed in patch_seeds:
            candidate = _hash_combine_64(seed, build_hash)
            candidate = _hash_combine_64(candidate, minor_hash)
            candidate = _hash_combine_64(candidate, major_hash)
            if candidate & _MASK32 == target:
                return Version(major, minor, build, patch)
    return None


def find_version(
    target_hash: int,
    *,
    major_range: tuple[int, int] = (0, 20),
    minor_range: tuple[int, int] = (0, 20),
    build_range: tuple[int, int] = (0, 500),
    patch_range: tuple[int, int] = (0, 200),
    jobs: int = 1,
) -> Version | None:
    ranges = (major_range, minor_range, build_range, patch_range)
    if any(start < 0 or end <= start for start, end in ranges):
        raise ValueError("search ranges must be non-negative, non-empty intervals")
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    target_hash &= _MASK32
    tasks = (
        (major, minor, build_range, patch_range, target_hash)
        for major, minor in itertools.product(
            range(*major_range), range(*minor_range)
        )
    )
    if jobs == 1:
        for task in tasks:
            result = _search_task(task)
            if result is not None:
                return result
        return None

    task_count = (major_range[1] - major_range[0]) * (
        minor_range[1] - minor_range[0]
    )
    process_count = min(jobs, task_count)
    with multiprocessing.get_context().Pool(process_count) as pool:
        for result in pool.imap(_search_task, tasks, chunksize=1):
            if result is not None:
                pool.terminate()
                return result
    return None


__all__ = [
    "Version",
    "calculate_version_hash",
    "find_version",
    "parse_cached_data_hash",
]
