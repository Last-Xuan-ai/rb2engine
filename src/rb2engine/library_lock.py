"""Cross-process exclusion shared by conversion and waveform publication.

The lock file remains in Database2: unlinking it while another process has the
old inode open would permit a second independent lock on the same library.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from rb2engine.errors import FatalError


@contextmanager
def library_lock(database_directory: Path) -> Iterator[None]:
    """Fail promptly if another rb2engine operation owns this library."""
    directory = Path(database_directory)
    for part in (directory, *directory.parents):
        if part.is_symlink():
            raise FatalError("Engine library path may not traverse a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".rb2engine.lock"
    if path.is_symlink():
        raise FatalError("Engine library lock may not be a symlink")
    with path.open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt

            # Windows byte-range locks need a persistent byte to lock.
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise FatalError("Another rb2engine operation holds the library lock") from exc
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise FatalError("Another rb2engine operation holds the library lock") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
