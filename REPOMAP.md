# Project Repository Map

This file is an automatically generated map of the project structure for LLM context.

## File Tree
```text
./
  .gitignore
  LICENSE
  README.md
  pyproject.toml
  pytest.ini
  llm_cli/
    __init__.py
    modules/
      __init__.py
      custom_markdown.py
      media_utils.py
      models.py
      tool_registry.py
      tools/
        __init__.py
        file_ops.py
        media.py
        system.py
        web.py
    apps/
      __init__.py
      claude_models.py
      cli_common.py
      configure.py
      defaults.toml
      gemini_models.py
      grok_models.py
      mcp_server.py
      model_listing.py
      ollama_models.py
      openai_models.py
      unified.py
    security/
      __init__.py
      audit.py
      command_validator.py
      path_validator.py
    clients/
      __init__.py
      base.py
      claude.py
      config.py
      gemini.py
      grok.py
      mcp_manager.py
      ollama.py
      openai.py
      session.py
  .pytest_cache/
    .gitignore
    CACHEDIR.TAG
    README.md
    v/
      cache/
        lastfailed
        nodeids
  .ruff_cache/
    .gitignore
    CACHEDIR.TAG
    0.14.11/
      17561854856620664191
      3602718424835133808
      5520045461155271223
    0.14.10/
      13579696590225924306
      5363627681121889373
      782179939944622823
  config/
    config.toml.sample
  scripts/
  tests/
    README.md
    __init__.py
    conftest.py
    test_agent_tools.py
    test_attachment.py
    test_audio_support.py
    test_base_client.py
    test_cli_args.py
    test_command_validator.py
    test_configure_utils.py
    test_conversation_history.py
    test_custom_model.py
    test_file_ops.py
    test_file_ops_edit.py
    test_gemini_features.py
    test_gemini_file_uri.py
    test_grep_validation.py
    test_log_trimming.py
    test_path_validator.py
    test_pdf_processing.py
    test_providers.py
    test_unified_provider_switching.py
    test_unified_video.py
    test_web_tools.py
  images/
    banner.jpeg
    browser_example.png
    google_search.png
    llm_cli_overview.jpg
    llm_cli_overview_en.jpg
```

## Definitions

### llm_cli/__init__.py
```python
# No classes or functions defined.
```

### llm_cli/modules/__init__.py
```python
# No classes or functions defined.
```

### llm_cli/modules/custom_markdown.py
```python
class CustomTableElement:
    def __rich_console__(self, console, options)
class CustomMarkdown:
    def __init__(self, markup)  # Initialize CustomMarkdown with custom table element.
```

### llm_cli/modules/media_utils.py
```python
def validate_url(url)
def read_pdf_text(source)
def encode_file_base64(path)
def fetch_url_content(url, pdf_as_base64)
def process_file(path, pdf_as_base64)
def generate_safe_filename(text, prefix, ext, max_len)  # Generates a safe and descriptive filename from text.
```

### llm_cli/modules/models.py
```python
class Role:
class ContentPart:  # A part of a message, which can be text or other data.
class Message:  # A single message in a conversation.
    def get_text(self)  # Helper to extract all text content from parts.
class DataSource:  # Input data sourced from files, URLs, or direct text.
class Usage:  # Token usage tracking.
class ClientState:  # Current state of an LLM client session.
```

### llm_cli/modules/tool_registry.py
```python
class ToolRegistry:  # Registry for managing local and remote (MCP) tools.
    def __init__(self)
    def register_shutdown_hook(self, func)  # Registers a function to be called when the application exits.
    def shutdown(self)  # Executes all registered shutdown hooks.
    def register(self, name, func, description, parameters, supported_providers, interactive, skip_approval)  # Registers a tool in the registry.
    def register_remote_tools(self, mcp_manager)
    def discover_local_tools(self)
    def get_tool_schemas(self, active_tools, provider)
    def get_active_names(self, names, provider)
    def _get_active(self, names, provider)
    def get_gemini_spec(self, names, provider)
    def get_openai_spec(self, names, provider)
    def get_anthropic_spec(self, names, provider)
def tool(name, description, parameters, supported_providers, desc, params, interactive, skip_approval)
```

### llm_cli/modules/tools/__init__.py
```python
# No classes or functions defined.
```

### llm_cli/modules/tools/file_ops.py
```python
def list_files(directory, depth, max_files)  # Lists files in a directory tree, excluding common noise directories
def read_file(path, start_line, end_line)
def write_file(path, content)
def edit_file(path, search, replace)  # Search and replace a specific block of text in a file.
```

### llm_cli/modules/tools/media.py
```python
def attach_file(path)
```

### llm_cli/modules/tools/system.py
```python
def set_resource_limits(mem_limit_mb)  # Sets resource limits for the child process. (Linux/Unix only)
def execute_command(command)
```

### llm_cli/modules/tools/web.py
```python
def google_search(queries, num)
def fetch_url(url)
def fetch_web_text(url)
```

### llm_cli/apps/__init__.py
```python
# No classes or functions defined.
```

### llm_cli/apps/claude_models.py
```python
def main()  # List available Claude models.
```

### llm_cli/apps/cli_common.py
```python
# Shared CLI entry point functionality for all LLM clients.
class ClientConfig:  # Configuration for CLI entry point.
def create_standard_parser(config)
def run_client_cli(config)
```

### llm_cli/apps/configure.py
```python
def load_config()  # Loads the configuration file and returns it as a dictionary.
def save_config(config)  # Saves the configuration dictionary to the file.
def prompt_input(prompt_text, current_value, secret, completer)  # Displays a prompt and returns user input or current value.
def prompt_bool(prompt_text, current_value)  # Prompts for a boolean value.
def prompt_list(prompt_text, current_value)  # Prompts for a comma-separated list.
def configure_provider(config, provider, name)  # Interactively configures a specific LLM provider.
def configure_general(config)  # Configures general application settings, including data paths.
def configure_mcp(config)  # Configures MCP servers.
def mask_secrets(data)  # Recursively mask sensitive information in configuration data.
def main()
```

### llm_cli/apps/gemini_models.py
```python
def main()  # List available Google Gemini models.
```

### llm_cli/apps/grok_models.py
```python
def main()  # List available Grok (xAI) models.
```

### llm_cli/apps/mcp_server.py
```python
def create_mcp_server()  # Create and configure the FastMCP server instance.
def main()  # Run the MCP server in stdio mode.
```

### llm_cli/apps/model_listing.py
```python
# Shared model listing functionality for all LLM providers.
class ModelListingConfig:  # Configuration for provider-specific model listing.
def create_model_listing_parser()  # Create standard argument parser for model listing tools.
def list_models(config)  # Generic model listing implementation.
```

### llm_cli/apps/ollama_models.py
```python
def main()
```

### llm_cli/apps/openai_models.py
```python
def main()  # List available OpenAI models.
```

### llm_cli/apps/unified.py
```python
class UnifiedClient:  # A unified client capable of switching between multiple
    def __init__(self, initial_provider)
    def conversation(self)
    def conversation(self, value)
    def live_debug(self)
    def live_debug(self, value)
    def tools_enabled(self)
    def tools_enabled(self, value)
    def reasoning_enabled(self)
    def reasoning_enabled(self, value)
    def _activate_provider(self, provider_alias)
    def _load_model_aliases(self)  # Handled by sub-clients.
    def set_model(self, alias)
    def set_custom_model(self, model_name)  # Sets a custom model for the active client.
    def _process_single_source(self, source)  # Delegate source processing to the active provider client.
    def _handle_command(self, user_input, sources, pending_data)
    def _send(self, data)
    def _has_pending_tool_calls(self)
def main()
```

### llm_cli/security/__init__.py
```python
# No classes or functions defined.
```

### llm_cli/security/audit.py
```python
def log_audit(tool_name, args, output, exit_code, error)  # Logs tool execution (especially command execution) for auditing purposes.
def _trim_log_file(path, max_lines)  # Keeps the log file within the specified line limit.
```

### llm_cli/security/command_validator.py
```python
class CommandValidationError:  # Raised when a command fails security validation.
class CommandValidator:  # Validates shell commands against a whitelist of allowed commands.
    def __init__(self, custom_whitelist, allow_dangerous_patterns, mcp_mode)
    def validate(self, command)
    def _check_python_oneliner_pre_parse(self, command)  # Specifically check for python -c one-liners before other pattern checks.
    def _validate_parts(self, parts)
    def _check_dangerous_patterns(self, command)
    def _check_paths(self, parts)
    def _check_dangerous_arguments(self, base_command, parts)
def validate_command(command, custom_whitelist)
def validate_mcp_command(command)
```

### llm_cli/security/path_validator.py
```python
class PathValidationError:  # Raised when a path fails security validation.
def validate_path(path, allow_outside_cwd)  # Validates a path against security policies:
```

### llm_cli/clients/__init__.py
```python
# No classes or functions defined.
```

### llm_cli/clients/base.py
```python
class ProviderSwitchRequest:  # Exception raised to request a switch to a different LLM provider.
    def __init__(self, provider)
class CheckpointRequest:  # Exception raised to request a conversation checkpoint (summarization).
class TemplateRequest:  # Exception raised to request loading a template into the input buffer.
    def __init__(self, text)
class BaseLlmClient:  # Abstract Base Class for LLM API clients.
    def __init__(self, initial_model_alias, api_key_name, config_section, pdf_as_base64, stdout, render_markdown, initial_tools, disable_system_prompt, enable_mcp, live_debug)  # Initializes the LLM client with configuration and state.
    def _init_mcp(self, update_active_tools)  # Initializes Model Context Protocol (MCP) tools.
    def _expand(self, p)  # Expands user path symbols.
    def _load_model_aliases(self)  # Loads model aliases from the configuration.
    def _send(self, data)  # Sends the request to the specific provider API.
    def _post_with_retry(self, url, headers, json_data, timeout, max_retries)  # Performs a POST request with automatic retry and exponential backoff.
    def set_model(self, alias)  # Sets the active model using its alias.
    def set_custom_model(self, model_name)  # Sets a custom model that is not in the configuration.
    def talk(self, initial_data, sources)  # Starts an interactive chat session.
    def process_sources(self, sources)  # Processes a list of input sources (files, URLs, text).
    def _process_single_source(self, source)  # Processes a single source string into a DataSource object.
    def _has_pending_tool_calls(self)  # Checks if the last model response contains tool calls.
    def load_session(self, path_str)  # Loads a conversation session from a JSON file.
    def _handle_command(self, user_input, sources, pending_data)  # Handles in-chat slash commands.
    def _print_help(self)
    def _trim_log_file(self, path, max_lines)
    def _save_inline_image_and_get_log_entry(self, inline_data, hint_text)  # Saves inline image data (base64) to a file and returns a formatted display
    def _log_debug(self, response_obj, request_payload, response_content)
    def _print_live_debug(self, timestamp, response_obj, request_payload, response_content)
    def _report_error(self, provider_name, e)
    def get_model_icon(self)  # Get an appropriate icon for the current model provider.
    def get_display_name(self)  # Get the formatted display name including icon and model path.
    def _format_response_text(self, text)
```

### llm_cli/clients/claude.py
```python
class ClaudeClient:  # Client for interacting with the Anthropic Claude API.
    def __init__(self, initial_model_alias)  # Initializes the Claude client.
    def _load_model_aliases(self)  # Loads model aliases from the configuration.
    def _send(self, data)  # Sends the conversation history and new data to Claude.
    def _update_history(self, data, model_msg)  # Updates the internal conversation history with new messages.
    def _build_messages(self, data)  # Converts internal conversation history to Claude API format.
```

### llm_cli/clients/config.py
```python
def _load_config_from_file()  # Loads configuration from the TOML file and caches it.
def get_setting(key, section)  # Gets a specific setting value from a section in the config file.
def get_bool_setting(key, section, default)  # Gets a boolean setting value from a section in the config file.
def get_model_aliases(section)  # Loads all model aliases from a specific section in the config file.
def get_all_model_aliases()  # Loads model alias configurations for all supported providers.
def get_provider_tools(section)
def get_mcp_servers()  # Loads MCP server configurations from the config file.
def get_templates()  # Loads prompt templates from the [templates] section of the config file.
```

### llm_cli/clients/gemini.py
```python
class GeminiClient:  # Client for interacting with Google's Gemini API.
    def __init__(self, initial_model_alias)  # Initializes the Gemini client.
    def _load_model_aliases(self)  # Loads model aliases from the configuration.
    def _process_single_source(self, source)  # Override to handle Gemini-specific File API uploads for media.
    def _send(self, data)  # Sends the conversation history and new data to Gemini.
    def _to_provider_request_format(self, new_parts)  # Converts history and new parts to Gemini API format.
    def _parse_response(self, response_json)  # Parses Gemini response into internal Message format.
    def _upload_file(self, path, mime_type)  # Handles resumable upload to Gemini File API.
    def _wait_for_file_active(self, file_name)  # Polls the file status until it is ACTIVE.
```

### llm_cli/clients/grok.py
```python
class GrokClient:  # Client for interacting with the xAI Grok API.
    def __init__(self, initial_model_alias)  # Initializes the Grok client.
    def _load_model_aliases(self)  # Loads model aliases from the configuration.
    def _send(self, data)  # Sends the conversation history and new data to Grok.
    def _update_history(self, data, model_msg)  # Updates internal history.
    def _build_messages(self, data)  # Converts internal history to Grok (OpenAI-compatible) format.
```

### llm_cli/clients/mcp_manager.py
```python
class MCPManager:  # Manages connections to multiple MCP servers.
    def __init__(self)
    def _run_async(self, coro)  # Helper to run async coroutines in the manager's event loop.
    def list_tools(self)  # Get the list of available tools from all MCP servers.
    def initialize_servers(self)  # Connect to all configured MCP servers and retrieve their tools.
    async def _connect_and_list_tools(self, server_name, params)
    def call_tool(self, server_name, tool_name, arguments)  # Call a tool on a specific MCP server.
    def shutdown(self)  # Close all connections.
```

### llm_cli/clients/ollama.py
```python
class OllamaClient:  # Client for interacting with the Ollama API.
    def __init__(self, initial_model_alias)  # Initializes the Ollama client.
    def _load_model_aliases(self)  # Loads model aliases from the configuration.
    def _send(self, data)  # Sends the conversation history and new data to Ollama.
    def _build_messages(self, data)  # Converts history and new data to Ollama API format.
    def _parse_response(self, res_json)  # Parses Ollama API response.
    def _build_model_parts(self, content, tool_calls, reasoning)  # Builds internal ContentPart list.
```

### llm_cli/clients/openai.py
```python
class OpenAIClient:  # Client for interacting with OpenAI's Chat Completions API and Images API.
    def __init__(self, initial_model_alias)  # Initializes the OpenAI client.
    def _load_model_aliases(self)  # Loads model aliases from the configuration.
    def _is_image_model(self)  # Determines if the current model is an image generation model.
    def _send(self, data)  # Sends the conversation history and new data to OpenAI.
    def _send_image_generation(self, data)  # Handles image generation via OpenAI's DALL-E API.
    def _update_history(self, data, model_msg)  # Updates the internal conversation history with new messages.
    def _build_messages(self, data)  # Converts the internal conversation history to OpenAI API format.
```

### llm_cli/clients/session.py
```python
class LlmCliCompleter:  # Provides completion for slash commands and their arguments.
    def __init__(self, client)
    def get_completions(self, document, complete_event)
def _(event)
def _(event)
def _(event)
def _(event)  # Open the current buffer in an external editor safely.
class ChatSession:  # Manages the interactive CLI session and the ReAct loop.
    def __init__(self, client)
    def run(self, initial_data, sources)
    def process_and_print(self, data)
    def _handle_checkpoint(self)
    def _log_chat(self, content, role)
    def _get_input(self, message, exit_on_escape)  # Helper for console input, supporting both TTY and prompt_toolkit.
    def _confirm(self, message)
    def _execute_tool_call(self, part)
    def _preview_diff(self, args)
    def _preview_edit_diff(self, args)  # Generate a unified diff preview for edit_file (search/replace).
    def _preview_command(self, args)
```

### tests/__init__.py
```python
# Test suite for llm-cli.
```

### tests/conftest.py
```python
# Shared test fixtures and configuration for pytest.
def mock_api_key()  # Provide a mock API key for testing.
def sample_text_content()  # Provide sample text content for testing.
def sample_pdf_content()  # Provide a simple PDF binary content for testing.
def sample_pdf_base64(sample_pdf_content)  # Provide base64-encoded PDF content.
def sample_image_base64()  # Provide a minimal base64-encoded image (1x1 PNG).
def temp_pdf_file(tmp_path, sample_pdf_content)  # Create a temporary PDF file for testing.
def temp_text_file(tmp_path, sample_text_content)  # Create a temporary text file for testing.
def temp_empty_file(tmp_path)  # Create a temporary empty file for testing.
def mock_config(monkeypatch, mock_api_key)  # Mock the config module to return test values.
def mock_requests_success(monkeypatch)  # Mock successful HTTP requests.
def mock_cloudscraper(monkeypatch, mock_requests_success)  # Mock cloudscraper to return successful responses.
```

### tests/test_agent_tools.py
```python
# Tests for system tools like execute_command.
def test_basic_execution()  # Verify that a normal command executes and returns output.
def test_interactive_command_no_hang()  # Verify that commands waiting for input (like cat) exit without hanging.
def test_stderr_capture()  # Verify that standard error is correctly captured.
def test_timeout_and_cleanup()  # Verify that processes are terminated on timeout and partial output is captured.
```

### tests/test_attachment.py
```python
class MockClient:
    def _load_model_aliases(self)
    def _send(self, data)
def test_attach_file_tool_success(mock_path, mock_process)
def test_attach_file_tool_not_found(mock_path)
def test_attach_file_tool_text_file(mock_path, mock_process)
def test_handle_attach_command()
def test_handle_attach_command_invalid()
```

### tests/test_audio_support.py
```python
def mock_config_audio(mock_config)
def test_gemini_audio_upload_called(mock_config_audio, tmp_path)
def test_gemini_send_with_audio_file_uri(mock_config_audio)
def test_base_client_audio_as_base64(mock_config_audio, tmp_path)
```

### tests/test_base_client.py
```python
# Tests for BaseLlmClient base class functionality.
class TestBaseLlmClient:  # Test suite for BaseLlmClient base class.
    def concrete_client(self, mock_config)  # Create a concrete implementation of BaseLlmClient for testing.
    def test_initialization(self, concrete_client)  # Test that client initializes correctly.
    def test_set_model_success(self, concrete_client)  # Test switching to an available model.
    def test_set_model_failure(self, concrete_client)  # Test switching to a non-existent model.
    def test_process_file_text(self, concrete_client, temp_text_file, sample_text_content)  # Test processing a text file via media_utils.
    def test_process_file_empty(self, concrete_client, temp_empty_file)  # Test that empty files are handled by media_utils.
    def test_process_sources_text_input(self, concrete_client)  # Test processing plain text sources.
    def test_process_single_source_media(self, concrete_client, temp_text_file)  # Test that media files are marked with is_file_or_url.
    def test_save_inline_image(self, concrete_client, tmp_path, sample_image_base64)  # Test saving received image data to a file.
    def test_talk_delegates_to_session(self, concrete_client)  # Test that talk() instantiates ChatSession and calls run().
    def test_system_prompt_construction(self, monkeypatch)  # Test that system prompt includes date/time and base prompt.
    def test_load_session_success(self, concrete_client, tmp_path)  # Test loading a session from a valid JSON file.
    def test_load_session_file_not_found(self, concrete_client)  # Test loading a session from a non-existent file.
    def test_load_session_invalid_json(self, concrete_client, tmp_path)  # Test loading a session from an invalid JSON file.
```

### tests/test_cli_args.py
```python
# Tests for CLI argument parsing.
class MockClient:
    def _load_model_aliases(self)
    def _send(self, data)
def parser()
def test_session_argument(parser)  # Test that the --session argument is accepted.
def test_removed_tools_argument(parser)  # Test that the -t/--tools argument is removed and raises an error.
def test_removed_no_system_prompt_argument(parser)  # Test that the --no-system-prompt argument is removed and raises an error.
def test_removed_debug_argument(parser)  # Test that the -d/--debug argument is removed and raises an error.
```

### tests/test_command_validator.py
```python
class TestCommandValidator:
    def test_allowed_commands(self)
    def test_disallowed_sed_and_patch(self)  # Test that sed and patch are now disallowed.
    def test_git_strict_restrictions(self)  # Test that dangerous git subcommands are strictly blocked.
    def test_path_traversal_blocking(self)  # Test that any command with .. is blocked.
    def test_mcp_mode(self)  # Verify MCP mode still works with its own whitelist.
    def test_validate_mcp_command_function(self)  # Test the convenience function for MCP, now allowing -m for python.
```

### tests/test_configure_utils.py
```python
def test_mask_secrets_api_key()
def test_mask_secrets_github_pat_in_string()
def test_mask_secrets_recursive()
```

### tests/test_conversation_history.py
```python
# Test conversation history handling with initial_data and new dataclasses.
def test_initial_data_not_duplicated_in_conversation(mock_config)  # Test that initial_data (file_uri) is handled correctly in conversation using dataclasses.
def test_conversation_cleared_after_clear_command(mock_config)  # Test that /clear command clears conversation history.
```

### tests/test_custom_model.py
```python
class MockClient:
    def _load_model_aliases(self)
    def _send(self, data)
def test_base_client_custom_model()
def test_unified_client_custom_model()
```

### tests/test_file_ops.py
```python
def test_write_and_read_file(tmp_path, monkeypatch)  # Test writing a file and then reading it back.
def test_read_file_line_range(tmp_path, monkeypatch)  # Test reading a specific line range from a file.
def test_list_files_recursive(tmp_path, monkeypatch)  # Test listing files with depth and directory structure.
def test_file_ops_security_block(tmp_path, monkeypatch)  # Test that file operations block paths outside the sandbox.
def test_list_files_max_files(tmp_path, monkeypatch)  # Test list_files respects max_files limit.
```

### tests/test_file_ops_edit.py
```python
def test_dir()
def test_edit_file_success(test_dir)
def test_edit_file_not_found(test_dir)
def test_edit_file_multiple_occurrences(test_dir)
```

### tests/test_gemini_features.py
```python
def mock_gemini_response_image()
def test_gemini_saves_image_and_displays_thought(mock_config, mock_gemini_response_image, tmp_path)
```

### tests/test_gemini_file_uri.py
```python
def test_process_single_source_detects_gemini_uri()
def test_process_single_source_with_gemini_uri_fetches_url()
```

### tests/test_grep_validation.py
```python
def test_grep_with_slash_pattern()
def test_grep_with_existing_system_file()
def test_ls_non_existent_path()
```

### tests/test_log_trimming.py
```python
def test_trim_log_file(tmp_path, mock_config)  # Test that log files are trimmed to max_lines.
def test_trim_log_file_no_trim_needed(tmp_path, mock_config)  # Test that log files are not trimmed if under max_lines.
def test_trim_log_file_nonexistent(tmp_path, mock_config)  # Test that trimming a nonexistent file doesn't raise an error.
```

### tests/test_path_validator.py
```python
class TestPathValidator:
    def test_sandbox_within_cwd(self)  # Should allow paths within current directory.
    def test_blocks_traversal(self)  # Should block any use of ..
    def test_blocks_absolute_system_paths(self)  # Should block absolute paths to system directories.
    def test_file_ops_integrity(self, tmp_path, monkeypatch)  # Test that file_ops tools actually respect the validator.
```

### tests/test_pdf_processing.py
```python
# Tests for PDF processing functionality across providers using dataclasses.
class TestPDFProcessing:  # Test suite for PDF processing in different providers.
    def test_gemini_pdf_as_base64(self, mock_config, temp_pdf_file)  # Test that Gemini processes PDFs as base64.
    def test_openai_pdf_as_base64(self, mock_config, temp_pdf_file)  # Placeholder for OpenAI PDF support test.
    def test_claude_pdf_as_base64(self, mock_config, temp_pdf_file)  # Test that Claude processes PDFs as base64.
    def test_grok_pdf_as_text(self, mock_config, temp_pdf_file)  # Test that Grok processes PDFs as text extraction.
    def test_gemini_build_message_with_pdf(self, mock_config, sample_pdf_base64)  # Test Gemini message building with PDF.
    def test_pdf_url_fetching_gemini(self, mock_config, mock_cloudscraper, sample_pdf_content)  # Test PDF URL fetching for Gemini (base64).
```

### tests/test_providers.py
```python
# Tests for provider-specific client implementations.
class TestProviderClients:  # Test suite for provider-specific clients.
    def test_client_initialization(self, mock_config, client_class, config_section, expected_base64)  # Test that all clients initialize correctly.
    def test_initial_tool_activation(self, mock_config)  # Test that tools can be activated at initialization.
    def test_gemini_model_switching(self, mock_config)  # Test model switching in Gemini client.
class TestUnifiedClient:  # Test suite for UnifiedClient.
    def test_unified_client_initialization(self, mock_config)  # Test UnifiedClient initialization.
    def test_provider_switching(self, mock_config)  # Test switching between providers.
    def test_unified_pdf_delegation_to_gemini(self, mock_config, temp_pdf_file)  # Test that UnifiedClient delegates PDF processing to Gemini.
    def test_unified_model_aliases(self, mock_config)  # Test that UnifiedClient loads model aliases correctly.
    def test_invalid_provider(self, mock_config)  # Test handling of invalid provider.
class TestSystemPrompt:  # Test suite for system prompt functionality.
    def test_system_prompt_enabled_by_default(self, mock_config, client_class, config_section)  # Test that system prompt is enabled by default when configured.
    def test_system_prompt_disabled_with_flag(self, mock_config, client_class, config_section)  # Test that system prompt can be disabled with flag.
```

### tests/test_unified_provider_switching.py
```python
def test_unified_client_switches_provider_via_alias(mock_config)
```

### tests/test_unified_video.py
```python
def test_unified_client_handles_video_via_gemini(mock_config, tmp_path)
```

### tests/test_web_tools.py
```python
def test_fetch_url_html(mock_cloudscraper)  # Test fetch_url returns raw HTML.
def test_fetch_url_binary(mock_cloudscraper)  # Test fetch_url handles binary content like PDF.
def test_fetch_web_text_basic(mock_cloudscraper)  # Test fetch_web_text extracts text and removes tags.
def test_fetch_web_text_truncation(mock_cloudscraper)  # Test fetch_web_text truncates output at 20000 chars.
def test_fetch_web_text_error(mock_cloudscraper)  # Test error handling in fetch_web_text.
def test_google_search_success(mock_config)  # Test google_search success scenario.
def test_google_search_multiple_queries(mock_config)  # Test google_search with multiple queries.
def test_google_search_no_results(mock_config)  # Test google_search when no items are returned.
def test_google_search_auth_error(monkeypatch)  # Test google_search when credentials are missing.
```
