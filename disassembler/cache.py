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
    if profile.has_ro_snapshot_checksum:
        if len(data) < 32:
            raise ValueError("file is shorter than this V8 version's code-cache header")
        ro_checksum, payload_length, checksum = struct.unpack_from("<3I", data, 16)
        header_size = 32
    else:
        ro_checksum = None
        payload_length, checksum = struct.unpack_from("<2I", data, 16)
        header_size = 24
    available = len(data) - header_size
    if payload_length > available:
        raise ValueError(
            f"payload length {payload_length} exceeds available {available} bytes; "
            "the selected V8 header layout does not match this buffer"
        )
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
