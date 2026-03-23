"""ReplayGain calculation using ffmpeg ebur128 filter (EBU R128 / RG2 standard)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REFERENCE_LOUDNESS = -18.0  # LUFS — ReplayGain 2.0 reference level


def _run_ebur128(args: list[str]) -> str:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats"] + args,
        capture_output=True,
        text=True,
    )
    return result.stderr


def _parse_integrated(stderr: str) -> float:
    # Use the last match — ffmpeg emits per-frame `I: X LUFS` values during
    # processing before the final summary, so re.search would grab the first
    # frame (near-silence) rather than the true integrated loudness.
    matches = re.findall(r"\bI:\s+([-\d.]+)\s+LUFS", stderr)
    if not matches:
        raise RuntimeError("ffmpeg ebur128: could not parse integrated loudness")
    return float(matches[-1])


def _parse_true_peak(stderr: str) -> float:
    m = re.search(r"\bPeak:\s+([-\d.]+)\s+dBTP", stderr)
    return float(m.group(1)) if m else 0.0


def _measure_file(path: Path) -> tuple[float, float]:
    """Return (integrated_lufs, true_peak_dbtp) for a single file."""
    stderr = _run_ebur128([
        "-i", str(path),
        "-filter:a", "ebur128=peak=true",
        "-f", "null", "-",
    ])
    return _parse_integrated(stderr), _parse_true_peak(stderr)


def _measure_album_lufs(paths: list[Path]) -> float:
    """
    Measure album integrated loudness by analyzing all tracks concatenated.
    This is the ITU-R BS.1770 compliant method for album gain.
    """
    n = len(paths)
    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", str(p)]

    concat_filter = (
        "".join(f"[{i}:a]" for i in range(n))
        + f"concat=n={n}:v=0:a=1[concat];[concat]ebur128=peak=true[out]"
    )
    stderr = _run_ebur128(
        inputs + [
            "-filter_complex", concat_filter,
            "-map", "[out]",
            "-f", "null", "-",
        ]
    )
    return _parse_integrated(stderr)


def calculate_replaygain(paths: list[Path], album_mode: bool = True) -> list[dict]:
    """
    Calculate ReplayGain tags for a list of FLAC files.

    Returns a list of dicts:
        {"path": str, "filename": str, "lufs": float, "tags": dict[str, str]}

    Nothing is written to disk — call flac.write_tags() on each result to apply.
    """
    track_data: list[dict] = []
    for path in paths:
        lufs, peak_dbtp = _measure_file(path)
        peak_linear = 10 ** (peak_dbtp / 20)
        track_gain = REFERENCE_LOUDNESS - lufs
        track_data.append({
            "path": str(path),
            "filename": path.name,
            "lufs": lufs,
            "peak_linear": peak_linear,
            "track_gain_db": track_gain,
        })

    if album_mode and len(paths) > 0:
        album_lufs = _measure_album_lufs(paths) if len(paths) > 1 else track_data[0]["lufs"]
        album_gain = REFERENCE_LOUDNESS - album_lufs
        album_peak = max(t["peak_linear"] for t in track_data)
    else:
        album_gain = None
        album_peak = None

    results: list[dict] = []
    for t in track_data:
        tags: dict[str, str] = {
            "REPLAYGAIN_TRACK_GAIN": f"{t['track_gain_db']:+.2f} dB",
            "REPLAYGAIN_TRACK_PEAK": f"{t['peak_linear']:.6f}",
            "REPLAYGAIN_REFERENCE_LOUDNESS": f"{REFERENCE_LOUDNESS:.1f} LUFS",
        }
        if album_gain is not None:
            tags["REPLAYGAIN_ALBUM_GAIN"] = f"{album_gain:+.2f} dB"
            tags["REPLAYGAIN_ALBUM_PEAK"] = f"{album_peak:.6f}"  # type: ignore[arg-type]

        results.append({
            "path": t["path"],
            "filename": t["filename"],
            "lufs": round(t["lufs"], 2),
            "track_gain_db": round(t["track_gain_db"], 2),
            "tags": tags,
        })

    return results
