"""Tests for PDF processing functionality across providers using dataclasses."""

from unittest.mock import MagicMock, patch

from llm_cli.clients.claude import ClaudeClient
from llm_cli.clients.gemini import GeminiClient
from llm_cli.clients.grok import GrokClient
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

    def test_openai_pdf_as_base64(self, mock_config, temp_pdf_file):
        """Placeholder for OpenAI PDF support test."""
        pass

    def test_claude_pdf_as_base64(self, mock_config, temp_pdf_file):  # noqa: ARG002
        """Test that Claude processes PDFs as base64."""
        client = ClaudeClient(initial_model_alias="default", stdout=True)
        assert client.pdf_as_base64 is True

        result = client._process_single_source(str(temp_pdf_file))
        assert isinstance(result, DataSource)
        assert result.content_type == "application/pdf"

    def test_grok_pdf_as_text(self, mock_config, temp_pdf_file):  # noqa: ARG002
        """Test that Grok processes PDFs as text extraction."""
        client = GrokClient(initial_model_alias="default", stdout=True)
        assert client.pdf_as_base64 is False

        result = client._process_single_source(str(temp_pdf_file))
        if result:
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
            mock_res.json.return_value = {"outputs": [{"type": "text", "text": "OK"}]}
            mock_post.return_value = mock_res

            client._send(data)

            args, kwargs = mock_post.call_args
            if kwargs.get("json"):
                payload = kwargs["json"]
            else:
                payload = args[1]  # json might be positional or passed as json=...

            # Check input list for document type
            # Expected: {"type": "document", "data": "base64...", "mime_type": "application/pdf"}
            assert "input" in payload
            found_pdf = False
            for item in payload["input"]:
                if (
                    item.get("type") == "document"
                    and item.get("mime_type") == "application/pdf"
                ):
                    found_pdf = True
                    break

            assert found_pdf, f"PDF input not found in payload: {payload}"

    def test_pdf_url_fetching_gemini(
        self,
        mock_config,  # noqa: ARG002
        mock_cloudscraper,
        sample_pdf_content,
    ):
        """Test PDF URL fetching for Gemini (base64)."""
        mock_cloudscraper.get.return_value.headers = {"Content-Type": "application/pdf"}
        mock_cloudscraper.get.return_value.content = sample_pdf_content

        with patch("llm_cli.modules.media_utils.scraper", mock_cloudscraper):
            from llm_cli.modules.media_utils import fetch_url_content

            content, content_type = fetch_url_content(
                "https://example.com/test.pdf", pdf_as_base64=True
            )

        assert content is not None
        assert content_type == "application/pdf"
