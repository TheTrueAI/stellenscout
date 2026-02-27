"""Tests for immermatch.llm — parse_json() and call_gemini() retry logic."""

from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError

from immermatch.llm import call_gemini, parse_json


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


class TestCallGemini:
    """Tests for call_gemini() retry logic — mock client.models.generate_content + time.sleep."""

    def _make_client(self, side_effects: list) -> MagicMock:
        client = MagicMock()
        client.models.generate_content.side_effect = side_effects
        return client

    def _make_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.text = text
        return resp

    @patch("immermatch.llm.time.sleep")
    def test_success_first_try(self, mock_sleep: MagicMock):
        client = self._make_client([self._make_response("hello")])

        result = call_gemini(client, "prompt")

        assert result == "hello"
        mock_sleep.assert_not_called()

    @patch("immermatch.llm.time.sleep")
    def test_retries_on_server_error(self, mock_sleep: MagicMock):
        client = self._make_client(
            [
                ServerError(503, {"error": "Unavailable"}),
                self._make_response("recovered"),
            ]
        )

        result = call_gemini(client, "prompt")

        assert result == "recovered"
        assert mock_sleep.call_count == 1

    @patch("immermatch.llm.time.sleep")
    def test_retries_on_429_client_error(self, mock_sleep: MagicMock):
        client = self._make_client(
            [
                ClientError(429, {"error": "RESOURCE_EXHAUSTED"}),
                self._make_response("ok"),
            ]
        )

        result = call_gemini(client, "prompt")

        assert result == "ok"
        assert mock_sleep.call_count == 1

    @patch("immermatch.llm.time.sleep")
    def test_raises_immediately_on_non_429_client_error(self, mock_sleep: MagicMock):
        client = self._make_client([ClientError(400, {"error": "Bad Request"})])

        with pytest.raises(ClientError):
            call_gemini(client, "prompt")

        mock_sleep.assert_not_called()
