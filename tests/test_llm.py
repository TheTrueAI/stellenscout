"""Tests for stellenscout.llm — parse_json() pure function."""

import pytest

from stellenscout.llm import parse_json


class TestParseJson:
    def test_raw_object(self):
        result = parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_raw_array(self):
        result = parse_json('["a", "b", "c"]')
        assert result == ["a", "b", "c"]

    def test_markdown_fenced(self):
        text = '```json\n{"name": "Alice"}\n```'
        result = parse_json(text)
        assert result == {"name": "Alice"}

    def test_markdown_fenced_no_lang(self):
        text = "```\n[1, 2, 3]\n```"
        result = parse_json(text)
        assert result == [1, 2, 3]

    def test_json_embedded_in_text(self):
        text = 'Here is the result: {"score": 85, "reasoning": "Good"} end.'
        result = parse_json(text)
        assert result["score"] == 85

    def test_nested_object(self):
        text = '{"outer": {"inner": 42}}'
        result = parse_json(text)
        assert result["outer"]["inner"] == 42

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty response"):
            parse_json("")

    def test_garbage_raises(self):
        with pytest.raises(ValueError, match="Could not parse JSON"):
            parse_json("this is not json at all")
