"""Tests for PDF processing functionality across providers using dataclasses."""

from unittest.mock import MagicMock, patch

from llm_cli.clients.claude import ClaudeClient
from llm_cli.clients.gemini import GeminiClient
from llm_cli.clients.grok import GrokClient
from llm_cli.clients.openai import OpenAIClient
from llm_cli.modules.models import DataSource


class TestPDFProcessing:
    """Test suite for PDF processing in different providers."""

    def test_gemini_pdf_as_base64(self, mock_config, temp_pdf_file):  # noqa: ARG002
        """Test that Gemini processes PDFs as base64."""
        client = GeminiClient(initial_model_alias="default", stdout=True)
        assert client.pdf_as_base64 is True

        result = client._process_single_source(str(temp_pdf_file))
        assert isinstance(result, DataSource)
        assert result.content_type == "application/pdf"

    def test_openai_pdf_extraction(self, mock_config, temp_pdf_file):  # noqa: ARG002
        """Test that OpenAI processes PDFs as base64."""
        client = OpenAIClient(initial_model_alias="default", stdout=True)
        assert client.pdf_as_base64 is True

        result = client._process_single_source(str(temp_pdf_file))
        assert isinstance(result, DataSource)
        assert result.content_type == "application/pdf"

    def test_claude_pdf_extraction(self, mock_config, temp_pdf_file):  # noqa: ARG002
        """Test that Claude processes PDFs as base64."""
        client = ClaudeClient(initial_model_alias="default", stdout=True)
        assert client.pdf_as_base64 is True

        result = client._process_single_source(str(temp_pdf_file))
        assert isinstance(result, DataSource)
        assert result.content_type == "application/pdf"

    def test_grok_pdf_extraction(self, mock_config, temp_pdf_file):  # noqa: ARG002
        """Test that Grok processes PDFs via text extraction."""
        client = GrokClient(initial_model_alias="default", stdout=True)
        assert client.pdf_as_base64 is False

        result = client._process_single_source(str(temp_pdf_file))
        assert isinstance(result, DataSource)
        assert result.content_type == "text/plain"

    def test_gemini_build_message_with_pdf(
        self,
        mock_config,  # noqa: ARG002
        sample_pdf_base64,
    ):
        """Test Gemini message building with PDF."""
        client = GeminiClient(initial_model_alias="default", stdout=True)

        data = [
            DataSource(
                content=sample_pdf_base64,
                content_type="application/pdf",
                is_file_or_url=True,
            )
        ]

        with patch("requests.post") as mock_post:
            mock_res = MagicMock()
            mock_res.status_code = 200
            # generateContent API response format
            mock_res.json.return_value = {
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": "OK"}]}}
                ],
                "usageMetadata": {"totalTokenCount": 5},
            }
            mock_post.return_value = mock_res

            client._send(data)

            args, kwargs = mock_post.call_args
            payload = kwargs.get("json") or args[1]

            # generateContent API uses 'contents' with inlineData parts
            assert "contents" in payload
            found_pdf = False
            for content_item in payload["contents"]:
                for part in content_item.get("parts", []):
                    inline = part.get("inlineData", {})
                    if inline.get("mimeType") == "application/pdf":
                        found_pdf = True
                        break

            assert found_pdf, f"PDF inlineData not found in contents: {payload}"

    def test_pdf_url_fetching_gemini(
        self,
        mock_config,  # noqa: ARG002
        mock_curl_requests,
        sample_pdf_content,
    ):
        """Test PDF URL fetching for Gemini (base64)."""
        mock_curl_requests.headers = {"Content-Type": "application/pdf"}
        mock_curl_requests.content = sample_pdf_content

        from llm_cli.modules.media_utils import fetch_url_content

        content, content_type = fetch_url_content(
            "https://example.com/test.pdf", pdf_as_base64=True
        )

        assert content is not None
        assert content_type == "application/pdf"
