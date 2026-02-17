import json
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from app.services.metadata import (
    extract_rating_keys_json,
    extract_rating_keys_xml,
    is_episode_route,
    obscure_episode_json,
    obscure_episode_xml,
)

# --- Sample Plex XML response (season children) ---

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="3">
  <Video ratingKey="101" type="episode" index="1"
         title="The One Where Ross Finds Out"
         summary="Ross discovers Rachel's feelings."
         thumb="/library/metadata/101/thumb"
         art="/library/metadata/101/art"
         parentThumb="/library/metadata/50/thumb"
         grandparentThumb="/library/metadata/10/thumb"
         grandparentArt="/library/metadata/10/art"
         tagline="A big reveal">
    <Role tag="Guest Star"/>
  </Video>
  <Video ratingKey="102" type="episode" index="2"
         title="The One With the Prom Video"
         summary="Everyone watches an old prom video."
         thumb="/library/metadata/102/thumb"
         parentThumb="/library/metadata/50/thumb"
         grandparentThumb="/library/metadata/10/thumb"
         grandparentArt="/library/metadata/10/art">
  </Video>
  <Video ratingKey="200" type="movie" title="Some Movie" summary="A movie."/>
</MediaContainer>"""

# --- Sample Plex JSON response ---

SAMPLE_JSON = {
    "MediaContainer": {
        "Metadata": [
            {
                "ratingKey": "101",
                "type": "episode",
                "index": 1,
                "title": "The One Where Ross Finds Out",
                "summary": "Ross discovers Rachel's feelings.",
                "thumb": "/library/metadata/101/thumb",
                "art": "/library/metadata/101/art",
                "parentThumb": "/library/metadata/50/thumb",
                "grandparentThumb": "/library/metadata/10/thumb",
                "grandparentArt": "/library/metadata/10/art",
                "tagline": "A big reveal",
                "Role": [{"tag": "Guest Star"}],
            },
            {
                "ratingKey": "102",
                "type": "episode",
                "index": 2,
                "title": "The One With the Prom Video",
                "summary": "Everyone watches an old prom video.",
                "thumb": "/library/metadata/102/thumb",
                "parentThumb": "/library/metadata/50/thumb",
                "grandparentThumb": "/library/metadata/10/thumb",
                "grandparentArt": "/library/metadata/10/art",
            },
            {
                "ratingKey": "200",
                "type": "movie",
                "title": "Some Movie",
                "summary": "A movie.",
            },
        ]
    }
}


# ---- Route detection tests ----

class TestIsEpisodeRoute:
    def test_single_metadata(self):
        assert is_episode_route("/library/metadata/12345") is True

    def test_season_children(self):
        assert is_episode_route("/library/metadata/100/children") is True

    def test_section_all(self):
        assert is_episode_route("/library/sections/1/all") is True

    def test_section_on_deck(self):
        assert is_episode_route("/library/sections/2/onDeck") is True

    def test_recently_added(self):
        assert is_episode_route("/library/sections/1/recentlyAdded") is True

    def test_hubs(self):
        assert is_episode_route("/hubs") is True
        assert is_episode_route("/hubs/home") is True

    def test_non_episode_routes(self):
        assert is_episode_route("/") is False
        assert is_episode_route("/identity") is False
        assert is_episode_route("/library/sections") is False
        assert is_episode_route("/photo/:/transcode") is False


# ---- XML tests ----

class TestObscureXml:
    def test_unwatched_episodes_are_obscured(self):
        root = ET.fromstring(SAMPLE_XML)
        watched = {"101": False, "102": False}
        modified = obscure_episode_xml(root, watched)

        assert modified is True
        episodes = [v for v in root.iter("Video") if v.get("type") == "episode"]

        ep1 = episodes[0]
        assert ep1.get("title") == "Episode 1"
        assert ep1.get("summary") == ""
        assert ep1.get("thumb") == "/library/metadata/50/thumb"
        assert ep1.get("art") == "/library/metadata/10/art"
        assert ep1.get("tagline") == ""
        assert ep1.findall("Role") == []

        ep2 = episodes[1]
        assert ep2.get("title") == "Episode 2"
        assert ep2.get("summary") == ""

    def test_watched_episodes_pass_through(self):
        root = ET.fromstring(SAMPLE_XML)
        watched = {"101": True, "102": True}
        modified = obscure_episode_xml(root, watched)

        assert modified is False
        ep1 = list(root.iter("Video"))[0]
        assert ep1.get("title") == "The One Where Ross Finds Out"

    def test_mixed_watched_state(self):
        root = ET.fromstring(SAMPLE_XML)
        watched = {"101": True, "102": False}
        modified = obscure_episode_xml(root, watched)

        assert modified is True
        episodes = [v for v in root.iter("Video") if v.get("type") == "episode"]
        assert episodes[0].get("title") == "The One Where Ross Finds Out"
        assert episodes[1].get("title") == "Episode 2"

    def test_movies_are_never_obscured(self):
        root = ET.fromstring(SAMPLE_XML)
        watched = {"101": False, "102": False, "200": False}
        obscure_episode_xml(root, watched)

        movie = [v for v in root.iter("Video") if v.get("type") == "movie"][0]
        assert movie.get("title") == "Some Movie"
        assert movie.get("summary") == "A movie."

    def test_unknown_keys_treated_as_unwatched(self):
        root = ET.fromstring(SAMPLE_XML)
        watched = {}  # no keys known
        modified = obscure_episode_xml(root, watched)

        assert modified is True


# ---- JSON tests ----

class TestObscureJson:
    def _fresh_data(self):
        return json.loads(json.dumps(SAMPLE_JSON))

    def test_unwatched_episodes_are_obscured(self):
        data = self._fresh_data()
        watched = {"101": False, "102": False}
        modified = obscure_episode_json(data, watched)

        assert modified is True
        eps = [m for m in data["MediaContainer"]["Metadata"] if m["type"] == "episode"]

        assert eps[0]["title"] == "Episode 1"
        assert eps[0]["summary"] == ""
        assert eps[0]["thumb"] == "/library/metadata/50/thumb"
        assert eps[0]["art"] == "/library/metadata/10/art"
        assert eps[0]["tagline"] == ""
        assert "Role" not in eps[0]

    def test_watched_episodes_pass_through(self):
        data = self._fresh_data()
        watched = {"101": True, "102": True}
        modified = obscure_episode_json(data, watched)

        assert modified is False
        assert data["MediaContainer"]["Metadata"][0]["title"] == "The One Where Ross Finds Out"

    def test_mixed_watched_state(self):
        data = self._fresh_data()
        watched = {"101": True, "102": False}
        modified = obscure_episode_json(data, watched)

        assert modified is True
        eps = data["MediaContainer"]["Metadata"]
        assert eps[0]["title"] == "The One Where Ross Finds Out"
        assert eps[1]["title"] == "Episode 2"

    def test_movies_are_never_obscured(self):
        data = self._fresh_data()
        watched = {"101": False, "102": False, "200": False}
        obscure_episode_json(data, watched)

        movie = [m for m in data["MediaContainer"]["Metadata"] if m["type"] == "movie"][0]
        assert movie["title"] == "Some Movie"


# ---- Rating key extraction tests ----

class TestExtractRatingKeys:
    def test_xml_extracts_episode_keys_only(self):
        root = ET.fromstring(SAMPLE_XML)
        keys = extract_rating_keys_xml(root)
        assert keys == ["101", "102"]

    def test_json_extracts_episode_keys_only(self):
        keys = extract_rating_keys_json(SAMPLE_JSON)
        assert keys == ["101", "102"]

    def test_empty_xml(self):
        root = ET.fromstring("<MediaContainer/>")
        assert extract_rating_keys_xml(root) == []

    def test_empty_json(self):
        assert extract_rating_keys_json({"MediaContainer": {}}) == []
        assert extract_rating_keys_json({}) == []


# ---- Obfuscation config toggle tests ----

class TestObfuscationConfig:
    def test_title_only_mode(self):
        """When only title obfuscation is enabled, summary/thumb/roles stay intact."""
        from app.config import ObfuscationConfig
        mock_obf = ObfuscationConfig(title=True, summary=False, thumbnail=False, roles=False)

        with patch("app.services.metadata.obf", mock_obf):
            data = json.loads(json.dumps(SAMPLE_JSON))
            watched = {"101": False, "102": False}
            obscure_episode_json(data, watched)

            ep = data["MediaContainer"]["Metadata"][0]
            assert ep["title"] == "Episode 1"
            assert ep["summary"] == "Ross discovers Rachel's feelings."
            assert ep["thumb"] == "/library/metadata/101/thumb"
            assert "Role" in ep

    def test_all_disabled(self):
        """When all obfuscation is disabled, nothing changes (but still returns modified=True
        because the episode was unwatched and processed)."""
        from app.config import ObfuscationConfig
        mock_obf = ObfuscationConfig(title=False, summary=False, thumbnail=False, roles=False)

        with patch("app.services.metadata.obf", mock_obf):
            data = json.loads(json.dumps(SAMPLE_JSON))
            watched = {"101": False, "102": False}
            obscure_episode_json(data, watched)

            ep = data["MediaContainer"]["Metadata"][0]
            assert ep["title"] == "The One Where Ross Finds Out"
            assert ep["summary"] == "Ross discovers Rachel's feelings."
