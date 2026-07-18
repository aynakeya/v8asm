from __future__ import annotations

import struct
from dataclasses import dataclass

from .profiles import Profile, ProfileSet


@dataclass(frozen=True)
class CacheHeader:
    magic: int
    version_hash: int
    source_hash: int
    flags_hash: int
    ro_snapshot_checksum: int | None
    payload_length: int
    checksum: int
    header_size: int
    raw_payload: bool = False


def parse_header(
    data: bytes, profiles: ProfileSet, version: str | None = None
) -> tuple[CacheHeader, Profile]:
    if len(data) < 24:
        raise ValueError("file is shorter than the minimum V8 code-cache header")
    magic, version_hash, source_hash, flags_hash = struct.unpack_from("<4I", data)
    profile = profiles.by_version(version) if version else profiles.by_hash(version_hash)

    candidates: list[tuple[str, int, int | None, int, int]] = []
    attempts: list[str] = []
    for name, unaligned_size, ro_offset, length_offset, checksum_offset in (
        ("legacy", 24, None, 16, 20),
        ("read-only-checksum", 28, 16, 20, 24),
    ):
        if len(data) < unaligned_size:
            continue
        payload_length = struct.unpack_from("<I", data, length_offset)[0]
        header_size = len(data) - payload_length
        detail = (
            f"{name} fields encode {payload_length} payload bytes, "
            f"implying a {header_size}-byte header"
        )
        if header_size < unaligned_size or header_size % 4:
            attempts.append(f"{detail}, which is not a valid aligned header")
            continue
        if any(data[unaligned_size:header_size]):
            attempts.append(f"{detail}, but header padding is not zero")
            continue
        ro_checksum = (
            struct.unpack_from("<I", data, ro_offset)[0]
            if ro_offset is not None
            else None
        )
        checksum = struct.unpack_from("<I", data, checksum_offset)[0]
        candidates.append(
            (name, header_size, ro_checksum, payload_length, checksum)
        )

    if not candidates:
        raise ValueError(
            "no cached-data header layout matches the file length: "
            + "; ".join(attempts)
        )
    if len(candidates) != 1:
        layouts = ", ".join(
            f"{candidate[0]} ({candidate[1]} bytes)" for candidate in candidates
        )
        raise ValueError(f"cached-data header layout is ambiguous: {layouts}")
    _, header_size, ro_checksum, payload_length, checksum = candidates[0]

    return (
        CacheHeader(
            magic=magic,
            version_hash=version_hash,
            source_hash=source_hash,
            flags_hash=flags_hash,
            ro_snapshot_checksum=ro_checksum,
            payload_length=payload_length,
            checksum=checksum,
            header_size=header_size,
        ),
        profile,
    )
