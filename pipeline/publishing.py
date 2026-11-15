"""Shared safe publication and verified raster reading for every pipeline stage (DT-08).

Each stage builds its complete output set in a sibling ``.<name>.staging`` directory and
swaps it into ``<name>`` in one rename; the previous set waits in ``.<name>.previous``
until the swap has succeeded. These helpers make that safe:

- :func:`check_output_dir` refuses to run when the output directory or either sibling holds
  anything the stage does not own. Owned names must be regular files (or a plain owned
  subdirectory of owned files); directories, symlinks and Windows junctions under owned
  names are foreign.
- Nothing is ever deleted recursively. :func:`remove_owned` unlinks owned regular files one
  by one and then removes the emptied directories with ``rmdir``, so an entry that appears
  after the check (a foreign file, directory or link) makes the removal fail instead of
  being deleted. A single publisher per output directory is assumed; concurrent runs are
  refused at the latest by this non-recursive removal.
- :func:`overlapping_input` finds an input that is, or lies inside, the output directory or
  either sibling. For input directories it also checks every entry, resolved, so a link
  inside an input directory that points into a publication path is caught.
  :func:`input_file` restricts manifest-recorded file names to bare names inside their
  input directory, so a manifest cannot point anywhere else.
- :func:`publish` treats the staging rename as the commit point: before it any failure
  restores the previous set and raises; after it a failure to remove the backup only
  returns a message (the backup is kept), because the new set is already in place.
- :func:`read_verified_raster` hashes a file and decodes **the same bytes** in memory, so
  a file replaced between hashing and decoding cannot be read unverified. It is meant for
  interim products (crops and their derivatives, tens of MB); raw multi-GB inputs (full
  GCOV scenes, HDF5, the DEM tile) are still hashed and then opened by path, a documented
  limitation.

Every filesystem failure in these helpers is raised as :class:`PublishError`, which each
stage translates into its own error (CLI exit code 2).
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
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

Subdirs = Mapping[str, Iterable[str]] | None


class PublishError(Exception):
    """Raised when an output set cannot be checked, replaced or read faithfully."""


def staging_dirs(output_dir: Path) -> tuple[Path, Path]:
    """The ``(.<name>.staging, .<name>.previous)`` siblings of ``output_dir``."""
    return (
        output_dir.with_name(f".{output_dir.name}.staging"),
        output_dir.with_name(f".{output_dir.name}.previous"),
    )


def entry_kind(path: Path) -> str:
    """``'file'``, ``'dir'``, ``'link'`` or ``'other'``, never following links/junctions."""
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise PublishError(f"cannot inspect {path.name}: {exc}") from exc
    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        return "link"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    return "file" if stat.S_ISREG(st.st_mode) else "other"


def _listing(directory: Path) -> list[Path]:
    try:
        return sorted(directory.iterdir())
    except OSError as exc:
        raise PublishError(f"cannot list {directory.name}: {exc}") from exc


def _exists(path: Path) -> bool:
    """Like ``os.path.lexists``, but a permission or I/O error is raised, not "missing"."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise PublishError(f"cannot inspect {path.name}: {exc}") from exc
    return True


def _subdirs(subdirs: Subdirs) -> dict[str, frozenset[str]]:
    return {k: frozenset(v) for k, v in (subdirs or {}).items()}


def foreign_entries(directory: Path, owned: Iterable[str], subdirs: Subdirs = None) -> list[str]:
    """Entries of ``directory`` that the stage does not own (``[]`` if it is missing).

    ``owned`` are regular-file names; ``subdirs`` maps an owned plain subdirectory name to
    the regular-file names it may hold. Raises if ``directory`` itself is not plain.
    """
    if not _exists(directory):
        return []
    if entry_kind(directory) != "dir":
        raise PublishError(f"{directory.name} is not a plain directory")
    files, dirs = frozenset(owned), _subdirs(subdirs)
    foreign: list[str] = []
    for entry in _listing(directory):
        kind = entry_kind(entry)
        if entry.name in dirs and kind == "dir":
            foreign += [
                f"{entry.name}/{p.name}"
                for p in _listing(entry)
                if p.name not in dirs[entry.name] or entry_kind(p) != "file"
            ]
        elif entry.name not in files or kind != "file":
            foreign.append(entry.name)
    return sorted(foreign)


def check_output_dir(output_dir: Path, owned: Iterable[str], subdirs: Subdirs = None) -> None:
    """Refuse unless the output and both siblings are missing or hold only owned files."""
    owned = frozenset(owned)
    for path in (output_dir, *staging_dirs(output_dir)):
        foreign = foreign_entries(path, owned, subdirs)
        if foreign:
            raise PublishError(
                f"output_dir {path.name} holds files this stage does not own: {foreign}"
            )


def _identity(path: Path) -> tuple[int, int]:
    """``(st_dev, st_ino)`` of a plain directory, never following links or junctions."""
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise PublishError(f"cannot inspect {path.name}: {exc}") from exc
    if (
        not stat.S_ISDIR(st.st_mode)
        or stat.S_ISLNK(st.st_mode)
        or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT
    ):
        raise PublishError(f"{path.name} is not a plain directory")
    return st.st_dev, st.st_ino


def _still(path: Path, identity: tuple[int, int]) -> None:
    """Fail closed if ``path`` is no longer the directory first inspected."""
    try:
        same = _identity(path) == identity
    except PublishError as exc:
        raise PublishError(
            f"{path.name} changed during removal ({exc}); nothing more was deleted"
        ) from exc
    if not same:
        raise PublishError(f"{path.name} changed during removal; nothing more was deleted")


def remove_owned(directory: Path, owned: Iterable[str], subdirs: Subdirs = None) -> None:
    """Delete an owned set without recursion: unlink owned files, then ``rmdir``.

    Any entry that is not an owned regular file (or owned subdirectory of owned files)
    stops the removal with :class:`PublishError` and is left untouched. ``unlink`` never
    deletes a directory tree and removes a link itself, never its target. The identity
    (device, inode) of each directory is pinned when first inspected and re-checked before
    every deletion inside it, so a directory replaced by a link or junction mid-removal
    stops the removal. Windows Python has no ``dir_fd`` deletion, so a hostile process of the
    same user racing between that re-check and the deletion is outside the threat model
    (one publisher per output directory, nobody else editing it).
    """
    if not _exists(directory):
        return
    root = _identity(directory)
    files, dirs = frozenset(owned), _subdirs(subdirs)
    try:
        for entry in _listing(directory):
            kind = entry_kind(entry)
            if entry.name in dirs and kind == "dir":
                sub = _identity(entry)
                for p in _listing(entry):
                    if p.name not in dirs[entry.name] or entry_kind(p) != "file":
                        raise PublishError(
                            f"{directory.name} holds files this stage does not own: "
                            f"['{entry.name}/{p.name}']"
                        )
                    _still(directory, root)
                    _still(entry, sub)
                    p.unlink()
                _still(directory, root)
                _still(entry, sub)
                entry.rmdir()
            elif entry.name in files and kind == "file":
                _still(directory, root)
                entry.unlink()
            else:
                raise PublishError(
                    f"{directory.name} holds files this stage does not own: ['{entry.name}']"
                )
        _still(directory, root)
        directory.rmdir()
    except OSError as exc:
        raise PublishError(f"cannot remove {directory.name}: {exc}") from exc


def clear_staging(output_dir: Path, owned: Iterable[str], subdirs: Subdirs = None) -> Path:
    """Remove a stale owned staging set and return the staging path."""
    staging, _ = staging_dirs(output_dir)
    remove_owned(staging, owned, subdirs)
    return staging


def discard_staging(staging: Path, owned: Iterable[str], subdirs: Subdirs = None) -> None:
    """Best-effort cleanup of an unpublished staging set; never raises, never recurses."""
    try:
        remove_owned(staging, owned, subdirs)
    except PublishError:
        pass


def input_file(directory: Path, name: object, manifest: str) -> Path:
    """``directory / name`` for a bare manifest-recorded file name; anything else is refused."""
    if (
        not isinstance(name, str)
        or name in ("", ".", "..")
        or Path(name).name != name
        or Path(name).is_absolute()
        or "/" in name
        or "\\" in name
    ):
        raise PublishError(f"{manifest}: file name {name!r} must be a bare name in its directory")
    return directory / name


def overlapping_input(output_dir: Path, inputs: Iterable[Path]) -> Path | None:
    """The first input (file, directory or directory entry) publication could move or delete.

    Publication renames ``output_dir`` and removes its staging/backup siblings, so an input
    is at risk when it **is** one of those three paths or lies **inside** one, after
    resolving links and junctions. Existing input directories are also checked entry by
    entry (resolved). An output nested inside an input directory removes nothing of the
    input and is allowed. Pass raw input files themselves, not their parent directories.
    """
    try:
        paths = (output_dir, *staging_dirs(output_dir))
        targets = [p.resolve() for p in paths]
        own = {os.path.normcase(str(p.absolute())) for p in paths}

        def at_risk(path: Path) -> bool:
            p = path.resolve()
            return any(p == t or p.is_relative_to(t) for t in targets)

        for item in inputs:
            if at_risk(item):
                return item
            if item.is_dir():
                for entry in item.iterdir():
                    # The publication paths themselves may sit in an input directory.
                    is_own = os.path.normcase(str(entry.absolute())) in own
                    if is_own and entry_kind(entry) == "dir":
                        continue
                    if at_risk(entry):
                        return entry
    except OSError as exc:
        raise PublishError(f"cannot check inputs against {output_dir.name}: {exc}") from exc
    return None


def publish(
    staging: Path, output_dir: Path, owned: Iterable[str], subdirs: Subdirs = None
) -> str | None:
    """Swap ``staging`` into ``output_dir``; return a message if only the cleanup failed.

    Before the rename of ``staging`` any failure restores the previous set and raises
    :class:`PublishError`. The rename is the commit point: afterwards a failure to remove
    the backup is only returned (never raised, never a Python warning), and the backup is
    kept for the next run to remove after its ownership check.
    """
    _, previous = staging_dirs(output_dir)
    if _exists(previous) and not _exists(output_dir):
        # An interrupted swap (or a failed rollback) left the last complete set only in the
        # backup: restore it first, so it is never removed before a replacement commits.
        try:
            previous.rename(output_dir)
        except OSError as exc:
            raise PublishError(
                f"cannot restore {previous.name} to {output_dir.name}: {exc}"
            ) from exc
    remove_owned(previous, owned, subdirs)
    try:
        if _exists(output_dir):
            output_dir.rename(previous)
        try:
            staging.rename(output_dir)
        except OSError:
            if _exists(previous) and not _exists(output_dir):
                previous.rename(output_dir)
            raise
    except OSError as exc:
        raise PublishError(f"cannot publish outputs to {output_dir.name}: {exc}") from exc
    try:
        remove_owned(previous, owned, subdirs)
    except PublishError as exc:
        return (
            f"outputs published to {output_dir.name}, but the backup {previous.name} "
            f"was kept: {exc}"
        )
    return None


def report(message: str | None, stage: str) -> None:
    """Print a post-commit cleanup message to stderr (stages call this; never raises)."""
    if message is not None:
        try:
            print(f"{stage} warning: {message}", file=sys.stderr)
        except (OSError, ValueError):
            pass


def read_verified(path: Path, sha256: str, manifest: str, hint: str = "") -> bytes:
    """The bytes of ``path`` if their sha256 matches the manifest record."""
    try:
        if not path.is_file():
            raise PublishError(f"input not found: {path.name}")
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
