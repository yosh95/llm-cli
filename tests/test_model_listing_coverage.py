from unittest.mock import MagicMock, patch

import pytest

from llm_cli.apps.model_listing import ModelListingConfig, list_models


@pytest.fixture
def mock_get_setting():
    with patch("llm_cli.apps.model_listing.get_setting") as mock:
        yield mock


@pytest.fixture
def mock_requests_get():
    with patch("llm_cli.apps.model_listing.requests.get") as mock:
        yield mock


def test_list_models_missing_api_key(mock_get_setting):
    mock_get_setting.return_value = None
    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
    )
    with pytest.raises(SystemExit) as excinfo:
        list_models(config)
    assert excinfo.value.code == 1


def test_list_models_request_failure(mock_get_setting, mock_requests_get):
    mock_get_setting.return_value = "fake-key"
    mock_requests_get.side_effect = Exception("Network error")

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
    )

    with patch("sys.argv", ["script"]):
        with pytest.raises(SystemExit) as excinfo:
            list_models(config)
    assert excinfo.value.code == 1


def test_list_models_missing_data_key(mock_get_setting, mock_requests_get, capsys):
    mock_get_setting.return_value = "fake-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {"error": "something"}
    mock_requests_get.return_value = mock_response

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
    )

    with patch("sys.argv", ["script"]):
        list_models(config)

    captured = capsys.readouterr()
    assert '"error": "something"' in captured.out


def test_list_models_filter_by_name_with_extractor(
    mock_get_setting, mock_requests_get, capsys
):
    mock_get_setting.return_value = "fake-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "model-1", "custom_name": "Model One"},
            {"id": "model-2", "custom_name": "Model Two"},
        ]
    }
    mock_requests_get.return_value = mock_response

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
        extract_model_name=lambda m: m["custom_name"],
    )

    # Filter for "Model One"
    with patch("sys.argv", ["script", "Model One"]):
        list_models(config)

    captured = capsys.readouterr()
    assert '"custom_name": "Model One"' in captured.out
    assert "model-2" not in captured.out


def test_list_models_filter_by_name_no_extractor(
    mock_get_setting, mock_requests_get, capsys
):
    mock_get_setting.return_value = "fake-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "model-1"}, {"name": "model-2"}]}
    mock_requests_get.return_value = mock_response

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
    )

    with patch("sys.argv", ["script", "model-1"]):
        list_models(config)

    captured = capsys.readouterr()
    assert '"id": "model-1"' in captured.out
    assert "model-2" not in captured.out


def test_list_models_non_verbose_no_extractor(
    mock_get_setting, mock_requests_get, capsys
):
    mock_get_setting.return_value = "fake-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "model-1"}, {"name": "model-2"}]}
    mock_requests_get.return_value = mock_response

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
    )

    with patch("sys.argv", ["script"]):
        list_models(config)

    captured = capsys.readouterr()
    assert "model-1" in captured.out
    assert "model-2" in captured.out


def test_list_models_verbose_custom_columns(
    mock_get_setting, mock_requests_get, capsys
):
    mock_get_setting.return_value = "fake-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"id": "model-a", "type": "chat"}, {"id": "model-b", "type": "embed"}]
    }
    mock_requests_get.return_value = mock_response

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
        columns=[
            ("ID", "id"),
            ("Kind", lambda m: m["type"].upper()),
            ("Static", 123),  # Non-string, non-callable to hit line 158
        ],
        extract_model_name=lambda m: m["id"],
    )

    with patch("sys.argv", ["script", "-v"]):
        list_models(config)

    captured = capsys.readouterr()
    assert "ID" in captured.out
    assert "Kind" in captured.out
    assert "CHAT" in captured.out
    assert "123" in captured.out


def test_list_models_callbacks(mock_get_setting, mock_requests_get):
    mock_get_setting.return_value = "my-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": []}
    mock_requests_get.return_value = mock_response

    build_url = MagicMock(return_value="http://custom.url")
    build_headers = MagicMock(return_value={"X-Test": "Val"})

    config = ModelListingConfig(
        provider_name="TestProvider",
        config_section="test",
        api_key_setting="key",
        api_url="http://api.test",
        response_data_key="data",
        build_url=build_url,
        build_headers=build_headers,
    )

    with patch("sys.argv", ["script"]):
        list_models(config)

    build_url.assert_called_once_with("http://api.test", "my-key")
    build_headers.assert_called_once_with("my-key")
    mock_requests_get.assert_called_once()
    args, kwargs = mock_requests_get.call_args
    assert args[0] == "http://custom.url"
    assert kwargs["headers"]["X-Test"] == "Val"
