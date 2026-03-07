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
    from llm_cli.modules.models import DataSource


def test_byte_tokenizer():
    with patch.dict("sys.modules", modules_to_patch):
        from llm_cli.clients.mamba import ByteTokenizer

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
    from llm_cli.clients.mamba import MambaClient

    with patch.dict("sys.modules", modules_to_patch):
        with patch("llm_cli.clients.mamba.get_setting", return_value=None):
            with patch.object(MambaClient, "_initialize_model"):
                client = MambaClient(initial_model_alias="default")
                assert client.config_section == "mamba"


@patch("llm_cli.clients.mamba.MambaLM")
def test_mamba_client_send(mock_mamba_lm_class):
    with patch.dict("sys.modules", modules_to_patch):
        from llm_cli.clients.mamba import MambaClient
        from llm_cli.modules.models import Role

        # Initialize with mocked methods to avoid real torch/heavy work
        with patch.object(MambaClient, "_initialize_model"):
            with patch.object(MambaClient, "_initialize_teacher"):
                with patch("llm_cli.clients.mamba.get_setting", return_value=None):
                    client = MambaClient(initial_model_alias="default")
                    client.model_instance = MagicMock()
                    client.optimizer = MagicMock()
                    client.conversation = []
                    client.turn_count = 0
                    client.teacher_enabled = False

                    # Mock _generate_mamba and _log_metrics
                    with patch.object(
                        client,
                        "_generate_mamba",
                        return_value=('{"message": "Hello"}', None),
                    ) as mock_gen:
                        with patch.object(client, "_log_metrics") as mock_log:
                            data = [DataSource(content="Hi", is_file_or_url=False)]
                            (resp, thought), usage = client._send(data)

                            assert "Hello" in resp
                            assert mock_gen.called
                            assert mock_log.called
                            # Verify conversation history update
                            assert len(client.conversation) == 2  # User + Model
                            assert client.conversation[0].role == Role.USER
                            assert client.conversation[1].role == Role.MODEL
