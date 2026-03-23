"""Tests for app/services/replaygain.py"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.replaygain import (
    REFERENCE_LOUDNESS,
    _parse_integrated,
    _parse_true_peak,
    calculate_replaygain,
)

# ── Sample ffmpeg ebur128 stderr output ───────────────────────────────────────

SAMPLE_STDERR = """
[Parsed_ebur128_0 @ 0x...] Summary:

  Integrated loudness:
    I:         -23.4 LUFS
    Threshold: -33.4 LUFS

  Loudness range:
    LRA:         6.3 LU
    Threshold:  -43.4 LUFS
    LRA low:   -26.9 LUFS
    LRA high:  -20.6 LUFS

  True peak:
    Peak:        -0.5 dBTP
"""

STDERR_NO_PEAK = """
  Integrated loudness:
    I:         -18.0 LUFS
"""

STDERR_MALFORMED = "ffmpeg: no such filter 'ebur128'"


# ── _parse_integrated ──────────────────────────────────────────────────────────

class TestParseIntegrated:
    def test_parses_negative_value(self):
        assert _parse_integrated(SAMPLE_STDERR) == pytest.approx(-23.4)

    def test_parses_reference_level(self):
        assert _parse_integrated(STDERR_NO_PEAK) == pytest.approx(-18.0)

    def test_raises_on_missing(self):
        with pytest.raises(RuntimeError, match="could not parse"):
            _parse_integrated(STDERR_MALFORMED)


# ── _parse_true_peak ───────────────────────────────────────────────────────────

class TestParseTruePeak:
    def test_parses_negative_dbtp(self):
        assert _parse_true_peak(SAMPLE_STDERR) == pytest.approx(-0.5)

    def test_returns_zero_when_missing(self):
        assert _parse_true_peak(STDERR_NO_PEAK) == 0.0


# ── calculate_replaygain (mocked subprocess) ───────────────────────────────────

def _make_stderr(lufs: float, peak: float) -> str:
    return f"""
  Integrated loudness:
    I:         {lufs:.1f} LUFS
  True peak:
    Peak:        {peak:.1f} dBTP
"""


class TestCalculateReplaygain:
    def _mock_run(self, lufs_values: list[float], peak: float = -1.0):
        """Return a side_effect list for subprocess.run, one per ffmpeg call."""
        call_count = {"n": 0}

        def side_effect(args, **kwargs):
            mock = MagicMock()
            mock.stderr = _make_stderr(lufs_values[call_count["n"] % len(lufs_values)], peak)
            call_count["n"] += 1
            return mock

        return side_effect

    def test_track_gain_calculation(self, tmp_path):
        f = tmp_path / "a.flac"
        f.touch()
        lufs = -23.0
        expected_gain = REFERENCE_LOUDNESS - lufs  # +5.0

        with patch("app.services.replaygain.subprocess.run") as mock_run:
            mock_run.side_effect = self._mock_run([lufs])
            results = calculate_replaygain([f], album_mode=False)

        assert len(results) == 1
        r = results[0]
        assert r["lufs"] == pytest.approx(lufs)
        assert r["track_gain_db"] == pytest.approx(expected_gain)
        assert "REPLAYGAIN_TRACK_GAIN" in r["tags"]
        assert "REPLAYGAIN_TRACK_PEAK" in r["tags"]
        assert "REPLAYGAIN_REFERENCE_LOUDNESS" in r["tags"]

    def test_album_mode_includes_album_tags(self, tmp_path):
        files = [tmp_path / f"{i}.flac" for i in range(2)]
        for f in files:
            f.touch()

        # 2 track calls + 1 album concat call
        lufs_values = [-20.0, -22.0, -21.0]

        with patch("app.services.replaygain.subprocess.run") as mock_run:
            mock_run.side_effect = self._mock_run(lufs_values)
            results = calculate_replaygain(files, album_mode=True)

        for r in results:
            assert "REPLAYGAIN_ALBUM_GAIN" in r["tags"]
            assert "REPLAYGAIN_ALBUM_PEAK" in r["tags"]

    def test_no_album_mode_excludes_album_tags(self, tmp_path):
        f = tmp_path / "a.flac"
        f.touch()

        with patch("app.services.replaygain.subprocess.run") as mock_run:
            mock_run.side_effect = self._mock_run([-20.0])
            results = calculate_replaygain([f], album_mode=False)

        assert "REPLAYGAIN_ALBUM_GAIN" not in results[0]["tags"]

    def test_gain_string_format(self, tmp_path):
        f = tmp_path / "a.flac"
        f.touch()

        with patch("app.services.replaygain.subprocess.run") as mock_run:
            mock_run.side_effect = self._mock_run([-20.0])
            results = calculate_replaygain([f], album_mode=False)

        gain_str = results[0]["tags"]["REPLAYGAIN_TRACK_GAIN"]
        # Must look like "+2.00 dB" or "-2.00 dB"
        assert "dB" in gain_str
        assert gain_str[0] in ("+", "-")

    def test_peak_linear_conversion(self, tmp_path):
        """Peak dBTP -6.0 should convert to ~0.5 linear."""
        f = tmp_path / "a.flac"
        f.touch()

        with patch("app.services.replaygain.subprocess.run") as mock_run:
            mock = MagicMock()
            mock.stderr = _make_stderr(-18.0, -6.0)
            mock_run.return_value = mock
            results = calculate_replaygain([f], album_mode=False)

        peak = float(results[0]["tags"]["REPLAYGAIN_TRACK_PEAK"])
        assert peak == pytest.approx(10 ** (-6.0 / 20), rel=1e-3)
