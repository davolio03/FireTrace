"""Shared safe publication and verified raster reading (DT-08).

Directory, symlink and junction cases, the rename commit point and the hash/decode
snapshot, on tiny synthetic files only.
"""

from __future__ import annotations

import hashlib
import os
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from affine import Affine
from rasterio.crs import CRS

from pipeline import publishing
from pipeline.publishing import (
    PublishError,
    check_output_dir,
    clear_staging,
    decode_raster,
    discard_staging,
    foreign_entries,
    input_file,
    overlapping_input,
    publish,
    read_verified,
    read_verified_raster,
    remove_owned,
    staging_dirs,
)
from pipeline.sar import write_cog

UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 600_000.0, 0.0, -10.0, 3_970_000.0)
OWNED = frozenset({"a.json", "b.tif"})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _junction(target: Path, link: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    winapi.CreateJunction(str(target), str(link))


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except OSError:
        pytest.skip("symlinks are not available on this system")


def locked_after_commit(previous: Path) -> Any:
    """remove_owned that fails on the backup once it holds the replaced set."""
    real = publishing.remove_owned

    def locked(directory: Path, *args: Any, **kwargs: Any) -> None:
        if directory == previous and directory.exists():
            raise PublishError("backup locked")
        real(directory, *args, **kwargs)

    return locked


def _set(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "a.json").write_text(text, encoding="utf-8")
    (directory / "b.tif").write_bytes(text.encode())
    return directory


# --------------------------------------------------------------------------- ownership


def test_staging_dirs_are_hidden_siblings(tmp_path: Path):
    staging, previous = staging_dirs(tmp_path / "sar")
    assert (staging.name, previous.name) == (".sar.staging", ".sar.previous")
    assert staging.parent == previous.parent == tmp_path


def test_missing_and_fully_owned_directories_have_nothing_foreign(tmp_path: Path):
    assert foreign_entries(tmp_path / "nope", OWNED) == []
    assert foreign_entries(_set(tmp_path / "out", "x"), OWNED) == []


def test_unknown_names_and_directories_under_owned_names_are_foreign(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "notes.txt").write_text("mine", encoding="utf-8")
    (out / "a.json").mkdir()  # an owned *file* name used by a directory
    (out / "a.json" / "keep.txt").write_text("mine", encoding="utf-8")
    assert foreign_entries(out, OWNED) == ["a.json", "notes.txt"]


def test_owned_subdirectory_entries_must_be_owned_regular_files(tmp_path: Path):
    out = tmp_path / "out"
    (out / "layers" / "x.png").mkdir(parents=True)
    (out / "layers" / "other.png").write_bytes(b"x")
    found = foreign_entries(out, OWNED, {"layers": {"x.png", "y.png"}})
    assert found == ["layers/other.png", "layers/x.png"]


def test_junction_under_an_owned_name_is_foreign(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    _junction(elsewhere, out / "a.json")
    assert foreign_entries(out, OWNED) == ["a.json"]


def test_symlink_under_an_owned_name_is_foreign(tmp_path: Path):
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    _symlink(target, out / "a.json")
    assert foreign_entries(out, OWNED) == ["a.json"]


def test_output_dir_that_is_a_file_or_junction_is_refused(tmp_path: Path):
    (tmp_path / "file").write_text("x", encoding="utf-8")
    with pytest.raises(PublishError, match="not a plain directory"):
        foreign_entries(tmp_path / "file", OWNED)
    target = _set(tmp_path / "target", "x")
    _junction(target, tmp_path / "linked")
    with pytest.raises(PublishError, match="not a plain directory"):
        foreign_entries(tmp_path / "linked", OWNED)


@pytest.mark.parametrize("which", [0, 1, 2])
def test_check_output_dir_covers_the_staging_and_backup_siblings(tmp_path: Path, which: int):
    out = tmp_path / "out"
    path = (out, *staging_dirs(out))[which]
    path.mkdir()
    (path / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(PublishError, match=f"{path.name} holds files this stage does not own"):
        check_output_dir(out, OWNED)
    assert (path / "notes.txt").is_file()


# --------------------------------------------------------------------------- overlap


def test_inputs_at_or_inside_a_publication_path_are_reported(tmp_path: Path):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    assert overlapping_input(out, [tmp_path / "in", out]) == out
    assert overlapping_input(out, [staging]) == staging
    assert overlapping_input(out, [previous / "deep" / "raw.tif"]) == previous / "deep" / "raw.tif"
    assert overlapping_input(out, [out / "raw.geojson"]) == out / "raw.geojson"


def test_unrelated_inputs_and_an_output_nested_in_an_input_are_allowed(tmp_path: Path):
    out = tmp_path / "data" / "interim" / "x"
    assert overlapping_input(out, [tmp_path / "data" / "interim" / "nisar"]) is None
    # Publishing inside an input directory moves or deletes nothing of that input.
    assert overlapping_input(out, [tmp_path / "data"]) is None
    assert overlapping_input(out, [tmp_path / "data" / "raw" / "wfigs.geojson"]) is None


def test_overlap_follows_aliases(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    _junction(out, tmp_path / "alias")
    assert overlapping_input(out, [tmp_path / "alias"]) == tmp_path / "alias"


# --------------------------------------------------------------------------- publish


def test_first_publish_and_replacement(tmp_path: Path):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    assert publish(_set(staging, "one"), out, OWNED) is None
    assert (out / "a.json").read_text(encoding="utf-8") == "one"
    assert publish(_set(staging, "two"), out, OWNED) is None
    assert (out / "a.json").read_text(encoding="utf-8") == "two"
    assert not staging.exists() and not previous.exists()


def test_stale_backup_is_replaced(tmp_path: Path):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    _set(out, "current")
    _set(previous, "stale")
    publish(_set(staging, "new"), out, OWNED)
    assert (out / "a.json").read_text(encoding="utf-8") == "new"
    assert not previous.exists()


def test_failed_swap_restores_the_previous_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    _set(out, "old")
    real = Path.rename

    def blocked(self: Path, target: Any) -> Any:
        if self.name == staging.name:
            raise OSError("rename blocked")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", blocked)
    with pytest.raises(PublishError, match="rename blocked"):
        publish(_set(staging, "new"), out, OWNED)
    assert (out / "a.json").read_text(encoding="utf-8") == "old"
    assert not previous.exists()


def test_backup_cleanup_failure_after_the_commit_is_only_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    _set(out, "old")
    monkeypatch.setattr(publishing, "remove_owned", locked_after_commit(previous))
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a post-commit problem must never raise
        message = publish(_set(staging, "new"), out, OWNED)
    assert message is not None and "kept" in message and "backup locked" in message
    assert (out / "a.json").read_text(encoding="utf-8") == "new", "the new set is published"
    assert (previous / "a.json").read_text(encoding="utf-8") == "old", "and the backup kept"


# --------------------------------------------------------------------------- verified reads


def test_read_verified_reports_mismatch_and_missing_files(tmp_path: Path):
    path = tmp_path / "x.tif"
    path.write_bytes(b"payload")
    assert read_verified(path, _sha(path), "m.json") == b"payload"
    with pytest.raises(PublishError, match=r"x.tif: sha256 .* differs from m.json .*; re-run it"):
        read_verified(path, "0" * 64, "m.json", "re-run it")
    with pytest.raises(PublishError, match="input not found: y.tif"):
        read_verified(tmp_path / "y.tif", "0" * 64, "m.json")


def test_raster_is_decoded_from_the_hashed_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "x.tif"
    original = np.arange(12, dtype=np.float32).reshape(3, 4)
    write_cog(path, original, crs=UTM10N, transform=TRANSFORM, nodata=np.nan)
    sha = _sha(path)
    real = Path.read_bytes
    swapped: list[Path] = []

    def racing(self: Path) -> bytes:
        payload = real(self)
        if self == path and not swapped:  # replaced right after it is read and hashed
            swapped.append(self)
            write_cog(path, original + 100, crs=UTM10N, transform=TRANSFORM, nodata=np.nan)
        return payload

    monkeypatch.setattr(Path, "read_bytes", racing)
    raster = read_verified_raster(path, sha, "m.json")
    assert swapped == [path]
    np.testing.assert_array_equal(raster.data, original)
    assert raster.crs == UTM10N and raster.transform == TRANSFORM
    assert (raster.count, raster.dtype, raster.height, raster.width) == (1, "float32", 3, 4)


def test_decode_raster_rejects_garbage():
    with pytest.raises(PublishError, match="bad.tif: cannot read raster"):
        decode_raster(b"not a tiff", "bad.tif")


# --------------------------------------------------------------------------- review round 2


def test_remove_owned_deletes_only_owned_files_without_recursion(tmp_path: Path):
    out = _set(tmp_path / "out", "x")
    (out / "layers").mkdir()
    (out / "layers" / "p.png").write_bytes(b"x")
    remove_owned(out, OWNED, {"layers": {"p.png"}})
    assert not out.exists()


def test_remove_owned_leaves_a_late_foreign_tree_intact(tmp_path: Path):
    out = _set(tmp_path / "out", "x")
    (out / "b.tif").unlink()
    (out / "b.tif").mkdir()  # appears after any earlier ownership check
    (out / "b.tif" / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(PublishError, match="does not own"):
        remove_owned(out, OWNED)
    assert (out / "b.tif" / "keep.txt").is_file()


def test_remove_owned_never_follows_a_junction(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.json").write_text("precious", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    _junction(elsewhere, out / "layers")
    with pytest.raises(PublishError, match="does not own"):
        remove_owned(out, OWNED, {"layers": {"a.json"}})
    assert (elsewhere / "a.json").read_text(encoding="utf-8") == "precious"


def test_stale_staging_with_foreign_content_is_kept(tmp_path: Path):
    out = tmp_path / "out"
    staging, _ = staging_dirs(out)
    staging.mkdir()
    (staging / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(PublishError, match="does not own"):
        clear_staging(out, OWNED)
    discard_staging(staging, OWNED)  # best effort: no exception, nothing foreign removed
    assert (staging / "notes.txt").is_file()


def test_backup_with_foreign_content_stops_publication_before_the_swap(tmp_path: Path):
    out = _set(tmp_path / "out", "old")
    staging, previous = staging_dirs(out)
    previous.mkdir()
    (previous / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(PublishError, match="does not own"):
        publish(_set(staging, "new"), out, OWNED)
    assert (out / "a.json").read_text(encoding="utf-8") == "old"
    assert (previous / "notes.txt").is_file()


@pytest.mark.parametrize(
    "name", ["../x.tif", "/abs/x.tif", "C:\\x.tif", "sub/x.tif", "sub\\x.tif", "", "..", 3]
)
def test_input_file_accepts_only_bare_names(tmp_path: Path, name: object):
    with pytest.raises(PublishError, match="bare name"):
        input_file(tmp_path, name, "m.json")
    assert input_file(tmp_path, "x.tif", "m.json") == tmp_path / "x.tif"


def test_link_inside_an_input_directory_into_staging_is_caught(tmp_path: Path):
    out = tmp_path / "out"
    staging, _ = staging_dirs(out)
    staging.mkdir()
    inputs = tmp_path / "in"
    inputs.mkdir()
    _junction(staging, inputs / "crops")
    assert overlapping_input(out, [inputs]) == inputs / "crops"


def test_output_directly_inside_an_input_directory_is_allowed(tmp_path: Path):
    parent = tmp_path / "data"
    out = parent / "out"
    out.mkdir(parents=True)
    staging_dirs(out)[0].mkdir()
    assert overlapping_input(out, [parent]) is None


def test_filesystem_errors_become_publish_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = _set(tmp_path / "out", "x")

    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("access denied")

    monkeypatch.setattr(publishing.os, "lstat", denied)
    with pytest.raises(PublishError, match="access denied"):
        check_output_dir(out, OWNED)
    with pytest.raises(PublishError, match="access denied"):
        remove_owned(out, OWNED)


# --------------------------------------------------------------------------- review round 3


def test_directory_swapped_for_a_junction_mid_removal_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    winapi = pytest.importorskip("_winapi")
    out = _set(tmp_path / "out", "x")
    elsewhere = _set(tmp_path / "elsewhere", "precious")
    real = Path.unlink
    swapped: list[Path] = []

    def swap_after_first(self: Path, *args: Any, **kwargs: Any) -> None:
        real(self, *args, **kwargs)
        if not swapped:  # after deleting a.json, replace "out" by a junction
            swapped.append(self)
            out.rename(tmp_path / "out_moved")
            winapi.CreateJunction(str(elsewhere), str(out))

    monkeypatch.setattr(Path, "unlink", swap_after_first)
    with pytest.raises(PublishError, match="changed during removal"):
        remove_owned(out, OWNED)
    assert swapped
    assert (elsewhere / "a.json").read_text(encoding="utf-8") == "precious"
    assert (elsewhere / "b.tif").read_bytes() == b"precious"


def test_backup_is_restored_when_the_output_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    _set(previous, "last complete")  # an interrupted swap left only the backup
    real = Path.rename

    def blocked(self: Path, target: Any) -> Any:
        if self.name == staging.name:
            raise OSError("rename blocked")
        return real(self, target)

    _set(staging, "new")
    with monkeypatch.context() as mp:
        mp.setattr(Path, "rename", blocked)
        with pytest.raises(PublishError, match="rename blocked"):
            publish(staging, out, OWNED)
    assert (out / "a.json").read_text(encoding="utf-8") == "last complete", "nothing lost"
    assert not previous.exists()
    assert publish(staging, out, OWNED) is None
    assert (out / "a.json").read_text(encoding="utf-8") == "new"
    assert not previous.exists()


def test_permission_error_on_an_input_is_a_publish_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "x.tif"
    path.write_bytes(b"x")

    def denied(self: Path) -> bool:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "is_file", denied)
    with pytest.raises(PublishError, match="access denied"):
        read_verified(path, _sha(path), "m.json")


# --------------------------------------------------------------------------- nested trees (DT-09)

NUM = r"0|[1-9][0-9]*"
PYRAMID = publishing.Tree(
    files=frozenset({"tiles.json"}),
    dir_pattern=NUM,
    pattern_child=publishing.Tree(
        dir_pattern=NUM, pattern_child=publishing.Tree(file_pattern=rf"(?:{NUM})\.png")
    ),
)
BUNDLE = {"layers": {"p.png"}, "terrain": PYRAMID}


def _pyramid(directory: Path, tiles: tuple[str, ...] = ("8/41/100.png", "9/83/200.png")) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tiles.json").write_text("{}", encoding="utf-8")
    for name in tiles:
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(name.encode())
    return directory


def _bundle(directory: Path, tiles: tuple[str, ...] = ("8/41/100.png", "9/83/200.png")) -> Path:
    _set(directory, "x")
    (directory / "layers").mkdir()
    (directory / "layers" / "p.png").write_bytes(b"p")
    _pyramid(directory / "terrain", tiles)
    return directory


def test_tree_owns_pattern_files_and_dirs_at_their_depth_only(tmp_path: Path):
    out = _bundle(tmp_path / "out")
    assert foreign_entries(out, OWNED, BUNDLE) == []
    assert list(publishing.read_owned_tree(out / "terrain", PYRAMID)) == [
        "8/41/100.png",
        "9/83/200.png",
        "tiles.json",
    ]
    for name in (
        "terrain/8/41/x.png",  # not a number
        "terrain/8/41/007.png",  # not canonical
        "terrain/8/100.png",  # too shallow
        "terrain/8/41/1/100.png",  # too deep
        "terrain/x/41/100.png",
        "terrain/notes.txt",
        "terrain/8/tiles.json",
    ):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"?")
    assert foreign_entries(out, OWNED, BUNDLE) == sorted(
        [
            "terrain/8/41/x.png",
            "terrain/8/41/007.png",
            "terrain/8/100.png",
            "terrain/8/41/1",
            "terrain/x",
            "terrain/notes.txt",
            "terrain/8/tiles.json",
        ]
    )


def test_unicode_digits_are_not_owned(tmp_path: Path):
    out = _pyramid(tmp_path / "t")
    (out / "١").mkdir()  # ARABIC-INDIC DIGIT ONE
    assert foreign_entries(out, PYRAMID) == ["١"]


def test_directory_under_a_tile_name_and_file_under_a_dir_name_are_foreign(tmp_path: Path):
    out = _pyramid(tmp_path / "t", ())
    (out / "8").write_bytes(b"not a dir")
    (out / "9" / "83" / "200.png").mkdir(parents=True)
    assert foreign_entries(out, PYRAMID) == ["8", "9/83/200.png"]
    with pytest.raises(PublishError, match="not expected"):
        publishing.read_owned_tree(out, PYRAMID)


def test_junction_inside_the_tree_is_foreign_and_never_followed(tmp_path: Path):
    elsewhere = _pyramid(tmp_path / "elsewhere", ("8/41/100.png",))
    out = _pyramid(tmp_path / "out" / "terrain", ("9/83/200.png",))
    _junction(elsewhere / "8", out / "8")
    assert foreign_entries(out, PYRAMID) == ["8"]
    with pytest.raises(PublishError, match="does not own"):
        remove_owned(out, PYRAMID)
    assert (elsewhere / "8" / "41" / "100.png").read_bytes() == b"8/41/100.png"


def test_symlinked_tile_is_foreign(tmp_path: Path):
    out = _pyramid(tmp_path / "t", ())
    (out / "8" / "41").mkdir(parents=True)
    target = tmp_path / "secret.png"
    target.write_bytes(b"secret")
    _symlink(target, out / "8" / "41" / "100.png")
    assert foreign_entries(out, PYRAMID) == ["8/41/100.png"]


def test_remove_owned_empties_a_nested_tree_bottom_up(tmp_path: Path):
    out = _bundle(tmp_path / "out")
    remove_owned(out, OWNED, BUNDLE)
    assert not out.exists()


def test_late_foreign_file_deep_in_the_tree_stops_removal(tmp_path: Path):
    out = _bundle(tmp_path / "out")
    (out / "terrain" / "9" / "83" / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(PublishError, match=r"\['terrain/9/83/keep.txt'\]"):
        remove_owned(out, OWNED, BUNDLE)
    assert (out / "terrain" / "9" / "83" / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_ancestor_swapped_for_a_junction_mid_removal_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    winapi = pytest.importorskip("_winapi")
    out = _pyramid(tmp_path / "out", ("8/41/100.png", "8/41/101.png"))
    elsewhere = _pyramid(tmp_path / "elsewhere", ("8/41/100.png", "8/41/101.png"))
    real = Path.unlink
    swapped: list[Path] = []

    def swap_level_one(self: Path, *args: Any, **kwargs: Any) -> None:
        real(self, *args, **kwargs)
        if not swapped:  # after the first tile, replace "out/8" (an ancestor) by a junction
            swapped.append(self)
            (out / "8").rename(tmp_path / "moved")
            winapi.CreateJunction(str(elsewhere / "8"), str(out / "8"))

    monkeypatch.setattr(Path, "unlink", swap_level_one)
    with pytest.raises(PublishError, match="changed during removal"):
        remove_owned(out, PYRAMID)
    assert swapped
    assert sorted(p.name for p in (elsewhere / "8" / "41").iterdir()) == ["100.png", "101.png"]


def test_publish_replaces_a_bundle_with_a_different_tile_set(tmp_path: Path):
    out = _bundle(tmp_path / "out", ("8/41/100.png", "9/83/200.png"))
    staging, previous = staging_dirs(out)
    _bundle(staging, ("10/166/401.png",))
    assert publish(staging, out, OWNED, BUNDLE) is None
    assert list(publishing.read_owned_tree(out / "terrain", PYRAMID)) == [
        "10/166/401.png",
        "tiles.json",
    ]
    assert not previous.exists() and not staging.exists()


def test_interrupted_nested_swap_restores_the_last_complete_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    out = tmp_path / "out"
    staging, previous = staging_dirs(out)
    _bundle(previous, ("8/41/100.png",))  # an interrupted swap left only the backup
    _bundle(staging, ("9/83/200.png",))
    real = Path.rename

    def blocked(self: Path, target: Any) -> Any:
        if self.name == staging.name:
            raise OSError("rename blocked")
        return real(self, target)

    with monkeypatch.context() as mp:
        mp.setattr(Path, "rename", blocked)
        with pytest.raises(PublishError, match="rename blocked"):
            publish(staging, out, OWNED, BUNDLE)
    assert (out / "terrain" / "8" / "41" / "100.png").is_file(), "nothing lost"
    assert publish(staging, out, OWNED, BUNDLE) is None
    assert list(publishing.read_owned_tree(out / "terrain", PYRAMID)) == [
        "9/83/200.png",
        "tiles.json",
    ]


def test_tree_rejects_ambiguous_specs():
    with pytest.raises(ValueError):
        publishing.Tree(dir_pattern=NUM)
    with pytest.raises(ValueError):
        publishing.tree(PYRAMID, {"layers": {"p.png"}})
    with pytest.raises(TypeError):
        publishing.tree("a.json")


def test_read_owned_tree_requires_a_plain_existing_directory(tmp_path: Path):
    with pytest.raises(PublishError, match="not found"):
        publishing.read_owned_tree(tmp_path / "missing", PYRAMID)


# --------------------------------------------------------------------------- review round 1 (DT-09)


def test_read_owned_tree_returns_the_bytes_it_walked(tmp_path: Path):
    out = _pyramid(tmp_path / "t")
    assert publishing.read_owned_tree(out, PYRAMID) == {
        "8/41/100.png": b"8/41/100.png",
        "9/83/200.png": b"9/83/200.png",
        "tiles.json": b"{}",
    }


def test_read_owned_tree_caps_the_number_of_files(tmp_path: Path):
    out = _pyramid(tmp_path / "t")
    with pytest.raises(PublishError, match="more than 2 files"):
        publishing.read_owned_tree(out, PYRAMID, max_files=2)


def test_directory_swapped_for_a_junction_during_reading_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    winapi = pytest.importorskip("_winapi")
    out = _pyramid(tmp_path / "t", ("8/41/100.png", "8/41/101.png"))
    elsewhere = _pyramid(tmp_path / "elsewhere", ("8/41/100.png", "8/41/101.png"))
    (elsewhere / "8" / "41" / "101.png").write_bytes(b"secret")
    real = Path.read_bytes
    swapped: list[Path] = []

    def swap_after_first(self: Path) -> bytes:
        payload = real(self)
        if not swapped:  # after the first tile, replace "t/8" by a junction elsewhere
            swapped.append(self)
            (out / "8").rename(tmp_path / "moved")
            winapi.CreateJunction(str(elsewhere / "8"), str(out / "8"))
        return payload

    monkeypatch.setattr(Path, "read_bytes", swap_after_first)
    with pytest.raises(PublishError, match="changed during"):
        publishing.read_owned_tree(out, PYRAMID)
    assert swapped


def test_file_replaced_during_its_read_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = _pyramid(tmp_path / "t", ("8/41/100.png",))
    real = Path.read_bytes

    def replace_file(self: Path) -> bytes:
        payload = real(self)
        if self.name == "100.png":
            self.unlink()
            self.write_bytes(b"a different, longer file")
        return payload

    monkeypatch.setattr(Path, "read_bytes", replace_file)
    with pytest.raises(PublishError, match="changed during reading"):
        publishing.read_owned_tree(out, PYRAMID)
