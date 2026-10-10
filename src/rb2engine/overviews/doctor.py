"""Inspect optional waveform dependencies without affecting base conversion."""

import platform
import sys

import numpy as np

from .generator import create_context


def doctor(*, include_aac=True):
    context = create_context()
    result = {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "platform": platform.platform(),
        "dependencies": context.runtime,
        "dsp": str(context.library),
        "dsp_sha256": context.runtime["dsp_sha256"],
        "supported_rates": [44100, 48000],
        "supported_channels": [1, 2],
        "hardware_validated": False,
    }
    if include_aac:
        result["aac_reader"] = str(context.ensure_aac())
        result["aac_runtime"] = context.aac_identity
    return result
