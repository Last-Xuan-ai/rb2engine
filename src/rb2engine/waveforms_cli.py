"""Optional overview commands; importing the CLI requires no waveform extras."""

from __future__ import annotations

import json
import sqlite3
import struct
import subprocess
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

import click

from rb2engine.errors import FatalError

PATH = click.Path(path_type=Path)


def _guard(function: Callable) -> Callable:
    """Keep optional dependencies and malformed inputs as actionable CLI errors."""

    @wraps(function)
    def invoke(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ImportError as exc:
            raise click.ClickException(
                "Waveform dependencies are missing. Install rb2engine[waveforms] "
                "and the external FFmpeg tools described in docs/waveforms.md."
            ) from exc
        except (
            OSError,
            ValueError,
            RuntimeError,
            sqlite3.Error,
            subprocess.SubprocessError,
            zlib.error,
            struct.error,
            KeyError,
            TypeError,
            FatalError,
        ) as exc:
            raise click.ClickException(str(exc)) from exc

    return invoke


def _cache(path: Path | None) -> Path:
    if path is not None:
        return path.expanduser().resolve()
    from rb2engine.overviews._build import build_cache

    return build_cache().parent / "waveforms"


def _json(value: Any) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _report(path: Path, value: Any) -> None:
    """Never replace a previous run's report or a source file by accident."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


@click.group()
def waveforms() -> None:
    """Generate and safely add overview waveforms to an existing Engine library.

    Opt-in macOS/Linux backend. Base conversion remains independent. Only
    apply/restore mutate the Engine database; prepare writes a reviewable plan.
    """


@waveforms.command("doctor")
@click.option("--no-aac", is_flag=True, help="Check generic DSP without AAC development libraries.")
@_guard
def doctor_cmd(no_aac: bool) -> None:
    """Check dependencies and build the optional native helpers in a user cache."""
    from rb2engine.overviews.doctor import doctor

    _json(doctor(include_aac=not no_aac))


@waveforms.command("generate")
@click.argument("audio", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--cache", type=PATH, help="Content cache; defaults to the user's cache directory.")
@_guard
def generate_cmd(audio: Path, cache: Path | None) -> None:
    """Generate both 1024-point overviews from one read-only audio file."""
    from rb2engine.overviews.generator import generate

    _json(generate(audio, _cache(cache)))


def _generate_many(items: list[dict[str, Any]], cache: Path) -> list[dict[str, Any]]:
    from rb2engine.overviews.generator import create_context, generate

    context = create_context()
    rows = []
    for index, item in enumerate(items, 1):
        row = dict(item)
        try:
            if "input_error" in item:
                raise ValueError(item["input_error"])
            row.update(status="generated", result=generate(item["audio"], cache, context=context))
        except Exception as exc:  # noqa: BLE001 - retain each failed input; report never claims success
            row.update(status="error", error=str(exc))
        rows.append(row)
        click.echo(f"{index}/{len(items)} {row['status']}", err=True)
    return rows


@waveforms.command("batch")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--cache", type=PATH)
@click.option("--report", "report_path", type=PATH, required=True)
@click.pass_context
@_guard
def batch_cmd(ctx: click.Context, manifest: Path, cache: Path | None, report_path: Path) -> None:
    """Generate from a JSON array of audio paths; failed songs remain in the report."""
    if report_path.exists():
        raise ValueError("Report already exists; choose a new report path")
    paths = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise ValueError("Manifest must be a non-empty JSON array of audio path strings")
    rows = _generate_many([{"audio": p} for p in paths], _cache(cache))
    failures = sum(row["status"] != "generated" for row in rows)
    _report(report_path, {"samples": rows, "failures": failures, "database_written": False})
    _json({"report": str(report_path), "tracks": len(rows), "failures": failures})
    if failures:
        ctx.exit(1)


@waveforms.command("verify-cache")
@click.argument("cache_entry", type=click.Path(exists=True, file_okay=False, path_type=Path))
@_guard
def verify_cache_cmd(cache_entry: Path) -> None:
    """Verify the identity and structure of one generated cache entry."""
    from rb2engine.overviews.generator import verify_entry

    _json(verify_entry(cache_entry))


@waveforms.command("prepare")
@click.argument("drive", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--track",
    "track_ids",
    multiple=True,
    type=click.IntRange(min=1),
    help="Select Engine Track IDs; omitted means every track in this library.",
)
@click.option("--cache", type=PATH)
@click.option("--out", type=PATH, help="New batch directory inside this drive's Engine Library.")
@click.option(
    "--allow-partial",
    is_flag=True,
    help="Explicitly prepare successful tracks even if others fail; exit remains 1.",
)
@click.pass_context
@_guard
def prepare_cmd(
    ctx: click.Context,
    drive: Path,
    track_ids: tuple[int, ...],
    cache: Path | None,
    out: Path | None,
    allow_partial: bool,
) -> None:
    """Generate from existing Track paths and prepare a waveform-only publication.

    No second music copy or manual mapping is needed. Generation errors prevent
    a plan by default; use --allow-partial to deliberately publish a subset.
    """
    from rb2engine.overviews.publication import (
        audio_path,
        connect,
        database_path,
        prepare,
        reject_symlinks,
        schema,
    )

    library = reject_symlinks(drive.expanduser()).resolve() / "Engine Library"
    database = database_path(library / "Database2" / "m.db")
    if out is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        out = library / "rb2engine-waveforms" / stamp
    out = out.expanduser().absolute()
    if not out.resolve().is_relative_to(library.resolve()) or out.exists():
        raise ValueError("--out must be a new directory inside this drive's Engine Library")
    for part in (out, *out.parents):
        if part.is_symlink():
            raise ValueError("Publication directory may not traverse a symlink")
    c = connect(database)
    try:
        c.execute("BEGIN")
        schema(c)
        tracks = c.execute("SELECT id,path FROM Track ORDER BY id").fetchall()
        known = {row["id"] for row in tracks}
        if set(track_ids) - known:
            raise ValueError(f"Unknown Engine Track IDs: {sorted(set(track_ids) - known)}")
        items = []
        for row in tracks:
            if track_ids and row["id"] not in track_ids:
                continue
            item = {"track_id": row["id"], "audio": row["path"]}
            try:
                item["audio"] = str(audio_path(database, row["path"]))
            except (OSError, ValueError) as exc:
                item["input_error"] = str(exc)
            items.append(item)
    finally:
        c.close()
    if not items:
        raise ValueError("No tracks selected")
    out.mkdir(parents=True, exist_ok=False)
    rows = _generate_many(items, _cache(cache))
    failures = sum(row["status"] != "generated" for row in rows)
    _report(
        out / "generation.json", {"samples": rows, "failures": failures, "database_written": False}
    )
    entries = [
        {"track_id": row["track_id"], "cache_path": row["result"]["cache_path"]}
        for row in rows
        if row["status"] == "generated"
    ]
    result: dict[str, Any] = {
        "batch": str(out),
        "tracks": len(rows),
        "failures": failures,
        "database_written": False,
        "plan_created": False,
    }
    if entries and (not failures or allow_partial):
        result.update(prepare(database, entries, out / "publication"), plan_created=True)
    _json(result)
    if failures:
        ctx.exit(1)


@waveforms.command("plan")
@click.argument("database", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=PATH, required=True)
@_guard
def plan_cmd(database: Path, manifest: Path, out: Path) -> None:
    """Prepare from an explicit JSON array of track_id/cache_path mappings."""
    from rb2engine.overviews.publication import prepare

    _json(prepare(database, json.loads(manifest.read_text(encoding="utf-8")), out))


def _publication_action(action: str, folder: Path) -> None:
    from rb2engine.overviews import publication

    function = {
        "apply": publication.apply,
        "check": publication.verify,
        "restore": publication.restore,
    }[action]
    _json(function(folder))


@waveforms.command("apply")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@_guard
def apply_cmd(folder: Path) -> None:
    """Back up and apply a prepared publication. Quit Engine first."""
    _publication_action("apply", folder)


@waveforms.command("check")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@_guard
def check_cmd(folder: Path) -> None:
    """Read back waveform bytes and verify protected metadata without writing."""
    _publication_action("check", folder)


@waveforms.command("restore")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@_guard
def restore_cmd(folder: Path) -> None:
    """Restore/recover this batch while preserving unrelated later edits."""
    _publication_action("restore", folder)
