"""Tests for BaseLlmClient base class functionality."""

import pytest
from unittest.mock import patch
from llm_cli.clients.base import BaseLlmClient


class TestBaseLlmClient:
    """Test suite for BaseLlmClient base class."""

    @pytest.fixture
    def concrete_client(self, mock_config):
        """Create a concrete implementation of BaseLlmClient for testing."""
        class ConcreteClient(BaseLlmClient):
            def _load_model_aliases(self):
                self.available_models = {'default': 'test-model'}

            def _send(self, data):
                return "test response", {"tokens": 100}

        return ConcreteClient(
            initial_model_alias='default',
            api_key_name='api_key',
            config_section='google',
            pdf_as_base64=True,
            stdout=False
        )

    def test_initialization(self, concrete_client):
        """Test that client initializes correctly."""
        assert concrete_client.model == 'test-model'
        assert concrete_client.current_alias == 'default'
        assert concrete_client.pdf_as_base64 is True
        assert concrete_client.conversation == []

    def test_set_model_success(self, concrete_client):
        """Test switching to an available model."""
        concrete_client.available_models['pro'] = 'test-model-pro'
        result = concrete_client.set_model('pro')
        assert result is True
        assert concrete_client.current_alias == 'pro'
        assert concrete_client.model == 'test-model-pro'

    def test_set_model_failure(self, concrete_client):
        """Test switching to a non-existent model."""
        result = concrete_client.set_model('nonexistent')
        assert result is False
        assert concrete_client.current_alias == 'default'

    def test_process_file_text(
        self, concrete_client, temp_text_file, sample_text_content
    ):
        """Test processing a text file via media_utils."""
        from llm_cli.modules.media_utils import process_file
        result = process_file(temp_text_file, pdf_as_base64=False)
        assert result is not None
        assert result['content'] == sample_text_content
        assert result['content_type'] == 'text/plain'

    def test_process_file_empty(self, concrete_client, temp_empty_file):
        """Test that empty files are handled by media_utils."""
        from llm_cli.modules.media_utils import process_file
        result = process_file(temp_empty_file)
        assert result is None

    def test_process_sources_text_input(self, concrete_client):
        """Test processing plain text sources."""
        sources = ["Hello world"]
        data = []
        for source in sources:
            source_data = concrete_client._process_single_source(source)
            if source_data:
                data.append(source_data)

        assert len(data) == 1
        assert data[0]['content'] == "Hello world"
        assert data[0]['content_type'] == 'text/plain'

    def test_process_single_source_media(self, concrete_client, temp_text_file):
        """Test that media files are marked with is_file_or_url."""
        result = concrete_client._process_single_source(str(temp_text_file))
        assert result is not None
        assert result['is_file_or_url'] is True

    def test_save_inline_image(
        self, concrete_client, tmp_path, sample_image_base64
    ):
        """Test saving received image data to a file."""
        import os
        inline_data = {
            'mimeType': 'image/png',
            'data': sample_image_base64
        }

        # Test current dir for image saving
        log_entry = concrete_client._save_inline_image_and_get_log_entry(
            inline_data
        )
        assert log_entry is not None
        assert "output image" in log_entry

        # Cleanup
        filename = log_entry.split(": ")[1].strip("*")
        if os.path.exists(filename):
            os.remove(filename)

    def test_talk_delegates_to_session(self, concrete_client):
        """Test that talk() instantiates ChatSession and calls run()."""
        with patch('llm_cli.clients.session.ChatSession') as mock_session_cls:
            mock_session = mock_session_cls.return_value
            concrete_client.talk()
            mock_session_cls.assert_called_once_with(concrete_client)
            mock_session.run.assert_called_once()
