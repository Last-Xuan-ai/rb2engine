# Engine overview validation

The unchanged standalone overview algorithm **0.5.0 passed two independent 50-song holdouts: 100/100 songs**, with **49 exact and 51 near** results. Both three-band and RGB outputs had to pass for a song to pass. The latest 50-song batch passed with **25 exact and 25 near** songs.

This is validation of the 1024-point overview algorithm. It does not by itself prove a subsequently modified rb2engine integration, scrolling high-resolution waveforms, BPM/key/grid analysis, or hardware playback.

## Results

| Dataset | Role | Songs | Exact songs | Near songs | Failed/pending | Exact waveforms | Near waveforms |
|---|---|---:|---:|---:|---:|---:|---:|
| 120 previously revealed songs | Development regression | 120 | 57 | 63 | 0 | 166 | 74 |
| Independent batch A | Predictions frozen before native import | 50 | 24 | 26 | 0 | 66 | 34 |
| Previous total | Regression plus batch A | 170 | 81 | 89 | 0 | 232 | 108 |
| Independent batch B | Predictions frozen before native import | 50 | 25 | 25 | 0 | 70 | 30 |
| **Independent batches A + B** | **Independent validation only** | **100** | **49** | **51** | **0** | **136** | **64** |
| All available samples | Regression plus both independent batches | 220 | 106 | 114 | 0 | 302 | 138 |

The worst absolute channel-byte error was **1**. The worst mean absolute error was **0.0016276041666666667** across 3,072 channel bytes per waveform, equivalent to five bytes differing by one. Every header, sample clock, and footer matched. The near threshold was unchanged throughout.

## Comparison criteria

- **Exact:** the complete decompressed header, all 1,024 three-channel points, and footer are identical.
- **Near:** identical header, sample clock, and footer; maximum channel-byte difference at most 1 and mean absolute difference at most 0.01.
- **Song pass:** both three-band and RGB outputs are exact or near. Missing references, generation errors, and mismatches cannot count as passing.

No predictions were shifted, rescaled, regenerated, or retuned after revealing either independent batch. A seeded order selected tracks within eight codec/rate strata. Each new batch excluded all previously revealed content identities, IDs, and normalized titles. Freezes are local timestamp/hash records, not an external preregistration service.

After each native import, references were captured once with Engine open and again after Engine exited. All 100 reference files per batch were byte-identical between captures, and comparison metrics were unchanged. Preexisting Track/PerformanceData records and playlist tables were unchanged by those imports.

## Independent 100-song coverage

| Codec | Sample rate (Hz) | Songs | Exact | Near | Failed |
|---|---:|---:|---:|---:|---:|
| aac | 44100 | 12 | 0 | 12 | 0 |
| aac | 48000 | 16 | 7 | 9 | 0 |
| flac | 44100 | 8 | 8 | 0 | 0 |
| flac | 48000 | 8 | 8 | 0 | 0 |
| mp3 | 44100 | 24 | 6 | 18 | 0 |
| mp3 | 48000 | 16 | 5 | 11 | 0 |
| pcm_s16le | 44100 | 8 | 7 | 1 | 0 |
| pcm_s16le | 48000 | 8 | 8 | 0 | 0 |

Every song was stereo. WAV coverage is signed 16-bit little-endian PCM. These are strata from one private music collection, not a universal compatibility or whole-library success-rate estimate. Mono, additional codecs/sample rates, different decoder builds, other operating systems, and hardware playback remain outside these runs.

## Environment and provenance

- Native reference: Engine DJ 5.1.0 on Apple Silicon macOS 27.0.1.
- Generator runtime: Python 3.12.14, NumPy 2.3.5, independently installed FFmpeg 9.0.1.
- Algorithm version: 0.5.0.
- Algorithm source SHA-256: `98078ca3a2c73fe40a86fa1bf0d5b53101f9d60c05be7ce5835db7f4c9c94884`.
- Independent batch A predictions frozen: `2026-10-10T11:59:16.878383+00:00`.
- Independent batch B predictions frozen: `2026-10-10T13:40:17.889248+00:00`.

[Machine-readable results](waveform-validation.json) contain anonymous per-sample metrics for all 220 songs. They deliberately omit song titles, artists, personal paths, audio, audio-content hashes, and library databases. The 120 development samples retain their regression classification; they are not relabeled as independent evidence.
