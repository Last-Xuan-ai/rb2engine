"""Real filesystem locks keep conversion and waveform publication mutually exclusive."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from rb2engine.errors import FatalError
from rb2engine.ir import SourceLibrary
from rb2engine.library_lock import library_lock
from rb2engine.report import ConversionReport
from rb2engine.writer.build import build_library
from rb2engine.writer.schema import create_database


def test_reentrant_acquisition_is_rejected_and_release_keeps_lock_file(tmp_path: Path) -> None:
    directory = tmp_path.resolve() / "Engine Library" / "Database2"
    with (
        library_lock(directory),
        pytest.raises(FatalError, match="holds the library lock"),
        library_lock(directory),
    ):
        pytest.fail("The same process must not start a second library writer")

    lock = directory / ".rb2engine.lock"
    assert lock.is_file()  # Removing it would let contenders lock different inodes.
    inode = lock.stat().st_ino
    with library_lock(directory):
        assert lock.stat().st_ino == inode
    assert lock.is_file()


def _acquire_in_subprocess(directory: Path) -> subprocess.CompletedProcess[str]:
    # A fresh interpreter prevents inherited file handles from disguising a broken
    # cross-process lock. This also exercises Windows' real msvcrt implementation.
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from rb2engine.errors import FatalError
from rb2engine.library_lock import library_lock
try:
    with library_lock(Path(sys.argv[2])):
        print('acquired')
except FatalError as exc:
    print(str(exc))
    sys.exit(42)
"""
    return subprocess.run(  # noqa: S603 - fixed code in the current Python interpreter
        [sys.executable, "-c", code, str(Path(__file__).parents[2] / "src"), str(directory)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def test_independent_process_is_excluded_then_lock_is_reusable(tmp_path: Path) -> None:
    directory = tmp_path.resolve() / "Engine Library" / "Database2"
    with library_lock(directory):
        denied = _acquire_in_subprocess(directory)
        assert denied.returncode == 42, denied.stderr
        assert "holds the library lock" in denied.stdout

    accepted = _acquire_in_subprocess(directory)
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "acquired"
    # The second interpreter has exited; its lock must no longer block a writer.
    with library_lock(directory):
        assert (directory / ".rb2engine.lock").is_file()


def test_exception_in_writer_releases_lock(tmp_path: Path) -> None:
    directory = tmp_path.resolve() / "Database2"
    with pytest.raises(RuntimeError, match="simulated writer failure"), library_lock(directory):
        raise RuntimeError("simulated writer failure")
    with library_lock(directory):
        assert (directory / ".rb2engine.lock").is_file()


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) in (5, 1314):
            pytest.skip("Windows symlink creation requires Developer Mode or privilege")
        raise


def test_lock_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    directory = root / "Engine Library" / "Database2"
    directory.mkdir(parents=True)
    target = root / "unrelated-file"
    original = b"must never be opened for lock writes"
    target.write_bytes(original)
    _symlink_or_skip(directory / ".rb2engine.lock", target)

    with pytest.raises(FatalError, match="lock may not be a symlink"), library_lock(directory):
        pytest.fail("A lock symlink must never be followed")
    assert target.read_bytes() == original


@pytest.mark.parametrize("link_is_database_directory", [False, True])
def test_symlink_in_database_path_is_rejected_before_creating_files(
    tmp_path: Path, link_is_database_directory: bool
) -> None:
    root = tmp_path.resolve()
    target = root / "unrelated-directory"
    target.mkdir()
    link = root / "linked-directory"
    _symlink_or_skip(link, target, directory=True)
    directory = link if link_is_database_directory else link / "Engine Library" / "Database2"

    with (
        pytest.raises(FatalError, match="path may not traverse a symlink"),
        library_lock(directory),
    ):
        pytest.fail("A database path must not traverse a symlink")
    assert list(target.iterdir()) == []


def test_conversion_refuses_held_lock_before_reconcile_or_any_database_write(
    tmp_path: Path,
) -> None:
    drive = tmp_path.resolve()
    engine = drive / "Engine Library"
    directory = engine / "Database2"
    directory.mkdir(parents=True)
    database = directory / "m.db"
    connection = create_database(database, (3, 0, 2), database_uuid="library-lock-test")
    connection.close()
    # Reconciliation normally deletes these. They may belong to the active
    # writer, so even cleanup must wait until the shared library lock is owned.
    (directory / "m.db.tmp").write_bytes(b"active conversion temporary database")
    (directory / "m.db.tmp-journal").write_bytes(b"active transaction")
    for suffix in ("tmp", "old"):
        residue = drive / f"Engine Library.{suffix}"
        residue.mkdir()
        (residue / "sentinel").write_bytes(b"do not reconcile without the lock")
    (directory / "hm.db").write_bytes(b"history must survive")
    before = {
        path.relative_to(drive): path.read_bytes() for path in drive.rglob("*") if path.is_file()
    }
    source = SourceLibrary(drive_root=drive, tracks={}, playlists=[], warnings=[])
    report = ConversionReport()

    with library_lock(directory), pytest.raises(FatalError, match="holds the library lock"):
        build_library(source, drive_root=drive, report=report, target_schema=(3, 0, 2))

    after = {
        path.relative_to(drive): path.read_bytes()
        for path in drive.rglob("*")
        if path.is_file() and path.name != ".rb2engine.lock"
    }
    assert after == before
