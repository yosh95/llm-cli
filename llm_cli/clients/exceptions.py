# llm_cli/clients/exceptions.py


class ProviderSwitchRequest(Exception):
    """Exception raised to request a switch to a different LLM provider."""

    def __init__(self, provider: str):
        self.provider = provider


class CheckpointRequest(Exception):
    """Exception raised to request a conversation checkpoint (summarization)."""

    pass


class TemplateRequest(Exception):
    """Exception raised to request loading a template into the input buffer."""

    def __init__(self, text: str):
        self.text = text


class ExitRequest(Exception):
    """Exception raised to request exiting the application."""

    pass
