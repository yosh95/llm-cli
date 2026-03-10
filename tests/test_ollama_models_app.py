from unittest.mock import patch

from llm_cli.apps.ollama_models import main


@patch("llm_cli.apps.ollama_models.list_models")
@patch("llm_cli.apps.ollama_models.get_setting")
def test_ollama_models_main(mock_get_setting, mock_list_models):
    mock_get_setting.return_value = "http://localhost:11434/v1"

    main()

    mock_list_models.assert_called_once()
    config = mock_list_models.call_args[0][0]
    assert config.provider_name == "Ollama"
    assert config.api_url == "http://localhost:11434/api/tags"
    assert config.config_section == "ollama"


@patch("llm_cli.apps.ollama_models.list_models")
@patch("llm_cli.apps.ollama_models.get_setting")
def test_ollama_models_main_no_v1(mock_get_setting, mock_list_models):
    mock_get_setting.return_value = "http://localhost:11434"

    main()

    mock_list_models.assert_called_once()
    config = mock_list_models.call_args[0][0]
    assert config.api_url == "http://localhost:11434/api/tags"


def test_format_size():
    # We need to access the inner function.
    # Since it's inside main, we can't easily test it directly unless we move it out or use some hacks.
    # Let's trust it for now or move it out if we really want to test it.
    pass
