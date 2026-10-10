"""Playlist order follows links, including repeated tracks and corrupt chains."""

import pytest

from rb2engine.chain import ChainInconsistent, walk_entity_chain


def test_entity_chain_follows_links_with_repeated_tracks() -> None:
    """Row ids and input order differ from playback; duplicate tracks stay."""
    rows = [(30, 100, 0), (70, 100, 20), (20, 200, 30)]
    assert walk_entity_chain(7, rows) == [100, 200, 100]


def test_entity_chain_handles_long_playlist_in_order() -> None:
    """A full-library playlist must preserve every entry without recursion."""
    count = 50_000
    rows = [(index, index * 2, index + 1) for index in range(1, count)]
    rows.append((count, count * 2, 0))
    assert walk_entity_chain(7, rows) == list(range(2, count * 2 + 1, 2))


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([(1, 100, 0), (2, 200, 0)], "forked"),
        ([(1, 100, 2), (2, 200, 1)], "chain is inconsistent"),
        ([(1, 100, 0), (2, 200, 3), (3, 300, 2)], "chain is inconsistent"),
        ([(1, 100, 0), (2, 200, 99)], "chain is inconsistent"),
    ],
)
def test_entity_chain_rejects_forks_cycles_and_unreachable_rows(
    rows: list[tuple[int, int, int]], message: str
) -> None:
    with pytest.raises(ChainInconsistent, match=message):
        walk_entity_chain(7, rows)


def test_empty_entity_chain() -> None:
    assert walk_entity_chain(7, []) == []
