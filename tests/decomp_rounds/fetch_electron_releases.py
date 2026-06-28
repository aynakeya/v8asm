#!/usr/bin/env python3
"""Fetch Electron release zips into the local electron-cache.

The Electron validation matrix intentionally consumes only local releases. This
helper fills that cache without changing matrix matching rules: after a release
is unpacked, check_electron_version_matrix.py still reads process.versions.v8
and selects only exactly matching Electron-flavored v8asm binaries.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_CACHE = Path("/home/aynakeya/workspace/tmp/v8test/electron-cache")
DEFAULT_PLATFORM = "linux"
DEFAULT_ARCH = "x64"
DEFAULT_BASE_URL = "https://github.com/electron/electron/releases/download"


def normalize_version(version: str) -> str:
    return version[1:] if version.startswith("v") else version


def release_names(version: str, platform: str, arch: str) -> tuple[str, str]:
    normalized = normalize_version(version)
    archive = f"electron-v{normalized}-{platform}-{arch}.zip"
    directory = f"v{normalized}-{platform}-{arch}"
    return archive, directory


def release_url(base_url: str, version: str, archive: str) -> str:
    normalized = normalize_version(version)
    return f"{base_url.rstrip('/')}/v{normalized}/{archive}"


def required_files(dest: Path) -> tuple[Path, Path, Path]:
    return (
        dest / "electron",
        dest / "snapshot_blob.bin",
        dest / "v8_context_snapshot.bin",
    )


def is_complete_release(dest: Path) -> bool:
    return all(path.is_file() for path in required_files(dest))


def make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with urllib.request.urlopen(url) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        tmp.replace(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def unpack(archive: Path, dest: Path) -> None:
    if dest.exists():
        if is_complete_release(dest):
            return
        raise RuntimeError(f"refusing to overwrite incomplete Electron cache: {dest}")

    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        raise RuntimeError(f"temporary unpack directory already exists: {tmp}")
    tmp.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        if not is_complete_release(tmp):
            missing = [str(path.relative_to(tmp)) for path in required_files(tmp) if not path.exists()]
            raise RuntimeError(f"{archive.name} missing required files: {', '.join(missing)}")
        make_executable(tmp / "electron")
        tmp.rename(dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def fetch_one(version: str, args: argparse.Namespace) -> str:
    archive_name, dir_name = release_names(version, args.platform, args.arch)
    archive = args.cache / archive_name
    dest = args.cache / dir_name

    if is_complete_release(dest):
        return f"{dir_name}: present"

    if not archive.exists():
        url = release_url(args.base_url, version, archive_name)
        if args.dry_run:
            return f"{dir_name}: would download {url}"
        download(url, archive)
    elif args.dry_run:
        return f"{dir_name}: would unpack {archive}"

    unpack(archive, dest)
    return f"{dir_name}: ready"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("versions", nargs="+", help="Electron versions, with or without leading v")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--platform", default=DEFAULT_PLATFORM)
    parser.add_argument("--arch", default=DEFAULT_ARCH)
    parser.add_argument("--base-url", default=os.environ.get("ELECTRON_RELEASE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.cache = args.cache.resolve()

    failures: list[str] = []
    for version in args.versions:
        try:
            print(fetch_one(version, args))
        except Exception as exc:
            failures.append(f"{version}: {exc}")

    if failures:
        print("fetch_electron_failures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
