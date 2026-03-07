from unittest.mock import MagicMock, patch

import pytest

# Define modules to patch for torch-less environments
mock_torch = MagicMock()
mock_nn = MagicMock()


# We need nn.Module to be a real class so inheritance works
class MockModule:
    def __init__(self, *_args, **_kwargs):
        pass

    def __call__(self, *_args, **_kwargs):
        return MagicMock()

    def parameters(self):
        return [MagicMock()]

    def to(self, *_args, **_kwargs):
        return self

    def eval(self):
        return self

    def train(self):
        return self

    def named_parameters(self):
        return []

    def load_state_dict(self, *_args, **_kwargs):
        pass

    def state_dict(self):
        return {}


mock_nn.Module = MockModule
mock_torch.nn = mock_nn
mock_torch.optim.AdamW = MagicMock()
mock_torch.nn.CrossEntropyLoss = MagicMock()
mock_torch.device.return_value = "cpu"
mock_torch.no_grad.return_value = MagicMock()
mock_torch.isnan.return_value = False
mock_torch.isinf.return_value = False

modules_to_patch = {
    "torch": mock_torch,
    "torch.nn": mock_nn,
    "torch.nn.functional": MagicMock(),
    "torch.optim": mock_torch.optim,
}

with patch.dict("sys.modules", modules_to_patch):
    from llm_cli.clients.mamba import ByteTokenizer, MambaClient
    from llm_cli.modules.models import DataSource


@pytest.fixture
def mamba_client():
    with patch.dict("sys.modules", modules_to_patch):
        with patch("llm_cli.clients.mamba.get_setting", return_value=None):
            with patch("llm_cli.clients.mamba.MambaLM"):
                with patch("torch.load", return_value={}):
                    client = MambaClient(initial_model_alias="default")
                    client.teacher_enabled = False  # Explicitly disable for most tests
                    return client


def test_mamba_tokenizer_edge_cases():
    tokenizer = ByteTokenizer()
    # Test filtering of control characters
    # 0 is a control char, not in safe_control_ids
    assert tokenizer.decode([0, 10, 127]) == "\n"
    # Test decoding with pending bytes
    encoded = list(b"Hello") + [257]
    assert tokenizer.decode(encoded) == "Hello<|im_end|>"


def test_mamba_initialize_teacher_success():
    import llm_cli.clients.config as config_mod

    # Save old cache
    old_cache = config_mod._config_cache
    config_mod._config_cache = {
        "mamba": {
            "teacher_enabled": True,
            "teacher_provider": "ollama",
            "teacher_model": "llama3",
        }
    }

    try:
        with patch("llm_cli.security.intent_analyzer.IntentAnalyzer") as mock_analyzer:
            with patch("llm_cli.clients.mamba.MambaLM"):
                with patch("torch.load", return_value={}):
                    mock_analyzer.return_value.client = MagicMock()
                    client = MambaClient(initial_model_alias="default")
                    assert client.teacher_enabled is True
                    assert client.teacher_client is not None
    finally:
        config_mod._config_cache = old_cache


def test_mamba_initialize_teacher_invalid_provider():
    import llm_cli.clients.config as config_mod

    old_cache = config_mod._config_cache
    config_mod._config_cache = {
        "mamba": {
            "teacher_enabled": True,
            "teacher_provider": "openai",  # Restricted to ollama/vllm
            "teacher_model": "gpt-4",
        }
    }

    try:
        with patch("llm_cli.clients.mamba.MambaLM"):
            with patch("torch.load", return_value={}):
                client = MambaClient(initial_model_alias="default")
                assert client.teacher_enabled is False
    finally:
        config_mod._config_cache = old_cache


def test_mamba_initialize_teacher_missing_config(mamba_client):
    with patch("llm_cli.clients.mamba.get_setting", return_value=None):
        mamba_client._initialize_teacher()
        assert mamba_client.teacher_enabled is False


def test_mamba_initialize_teacher_exception(mamba_client):
    with patch("llm_cli.clients.mamba.get_setting") as mock_get:
        mock_get.side_effect = lambda key, _section: {
            "teacher_enabled": True,
            "teacher_provider": "ollama",
            "teacher_model": "llama3",
        }.get(key)
        with patch(
            "llm_cli.security.intent_analyzer.IntentAnalyzer",
            side_effect=Exception("Init fail"),
        ):
            mamba_client._initialize_teacher()
            assert mamba_client.teacher_enabled is False


def test_mamba_generate_mamba_no_model(mamba_client):
    mamba_client.model_instance = None
    resp, thought = mamba_client._generate_mamba()
    assert "Error: Model not initialized" in resp


def test_mamba_online_update_no_model(mamba_client):
    mamba_client.model_instance = None
    loss = mamba_client._online_update("user", "target")
    assert loss is None


def test_mamba_online_update_high_loss(mamba_client):
    mamba_client.model_instance = MagicMock()
    mamba_client.optimizer = MagicMock()
    mamba_client.max_loss_threshold = 1.0

    mock_loss = MagicMock()
    mock_loss.item.return_value = 5.0  # Higher than threshold
    mamba_client.criterion.return_value = mock_loss

    loss = mamba_client._online_update("user", "target")
    assert loss is None
    mamba_client.optimizer.step.assert_not_called()


def test_mamba_send_with_teacher_and_correction(mamba_client):
    mamba_client.teacher_enabled = True
    mamba_client.teacher_client = MagicMock()

    # Mock _generate_mamba to return bad output first, then good output?
    # Actually _send uses it to get mamba_output.
    with patch.object(
        mamba_client, "_generate_mamba", return_value=('{"message": "Bad"}', None)
    ):
        with patch.object(mamba_client, "_get_mentor_review") as mock_review:
            # First attempt: invalid, gives correction
            mock_review.return_value = (False, "Fix it", '{"message": "Fixed"}')

            with patch.object(mamba_client, "_online_update", return_value=0.1):
                with patch.object(mamba_client, "_log_metrics"):
                    data = [DataSource(content="Hi", is_file_or_url=False)]
                    (resp, thought), usage = mamba_client._send(data)

                    assert resp == "Fixed"
                    assert mock_review.call_count == 2  # 2 attempts max


def test_mamba_get_mentor_review_exception(mamba_client):
    mamba_client.teacher_client = MagicMock()
    mamba_client.teacher_client._send.side_effect = Exception("API Fail")

    is_valid, critique, correction = mamba_client._get_mentor_review("user", "output")
    assert is_valid is True
    assert critique == ""


def test_mamba_send_json_fallback_parsing(mamba_client):
    # Ensure teacher is disabled to avoid slow Mentor calls
    mamba_client.teacher_enabled = False
    # Test fallback to tag parsing when JSON fails
    with patch.object(
        mamba_client,
        "_generate_mamba",
        return_value=('<tool_call>{"name": "test"}</tool_call> Just text', None),
    ):
        with patch.object(mamba_client, "_log_metrics"):
            data = [DataSource(content="Hi", is_file_or_url=False)]
            (resp, thought), usage = mamba_client._send(data)

            assert "Just text" in resp
            # Check if tool call was added to conversation
            last_msg = mamba_client.conversation[-1]
            assert any(p.function_call for p in last_msg.parts)


def test_mamba_log_metrics_exception(mamba_client):
    with patch("pathlib.Path.open", side_effect=Exception("Disk full")):
        # Should not raise
        mamba_client._log_metrics({"test": 1})


def test_mamba_initialize_model_with_path(mamba_client):
    with patch("llm_cli.clients.mamba.get_setting", return_value="/tmp/model.pt"):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("torch.load", return_value={}):
                mamba_client._initialize_model()
                assert mamba_client.model_instance is not None


def test_mamba_initialize_model_load_exception(mamba_client):
    with patch("llm_cli.clients.mamba.get_setting", return_value="/tmp/model.pt"):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("torch.load", side_effect=Exception("Corrupt")):
                # Should not raise, just print error
                mamba_client._initialize_model()


def test_mamba_online_update_save_exception(mamba_client):
    mamba_client.model_instance = MagicMock()
    mamba_client.optimizer = MagicMock()

    mock_loss = MagicMock()
    mock_loss.item.return_value = 0.1

    with patch("llm_cli.clients.mamba.torch.nn.CrossEntropyLoss") as mock_crit_class:
        mock_crit = mock_crit_class.return_value
        mock_crit.return_value = mock_loss
        mamba_client.criterion = mock_crit

        with patch("torch.save", side_effect=Exception("Permission denied")):
            # Should log error and not crash
            loss = mamba_client._online_update("user", "target")
            assert loss == 0.1


def test_mamba_generate_mamba_loop(mamba_client):
    mock_instance = MagicMock()
    mamba_client.model_instance = mock_instance

    # Reset global mock_torch to avoid side effects from other tests
    mock_torch.argmax.reset_mock()
    mock_torch.argmax.return_value = MagicMock()

    # step should return (logits, states)
    mock_logits = MagicMock()
    mock_states = MagicMock()
    mock_instance.step.return_value = (mock_logits, mock_states)

    # torch.argmax should return a mock token whose item() returns our desired sequence
    mock_next_token = MagicMock()
    # first call (pre-loop) item() -> 100, second call (in loop) item() -> 257
    mock_next_token.item.side_effect = [100, 257, 257]

    # We must ensure torch.argmax returns mock_next_token
    mock_torch.argmax.return_value = mock_next_token

    with patch.object(mamba_client.tokenizer, "decode", return_value="Hello"):
        # We don't need another patch here if mock_torch.argmax is already set
        resp, thought = mamba_client._generate_mamba()
        assert resp == "Hello"
        # Initial step + 1 step in loop
        assert mock_instance.step.call_count == 2
