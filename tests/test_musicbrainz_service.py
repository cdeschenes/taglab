"""Tests for app/services/musicbrainz.py"""
from unittest.mock import patch

import pytest

from app.services.musicbrainz import (
    _extract_label,
    _flatten_artist_credit,
    get_release,
    search_releases,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _artist_credit(name: str, join: str = "") -> dict:
    return {"artist": {"id": f"mbid-{name}", "name": name}, "joinphrase": join}


# ── _flatten_artist_credit ─────────────────────────────────────────────────────

class TestFlattenArtistCredit:
    def test_single_artist(self):
        assert _flatten_artist_credit([_artist_credit("Radiohead")]) == "Radiohead"

    def test_two_artists_with_join(self):
        credits = [_artist_credit("Jay-Z", " & "), _artist_credit("Kanye West")]
        assert _flatten_artist_credit(credits) == "Jay-Z & Kanye West"

    def test_empty_list(self):
        assert _flatten_artist_credit([]) == ""

    def test_string_element_handled(self):
        assert _flatten_artist_credit(["Various Artists"]) == "Various Artists"


# ── _extract_label ─────────────────────────────────────────────────────────────

class TestExtractLabel:
    def test_extracts_label_name(self):
        release = {"label-info-list": [{"label": {"name": "Sub Pop"}}]}
        assert _extract_label(release) == "Sub Pop"

    def test_empty_when_no_label(self):
        assert _extract_label({}) == ""

    def test_empty_when_label_list_empty(self):
        assert _extract_label({"label-info-list": []}) == ""


# ── search_releases ────────────────────────────────────────────────────────────

MOCK_SEARCH_RESULT = {
    "release-list": [
        {
            "id": "release-mbid-1",
            "title": "OK Computer",
            "date": "1997-05-21",
            "country": "GB",
            "artist-credit": [_artist_credit("Radiohead")],
            "medium-list": [{"track-count": 12}],
            "ext:score": "100",
        }
    ]
}


class TestSearchReleases:
    def test_returns_formatted_results(self):
        with patch("musicbrainzngs.search_releases", return_value=MOCK_SEARCH_RESULT):
            results = search_releases(artist="Radiohead", album="OK Computer")

        assert len(results) == 1
        r = results[0]
        assert r["mbid"] == "release-mbid-1"
        assert r["title"] == "OK Computer"
        assert r["artist"] == "Radiohead"
        assert r["date"] == "1997-05-21"
        assert r["country"] == "GB"
        assert r["track_count"] == 12

    def test_empty_release_list(self):
        with patch("musicbrainzngs.search_releases", return_value={"release-list": []}):
            results = search_releases(artist="Nobody", album="Nothing")
        assert results == []

    def test_raises_on_web_service_error(self):
        import musicbrainzngs
        with patch("musicbrainzngs.search_releases", side_effect=musicbrainzngs.WebServiceError("timeout")):
            with pytest.raises(RuntimeError, match="MusicBrainz search failed"):
                search_releases(artist="X", album="Y")


# ── get_release ────────────────────────────────────────────────────────────────

MOCK_RELEASE_RESULT = {
    "release": {
        "id": "release-mbid-1",
        "title": "OK Computer",
        "date": "1997-05-21",
        "country": "GB",
        "artist-credit": [_artist_credit("Radiohead")],
        "release-group": {"id": "rg-mbid-1"},
        "label-info-list": [{"label": {"name": "Parlophone"}}],
        "medium-list": [
            {
                "position": 1,
                "track-list": [
                    {
                        "id": "track-mbid-1",
                        "position": "1",
                        "recording": {
                            "id": "rec-mbid-1",
                            "title": "Airbag",
                            "artist-credit": [_artist_credit("Radiohead")],
                        },
                    },
                    {
                        "id": "track-mbid-2",
                        "position": "2",
                        "recording": {
                            "id": "rec-mbid-2",
                            "title": "Paranoid Android",
                            "artist-credit": [_artist_credit("Radiohead")],
                        },
                    },
                ],
            }
        ],
    }
}


class TestGetRelease:
    def test_returns_shared_tags(self):
        with patch("musicbrainzngs.get_release_by_id", return_value=MOCK_RELEASE_RESULT):
            result = get_release("release-mbid-1")

        shared = result["shared_tags"]
        assert shared["album"] == "OK Computer"
        assert shared["albumartist"] == "Radiohead"
        assert shared["date"] == "1997-05-21"
        assert shared["country"] == "GB"
        assert shared["label"] == "Parlophone"
        assert shared["musicbrainz_albumid"] == "release-mbid-1"
        assert shared["musicbrainz_releasegroupid"] == "rg-mbid-1"

    def test_returns_track_list(self):
        with patch("musicbrainzngs.get_release_by_id", return_value=MOCK_RELEASE_RESULT):
            result = get_release("release-mbid-1")

        assert len(result["tracks"]) == 2
        t0 = result["tracks"][0]
        assert t0["title"] == "Airbag"
        assert t0["tags"]["musicbrainz_trackid"] == "rec-mbid-1"
        assert t0["tags"]["tracknumber"] == "1"

    def test_raises_on_web_service_error(self):
        import musicbrainzngs
        with patch("musicbrainzngs.get_release_by_id", side_effect=musicbrainzngs.WebServiceError("404")):
            with pytest.raises(RuntimeError, match="MusicBrainz lookup failed"):
                get_release("bad-mbid")
