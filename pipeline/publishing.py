"""Shared safe publication and verified raster reading for every pipeline stage (DT-08).

Each stage builds its complete output set in a sibling ``.<name>.staging`` directory and
swaps it into ``<name>`` in one rename; the previous set waits in ``.<name>.previous``
until the swap has succeeded. These helpers make that safe:

- :func:`check_output_dir` refuses to run when the output directory or either sibling holds
  anything the stage does not own. Owned names must be regular files (or a plain owned
  subdirectory); directories, symlinks and Windows junctions under owned names are foreign,
  so ``shutil.rmtree`` never deletes something the stage did not write.
- :func:`overlapping_input` finds an input directory that equals, contains or lies inside
  the output directory or either sibling, so no input is ever deleted or replaced.
- :func:`publish` treats the staging rename as the commit point: before it any failure
  restores the previous set and raises; after it a failure to delete the backup is only
  a :class:`PublishWarning` (the backup is kept), because the new set is already in place.
- :func:`read_verified_raster` hashes a file and decodes **the same bytes** in memory, so
  a file replaced between hashing and decoding cannot be read unverified. It is meant for
  interim products (crops and their derivatives, tens of MB); raw multi-GB inputs (full
  GCOV scenes, HDF5) are still hashed and then opened by path, a documented limitation.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.io import MemoryFile

_REPARSE_POINT = 0x400  # Windows FILE_ATTRIBUTE_REPARSE_POINT (symlinks and junctions)


class PublishError(Exception):
    """Raised when an output set cannot be checked, replaced or read faithfully."""


class PublishWarning(UserWarning):
    """The new set is published, but a non-essential cleanup step failed."""


def staging_dirs(output_dir: Path) -> tuple[Path, Path]:
    """The ``(.<name>.staging, .<name>.previous)`` siblings of ``output_dir``."""
    return (
        output_dir.with_name(f".{output_dir.name}.staging"),
        output_dir.with_name(f".{output_dir.name}.previous"),
    )


def entry_kind(path: Path) -> str:
    """``'file'``, ``'dir'``, ``'link'`` or ``'other'``, never following links/junctions."""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        return "link"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    return "file" if stat.S_ISREG(st.st_mode) else "other"


def foreign_entries(
    directory: Path,
    owned: Iterable[str],
    subdirs: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    """Entries of ``directory`` that the stage does not own (``[]`` if it is missing).

    ``owned`` are regular-file names; ``subdirs`` maps an owned plain subdirectory name to
    the regular-file names it may hold. Raises if ``directory`` itself is not plain.
    """
    if not os.path.lexists(directory):
        return []
    if entry_kind(directory) != "dir":
        raise PublishError(f"{directory.name} is not a plain directory")
    files, dirs = frozenset(owned), {k: frozenset(v) for k, v in (subdirs or {}).items()}
    foreign: list[str] = []
    for entry in directory.iterdir():
        kind = entry_kind(entry)
        if entry.name in dirs and kind == "dir":
            foreign += [
                f"{entry.name}/{p.name}"
                for p in entry.iterdir()
                if p.name not in dirs[entry.name] or entry_kind(p) != "file"
            ]
        elif entry.name not in files or kind != "file":
            foreign.append(entry.name)
    return sorted(foreign)


def check_output_dir(
    output_dir: Path,
    owned: Iterable[str],
    subdirs: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """Refuse unless the output and both siblings are missing or hold only owned files."""
    owned = frozenset(owned)
    for path in (output_dir, *staging_dirs(output_dir)):
        foreign = foreign_entries(path, owned, subdirs)
        if foreign:
            raise PublishError(
                f"output_dir {path.name} holds files this stage does not own: {foreign}"
            )


def overlapping_input(output_dir: Path, inputs: Iterable[Path]) -> Path | None:
    """The first input (file or directory) that publication could move or delete.

    Publication renames ``output_dir`` and deletes its staging/backup siblings, so an input
    is at risk when it **is** one of those three paths or lies **inside** one. An output
    nested inside an input directory deletes nothing of the input and is allowed. Pass raw
    input files themselves, not their parent directories.
    """
    targets = [p.resolve() for p in (output_dir, *staging_dirs(output_dir))]
    for item in inputs:
        p = item.resolve()
        if any(p == t or p.is_relative_to(t) for t in targets):
            return item
    return None


def clear_staging(output_dir: Path) -> Path:
    """Remove a stale staging set (ownership already checked) and return the path."""
    staging, _ = staging_dirs(output_dir)
    try:
        if os.path.lexists(staging):
            shutil.rmtree(staging)
    except OSError as exc:
        raise PublishError(f"cannot clear {staging.name}: {exc}") from exc
    return staging


def publish(staging: Path, output_dir: Path) -> str | None:
    """Swap ``staging`` into ``output_dir``; return a warning if only the cleanup failed.

    Before the rename of ``staging`` any failure restores the previous set and raises
    :class:`PublishError`. The rename is the commit point: afterwards a failure to delete
    the backup returns a message (also emitted as :class:`PublishWarning`), and the backup
    is kept for the next run to remove after its ownership check.
    """
    _, previous = staging_dirs(output_dir)
    try:
        if os.path.lexists(previous):
            shutil.rmtree(previous)  # ownership checked by check_output_dir
        if os.path.lexists(output_dir):
            output_dir.rename(previous)
        try:
            staging.rename(output_dir)
        except OSError:
            if os.path.lexists(previous) and not os.path.lexists(output_dir):
                previous.rename(output_dir)
            raise
    except OSError as exc:
        raise PublishError(f"cannot publish outputs to {output_dir.name}: {exc}") from exc
    if os.path.lexists(previous):
        try:
            shutil.rmtree(previous)
        except OSError as exc:
            message = (
                f"outputs published to {output_dir.name}, but the backup {previous.name} "
                f"was kept: {exc}"
            )
            warnings.warn(message, PublishWarning, stacklevel=2)
            return message
    return None


def read_verified(path: Path, sha256: str, manifest: str, hint: str = "") -> bytes:
    """The bytes of ``path`` if their sha256 matches the manifest record."""
    if not path.is_file():
        raise PublishError(f"input not found: {path.name}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise PublishError(f"{path.name}: cannot read: {exc}") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != sha256:
        raise PublishError(
            f"{path.name}: sha256 {actual[:12]}... differs from {manifest} {sha256[:12]}..."
            f"{'; ' + hint if hint else ''}"
        )
    return payload


@dataclass(frozen=True)
class DecodedRaster:
    """A single-band raster decoded from verified bytes."""

    data: np.ndarray
    dtype: str
    count: int
    crs: CRS | None
    transform: Affine
    nodata: float | None
    height: int
    width: int


def decode_raster(payload: bytes, name: str) -> DecodedRaster:
    """Decode GeoTIFF bytes in memory (band 1); never touches the original path."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with MemoryFile(payload) as mem, mem.open() as ds:
                return DecodedRaster(
                    data=ds.read(1),
                    dtype=ds.dtypes[0],
                    count=ds.count,
                    crs=ds.crs,
                    transform=ds.transform,
                    nodata=ds.nodata,
                    height=ds.height,
                    width=ds.width,
                )
    except (RasterioError, OSError) as exc:
        raise PublishError(f"{name}: cannot read raster: {exc}") from exc


def read_verified_raster(path: Path, sha256: str, manifest: str, hint: str = "") -> DecodedRaster:
    """Hash ``path`` and decode exactly the bytes that were hashed."""
    return decode_raster(read_verified(path, sha256, manifest, hint), path.name)
