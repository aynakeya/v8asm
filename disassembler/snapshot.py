from __future__ import annotations

from dataclasses import dataclass

from .profiles import Profile


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def byte(self) -> int:
        if self.position >= len(self.data):
            raise ValueError("unexpected end of read-only snapshot payload")
        value = self.data[self.position]
        self.position += 1
        return value

    def raw(self, size: int) -> bytes:
        if size < 0 or self.position + size > len(self.data):
            raise ValueError("read-only snapshot entry exceeds its payload")
        start = self.position
        self.position += size
        return self.data[start : start + size]

    def uint30(self) -> int:
        if self.position + 4 > len(self.data):
            raise ValueError("truncated read-only snapshot uint30")
        size = (self.data[self.position] & 3) + 1
        value = int.from_bytes(self.raw(size), "little")
        return value >> 2

    def uint32(self) -> int:
        return int.from_bytes(self.raw(4), "little")


@dataclass(frozen=True)
class _Page:
    data: bytes
    present: bytes


@dataclass(frozen=True)
class ReadOnlySnapshot:
    version: str
    magic: int
    checksum: int
    profile: Profile
    tagged_size: int
    pages: tuple[_Page, ...]
    area_start_offset: int
    static_roots: bool
    root_locations: dict[tuple[int, int], str]

    @classmethod
    def parse(
        cls, data: bytes, profile: Profile, tagged_size: int
    ) -> ReadOnlySnapshot:
        if tagged_size not in (4, 8):
            raise ValueError("snapshot tagged_size must be 4 or 8")
        if not profile.has_ro_snapshot_checksum:
            raise ValueError(
                f"V8 {profile.version} uses the legacy read-only snapshot format, "
                "which disassembler does not support"
            )
        if len(data) < 88:
            raise ValueError("snapshot blob is shorter than its V8 header")

        version = data[16:80].split(b"\0", 1)[0].decode("ascii", errors="strict")
        if version.split("-", 1)[0] != profile.version:
            raise ValueError(
                f"snapshot V8 version {version or '<empty>'} does not match "
                f"profile {profile.version}"
            )
        read_only_offset = int.from_bytes(data[80:84], "little")
        shared_heap_offset = int.from_bytes(data[84:88], "little")
        if not 88 <= read_only_offset < shared_heap_offset <= len(data):
            raise ValueError("snapshot read-only section offsets are invalid")
        if read_only_offset + 8 > shared_heap_offset:
            raise ValueError("snapshot read-only section has no data header")

        magic = int.from_bytes(
            data[read_only_offset : read_only_offset + 4], "little"
        )
        payload_size = int.from_bytes(
            data[read_only_offset + 4 : read_only_offset + 8], "little"
        )
        payload_start = read_only_offset + 8
        payload_end = payload_start + payload_size
        if payload_end > shared_heap_offset:
            raise ValueError("snapshot read-only payload exceeds its section")

        pages, static_roots, roots = cls._parse_heap_image(
            data[payload_start:payload_end], profile, tagged_size
        )
        root_locations = cls._root_locations(
            roots, profile, tagged_size, len(pages)
        )
        if static_roots:
            area_start_offset = profile.static_root_area_start
            if area_start_offset is None:
                raise ValueError("profile does not provide a static-roots page offset")
        else:
            if not root_locations:
                raise ValueError("snapshot does not provide read-only root locations")
            area_start_offset = min(offset for _, offset in root_locations)

        return cls(
            version=version,
            magic=magic,
            checksum=int.from_bytes(data[12:16], "little"),
            profile=profile,
            tagged_size=tagged_size,
            pages=pages,
            area_start_offset=area_start_offset,
            static_roots=static_roots,
            root_locations=root_locations,
        )

    @staticmethod
    def _parse_heap_image(
        payload: bytes, profile: Profile, tagged_size: int
    ) -> tuple[tuple[_Page, ...], bool, tuple[int, ...]]:
        version = tuple(map(int, profile.version.split(".")[:2]))
        if version >= (12, 9):
            return ReadOnlySnapshot._parse_heap_image_layout(
                payload, profile, tagged_size, None
            )
        failures: list[str] = []
        for fixed in (False, True):
            try:
                return ReadOnlySnapshot._parse_heap_image_layout(
                    payload, profile, tagged_size, fixed
                )
            except ValueError as exc:
                failures.append(str(exc))
        raise ValueError(
            "unable to parse read-only snapshot image: " + "; ".join(failures)
        )

    @staticmethod
    def _parse_heap_image_layout(
        payload: bytes,
        profile: Profile,
        tagged_size: int,
        legacy_fixed: bool | None,
    ) -> tuple[tuple[_Page, ...], bool, tuple[int, ...]]:
        reader = _Reader(payload)
        version = tuple(map(int, profile.version.split(".")[:2]))
        modern = version >= (12, 9)
        allocate_at = 1 if modern else None
        segment = 2 if modern else 1
        relocate = 3 if modern else 2
        roots_marker = 4 if modern else 3
        finalize = 5 if modern else 4
        page_data: list[bytearray] = []
        page_present: list[bytearray] = []
        static_roots: bool | None = None
        roots: tuple[int, ...] = ()

        while True:
            opcode = reader.byte()
            if opcode == 0 or (
                allocate_at is not None and opcode == allocate_at
            ):
                fixed = opcode == allocate_at if modern else bool(legacy_fixed)
                if static_roots is None:
                    static_roots = fixed
                elif static_roots != fixed:
                    raise ValueError("snapshot mixes fixed and relocatable read-only pages")
                page_index = reader.uint30()
                area_size = reader.uint30()
                if fixed:
                    reader.uint32()
                if page_index != len(page_data) or area_size > 64 * 1024 * 1024:
                    raise ValueError("snapshot read-only page allocation is invalid")
                page_data.append(bytearray(area_size))
                page_present.append(bytearray(area_size))
                continue
            if opcode == segment:
                page_index = reader.uint30()
                offset = reader.uint30()
                size = reader.uint30()
                if (
                    page_index >= len(page_data)
                    or offset + size > len(page_data[page_index])
                ):
                    raise ValueError("snapshot read-only segment is outside its page")
                raw = reader.raw(size)
                page_data[page_index][offset : offset + size] = raw
                page_present[page_index][offset : offset + size] = b"\x01" * size
                if static_roots is False:
                    if reader.byte() != relocate:
                        raise ValueError("snapshot read-only relocation marker is missing")
                    slots = size // tagged_size
                    reader.raw((slots + 7) // 8)
                continue
            if opcode == roots_marker:
                if static_roots is None:
                    raise ValueError("snapshot contains no read-only pages")
                if not static_roots:
                    remaining = len(payload) - reader.position
                    if remaining < 1 or (remaining - 1) % 4:
                        raise ValueError("snapshot read-only roots table is malformed")
                    roots = tuple(reader.uint32() for _ in range((remaining - 1) // 4))
                if reader.byte() != finalize or reader.position != len(payload):
                    raise ValueError("snapshot read-only image has trailing data")
                break
            if opcode == finalize:
                raise ValueError("snapshot read-only image has no roots table")
            raise ValueError(f"unknown read-only snapshot opcode {opcode}")

        pages = tuple(
            _Page(bytes(data), bytes(present))
            for data, present in zip(page_data, page_present, strict=True)
        )
        return pages, bool(static_roots), roots

    @staticmethod
    def _root_locations(
        roots: tuple[int, ...], profile: Profile, tagged_size: int, page_count: int
    ) -> dict[tuple[int, int], str]:
        if not roots:
            return {}
        version = tuple(map(int, profile.version.split(".")[:2]))
        page_index_bits = 14 if version >= (13, 2) else 5
        page_mask = (1 << page_index_bits) - 1
        locations: dict[tuple[int, int], str] = {}
        for index, encoded in enumerate(roots):
            page = encoded & page_mask
            offset = (encoded >> page_index_bits) * tagged_size
            if page >= page_count:
                raise ValueError("snapshot read-only root points outside its pages")
            name = profile.root_names[index] if index < len(profile.root_names) else ""
            locations[(page, offset)] = name
        return locations

    def string_at(self, page_index: int, chunk_offset: int) -> str | None:
        if not 0 <= page_index < len(self.pages):
            return None
        offset = chunk_offset - self.area_start_offset
        header_size = self.tagged_size + 8
        page = self.pages[page_index]
        if offset < 0 or offset + header_size > len(page.data):
            return None
        if not all(page.present[offset : offset + header_size]):
            return None

        raw_map = int.from_bytes(page.data[offset : offset + 4], "little")
        if self.static_roots:
            map_name = self.profile.static_root_maps.get(raw_map)
        else:
            map_page, map_offset = self._decode_reference(raw_map)
            map_name = self.root_locations.get((map_page, map_offset))
        if map_name is None or not self._is_sequential_string_map(map_name):
            return None

        length_offset = offset + self.tagged_size + 4
        length = int.from_bytes(
            page.data[length_offset : length_offset + 4], "little"
        )
        if length > 16 * 1024 * 1024:
            return None
        width = 1 if "OneByte" in map_name else 2
        data_start = offset + header_size
        data_end = data_start + length * width
        if data_end > len(page.data) or not all(page.present[data_start:data_end]):
            return None
        encoding = "latin-1" if width == 1 else "utf-16-le"
        try:
            return page.data[data_start:data_end].decode(encoding)
        except UnicodeDecodeError:
            return None

    def _decode_reference(self, encoded: int) -> tuple[int, int]:
        version = tuple(map(int, self.profile.version.split(".")[:2]))
        page_index_bits = 14 if version >= (13, 2) else 5
        page_mask = (1 << page_index_bits) - 1
        return encoded & page_mask, (encoded >> page_index_bits) * self.tagged_size

    @staticmethod
    def _is_sequential_string_map(name: str) -> bool:
        if "StringMap" not in name or not (
            "OneByte" in name or "TwoByte" in name
        ):
            return False
        return not any(
            kind in name for kind in ("Cons", "External", "Sliced", "Thin")
        )
