import sys
from unittest.mock import MagicMock, patch

from llm_cli.apps.claude_models import main as claude_main
from llm_cli.apps.gemini_models import main as gemini_main
from llm_cli.apps.grok_models import main as grok_main
from llm_cli.apps.ollama_models import main as ollama_main
from llm_cli.apps.openai_models import main as openai_main
from llm_cli.apps.vllm_models import main as vllm_main


@patch("llm_cli.apps.model_listing.requests.get")
@patch("llm_cli.apps.model_listing.get_setting", return_value="fake-key")
def test_model_scripts(mock_get_setting, mock_requests_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"id": "test-model"}],
        "models": [{"name": "models/test-model"}],
    }
    mock_requests_get.return_value = mock_response

    with patch.object(sys, "argv", ["script"]):
        gemini_main()
        openai_main()
        claude_main()
        grok_main()
        ollama_main()
        vllm_main()
