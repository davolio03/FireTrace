"""Shared safe publication and verified raster reading for every pipeline stage (DT-08).

Each stage builds its complete output set in a sibling ``.<name>.staging`` directory and
swaps it into ``<name>`` in one rename; the previous set waits in ``.<name>.previous``
until the swap has succeeded. These helpers make that safe:

- :func:`check_output_dir` refuses to run when the output directory or either sibling holds
  anything the stage does not own. Ownership is a :class:`Tree` of names: owned regular
  files, owned plain subdirectories by name, and (for tile pyramids, DT-09) files and
  subdirectories whose names match a fixed pattern at a fixed depth. It is decided from
  names and entry kinds only, never from a manifest inside the tree. Directories, symlinks
  and Windows junctions under owned names are foreign.
- Nothing is ever deleted recursively. :func:`remove_owned` unlinks owned regular files one
  by one and then removes the emptied directories bottom-up with ``rmdir``, re-checking the
  identity of every directory on the path before each deletion, so an entry that appears
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
import re
import stat
import sys
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.io import MemoryFile

_REPARSE_POINT = 0x400  # Windows FILE_ATTRIBUTE_REPARSE_POINT (symlinks and junctions)


class PublishError(Exception):
    """Raised when an output set cannot be checked, replaced or read faithfully."""


@dataclass(frozen=True)
class Tree:
    """What a stage owns inside one directory.

    ``files`` are owned regular-file names and ``dirs`` maps an owned plain subdirectory
    name to what it may hold. ``file_pattern`` owns any regular file, and ``dir_pattern``
    any plain subdirectory (holding ``pattern_child``), whose whole name matches the
    pattern (ASCII regular expression). Everything else is foreign.
    """

    files: frozenset[str] = frozenset()
    dirs: Mapping[str, Tree] = field(default_factory=dict)
    file_pattern: str | None = None
    dir_pattern: str | None = None
    pattern_child: Tree | None = None

    def __post_init__(self) -> None:
        if (self.dir_pattern is None) != (self.pattern_child is None):
            raise ValueError("dir_pattern and pattern_child go together")
        object.__setattr__(self, "files", frozenset(self.files))
        object.__setattr__(self, "dirs", dict(self.dirs))

    def child(self, name: str, kind: str) -> Tree | None:
        """The spec of an owned subdirectory ``name`` of this kind, else None."""
        if kind != "dir":
            return None
        if name in self.dirs:
            return self.dirs[name]
        if self.dir_pattern is not None and re.fullmatch(self.dir_pattern, name, re.ASCII):
            return self.pattern_child
        return None

    def owns_file(self, name: str, kind: str) -> bool:
        """Whether ``name`` of this kind is an owned regular file."""
        if kind != "file" or name in self.dirs:
            return False
        if name in self.files:
            return True
        return self.file_pattern is not None and bool(
            re.fullmatch(self.file_pattern, name, re.ASCII)
        )


Owned = Iterable[str] | Tree
Subdirs = Mapping[str, Iterable[str] | Tree] | None


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


def tree(owned: Owned, subdirs: Subdirs = None) -> Tree:
    """The ownership :class:`Tree` for ``owned`` names plus fixed-name ``subdirs``.

    ``owned`` may already be a :class:`Tree` (then ``subdirs`` must be empty); a ``subdirs``
    value is either the regular-file names of that subdirectory or a :class:`Tree`.
    """
    if isinstance(owned, Tree):
        if subdirs:
            raise ValueError("pass subdirs inside the Tree")
        return owned
    if isinstance(owned, str):
        raise TypeError("owned must be a collection of names, not one string")
    dirs = {
        name: spec if isinstance(spec, Tree) else Tree(files=frozenset(spec))
        for name, spec in (subdirs or {}).items()
    }
    return Tree(files=frozenset(owned), dirs=dirs)


def _walk(directory: Path, spec: Tree, prefix: str, owned: list[str], foreign: list[str]) -> None:
    for entry in _listing(directory):
        kind = entry_kind(entry)
        sub = spec.child(entry.name, kind)
        if sub is not None:
            _walk(entry, sub, f"{prefix}{entry.name}/", owned, foreign)
        elif spec.owns_file(entry.name, kind):
            owned.append(prefix + entry.name)
        else:
            foreign.append(prefix + entry.name)


def _plain_dir(directory: Path) -> bool:
    """False if missing; raises if ``directory`` exists but is not a plain directory."""
    if not _exists(directory):
        return False
    if entry_kind(directory) != "dir":
        raise PublishError(f"{directory.name} is not a plain directory")
    return True


def foreign_entries(directory: Path, owned: Owned, subdirs: Subdirs = None) -> list[str]:
    """Entries of ``directory`` that the stage does not own (``[]`` if it is missing).

    Paths are relative, with ``/`` separators. Raises if ``directory`` itself is not plain.
    """
    if not _plain_dir(directory):
        return []
    found: list[str] = []
    foreign: list[str] = []
    _walk(directory, tree(owned, subdirs), "", found, foreign)
    return sorted(foreign)


def owned_files(directory: Path, owned: Owned, subdirs: Subdirs = None) -> list[str]:
    """Every owned regular file under ``directory`` (relative, ``/``-separated, sorted).

    Raises :class:`PublishError` if ``directory`` is missing, not plain or holds anything
    foreign, so a verified input tree can be compared with its manifest file by file.
    """
    if not _plain_dir(directory):
        raise PublishError(f"input not found: {directory.name}")
    found: list[str] = []
    foreign: list[str] = []
    _walk(directory, tree(owned, subdirs), "", found, foreign)
    if foreign:
        raise PublishError(
            f"{directory.name} holds entries that are not expected: {sorted(foreign)}"
        )
    return sorted(found)


def check_output_dir(output_dir: Path, owned: Owned, subdirs: Subdirs = None) -> None:
    """Refuse unless the output and both siblings are missing or hold only owned files."""
    spec = tree(owned, subdirs)
    for path in (output_dir, *staging_dirs(output_dir)):
        foreign = foreign_entries(path, spec)
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


def _still_all(chain: Sequence[tuple[Path, tuple[int, int]]]) -> None:
    """Re-check every directory from the removal root down to the current one."""
    for path, identity in chain:
        _still(path, identity)


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


def remove_owned(directory: Path, owned: Owned, subdirs: Subdirs = None) -> None:
    """Delete an owned set without recursion: unlink owned files, then ``rmdir`` bottom-up.

    Any entry that is not owned (see :class:`Tree`) stops the removal with
    :class:`PublishError` and is left untouched. ``unlink`` never deletes a directory tree
    and removes a link itself, never its target. The identity (device, inode) of each
    directory is pinned when first inspected, and every directory from ``directory`` down to
    the one being emptied is re-checked before each deletion, so a directory replaced by a
    link or junction mid-removal stops the removal. Windows Python has no ``dir_fd``
    deletion, so a hostile process of the same user racing between that re-check and the
    deletion is outside the threat model (one publisher per output directory, nobody else
    editing it).
    """
    if not _exists(directory):
        return
    spec = tree(owned, subdirs)
    try:
        _remove(directory, spec, [(directory, _identity(directory))], "")
    except OSError as exc:
        raise PublishError(f"cannot remove {directory.name}: {exc}") from exc


def _remove(
    directory: Path, spec: Tree, chain: list[tuple[Path, tuple[int, int]]], prefix: str
) -> None:
    root = chain[0][0]
    for entry in _listing(directory):
        kind = entry_kind(entry)
        sub = spec.child(entry.name, kind)
        if sub is not None:
            _remove(entry, sub, [*chain, (entry, _identity(entry))], f"{prefix}{entry.name}/")
        elif spec.owns_file(entry.name, kind):
            _still_all(chain)
            entry.unlink()
        else:
            raise PublishError(
                f"{root.name} holds files this stage does not own: ['{prefix}{entry.name}']"
            )
    _still_all(chain)
    directory.rmdir()


def clear_staging(output_dir: Path, owned: Owned, subdirs: Subdirs = None) -> Path:
    """Remove a stale owned staging set and return the staging path."""
    staging, _ = staging_dirs(output_dir)
    remove_owned(staging, owned, subdirs)
    return staging


def discard_staging(staging: Path, owned: Owned, subdirs: Subdirs = None) -> None:
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


def publish(staging: Path, output_dir: Path, owned: Owned, subdirs: Subdirs = None) -> str | None:
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
