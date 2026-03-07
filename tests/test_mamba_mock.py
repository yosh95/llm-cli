from unittest.mock import MagicMock, patch

# Mock torch BEFORE importing any mamba-related modules
mock_torch = MagicMock()
mock_nn = MagicMock()
mock_nn_functional = MagicMock()


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


mock_nn.Module = MockModule
mock_torch.nn = mock_nn
mock_torch.nn.functional = mock_nn_functional
mock_torch.device.return_value = "cpu"
mock_torch.long = "long"
mock_torch.float32 = "float32"
mock_torch.optim.AdamW = MagicMock()
mock_torch.nn.CrossEntropyLoss = MagicMock()
mock_torch.no_grad.return_value = MagicMock()

# Mock tensor operations
mock_tensor = MagicMock()
mock_torch.tensor.return_value = mock_tensor
mock_torch.argmax.return_value = MagicMock()

modules_to_patch = {
    "torch": mock_torch,
    "torch.nn": mock_nn,
    "torch.nn.functional": mock_nn_functional,
    "torch.optim": mock_torch.optim,
}

with patch.dict("sys.modules", modules_to_patch):
    from llm_cli.clients.mamba import ByteTokenizer, MambaClient
    from llm_cli.modules.models import DataSource


def test_byte_tokenizer():
    tokenizer = ByteTokenizer()
    text = "Hello <|im_start|>world<|im_end|>"
    encoded = tokenizer.encode(text)
    assert isinstance(encoded, list)
    assert 256 in encoded
    assert 257 in encoded

    decoded = tokenizer.decode(encoded)
    assert "Hello" in decoded
    assert "world" in decoded


def test_mamba_client_init():
    with patch.dict("sys.modules", modules_to_patch):
        with patch("llm_cli.clients.mamba.get_setting", return_value=None):
            client = MambaClient(initial_model_alias="default")
            assert client.config_section == "mamba"


@patch("llm_cli.clients.mamba.MambaLM")
def test_mamba_client_send(mock_mamba_lm_class):
    mock_instance = mock_mamba_lm_class.return_value
    # step should return (logits, states)
    mock_logits = MagicMock()
    mock_states = MagicMock()
    mock_instance.step.return_value = (mock_logits, mock_states)

    with patch.dict("sys.modules", modules_to_patch):
        with patch("llm_cli.clients.mamba.get_setting", return_value=None):
            with patch("torch.load", return_value={}):
                client = MambaClient(initial_model_alias="default")
                client.model_instance = mock_instance

                # Setup mocks for generate loop
                # next_token.item() should return im_end_token (257) to exit the loop
                mock_next_token = MagicMock()
                mock_next_token.item.return_value = 257
                mock_torch.argmax.return_value = mock_next_token

                # Mock decode to return some text
                with patch.object(
                    ByteTokenizer, "decode", return_value='{"message": "Hello"}'
                ):
                    data = [DataSource(content="Hi", is_file_or_url=False)]
                    (resp, thought), usage = client._send(data)

                    assert "Hello" in resp
