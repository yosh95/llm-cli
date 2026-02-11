from unittest.mock import MagicMock, patch

from llm_cli.apps import ollama_models, vllm_models


def test_ollama_models_url_parsing():
    """Test that ollama_models correctly parses the API URL from config."""
    with (
        patch("llm_cli.apps.ollama_models.get_setting") as mock_get_setting,
        patch("llm_cli.apps.ollama_models.requests.get") as mock_get,
        patch("llm_cli.apps.ollama_models.Console"),
    ):
        # Case 1: Standard URL with /v1/chat/completions
        mock_get_setting.return_value = "http://custom-host:11434/v1/chat/completions"
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": []}
        mock_get.return_value = mock_response

        ollama_models.main()

        # Should extract base URL and append /api/tags
        mock_get.assert_called_with(
            "http://custom-host:11434/api/tags",
            headers={"Connection": "close"},
            timeout=5,
        )

        # Case 2: URL without path
        mock_get_setting.return_value = "http://another-host:1234"
        ollama_models.main()
        mock_get.assert_called_with(
            "http://another-host:1234/api/tags",
            headers={"Connection": "close"},
            timeout=5,
        )


def test_vllm_models_url_config():
    """Test that vllm_models correctly uses the API URL from config."""
    with (
        patch("llm_cli.apps.vllm_models.get_setting") as mock_get_setting,
        patch("llm_cli.apps.vllm_models.list_models") as mock_list_models,
    ):
        # Case 1: Config is set
        mock_get_setting.return_value = "http://vllm-host:8000/v1/chat/completions"

        vllm_models.main()

        # Check that the config object passed to list_models has the correct URL
        # The logic in vllm_models replaces /chat/completions with /models
        args, _ = mock_list_models.call_args
        config = args[0]
        assert config.api_url == "http://vllm-host:8000/v1/models"

        # Case 2: Config is None (should fallback to default)
        mock_get_setting.return_value = None

        vllm_models.main()

        args, _ = mock_list_models.call_args
        config = args[0]
        assert config.api_url == "http://localhost:8000/v1/models"
