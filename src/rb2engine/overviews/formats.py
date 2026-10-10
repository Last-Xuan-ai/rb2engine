"""Engine Qt-compressed overview container; no database access."""

import hashlib
import math
import struct
import zlib
from pathlib import Path

import numpy as np

POINTS = 1024


def unpack(blob):
    if len(blob) <= 4:
        raise ValueError("Empty waveform")
    size = struct.unpack(">I", blob[:4])[0]
    if not 27 <= size <= 1048576:
        raise ValueError("Invalid waveform size")
    dec = zlib.decompressobj()
    raw = dec.decompress(blob[4:], size + 1)
    if len(raw) != size or not dec.eof or dec.unused_data or dec.unconsumed_tail:
        raise ValueError("Truncated or excessive compressed waveform")
    stored, requested, spacing = struct.unpack_from(">QQd", raw)
    if stored != requested or stored != POINTS or len(raw) != 24 + stored * 3 + 3:
        raise ValueError("Unknown waveform layout")
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("Invalid time axis")
    points = np.frombuffer(raw[24:-3], np.uint8).reshape(stored, 3).copy()
    return points, spacing, raw[-3:], raw


def pack(points, frames, block_frames, kind):
    if kind not in ("tri", "rgb") or frames <= 0 or block_frames <= 0:
        raise ValueError("Invalid overview parameters")
    values = np.asarray(points)
    if values.shape != (POINTS, 3) or values.dtype != np.uint8:
        raise ValueError("Expected 1024 x 3 uint8 points")
    # Preserve native operation ordering, including its final double ULP.
    spacing = (frames / (block_frames * POINTS)) * block_frames
    footer = values.max(0) if kind == "tri" else values[np.argmax(values.astype(np.uint16).sum(1))]
    raw = struct.pack(">QQd", POINTS, POINTS, spacing) + values.tobytes() + footer.tobytes()
    blob = struct.pack(">I", len(raw)) + zlib.compress(raw)
    recovered, actual, tail, _ = unpack(blob)
    if not np.array_equal(recovered, values) or actual != spacing or tail != footer.tobytes():
        raise AssertionError("Overview self-check failed")
    return blob


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()
