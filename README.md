# llm-cli: A Unified Command-Line Interface for Multiple LLMs

`llm-cli` is a powerful and versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), and xAI (Grok), allowing you to seamlessly switch between providers and leverage their unique capabilities right from your terminal using a single command: `llm`.

![llm-cli banner](images/banner.jpeg)

## Screenshots

### 📄 PDF Analysis (Multimodal)

Demonstrating how the system loads the "Attention is All You Need" paper PDF and explains its key points.

![PDF Analysis](images/chat.png)

### 🤖 Agent Mode & Tool Use

The AI can use tools like `google_search` or `search_arxiv` to find real-time information or `execute_command` to run various commands. **Agent Mode is enabled by default**, allowing the AI to autonomously help with your tasks.

![AI agent supports your coding](images/agent.png)

## Features

-   **Unified Interface**: Access Gemini, OpenAI, Claude, and Grok through a single `llm` command.
-   **Interactive Chat Mode**: A REPL-style interface with rich syntax highlighting and Markdown rendering.
-   **Agent Mode (Always On)**: Autonomous task execution. The AI can read/write files, execute shell commands, search the web, and **dynamically attach media files**.
-   **Academic Research Support**: Built-in `search_arxiv` tool to search for papers, read abstracts, and automatically fetch PDFs for analysis.
-   **Plugin-based Tool Architecture**: Easily extend the agent's capabilities by adding new tool modules.
-   **Distributed Agent via MCP**: Support for **Model Context Protocol (MCP)**. You can connect to remote `llm-cli` instances via SSH and let the LLM manage files or run tests on a remote server as if they were local tools.
-   **User-Driven Context Management (Checkpointing)**: Manually trigger `/checkpoint` to summarize the conversation and clear history.
-   **Multimodal Input & Support**:
    -   **Manual Attachment**: Use the `/attach <path>` command mid-session to inject images, PDFs, videos, or audio.
    -   **Autonomous Attachment**: Agents can use the `attach_file` or `fetch_url` tools to bring media files into the context when needed.
    -   **Gemini**: Text, local images, PDFs, **Audio**, and **Video**.
    -   **OpenAI / Claude / Grok**: Text and local images (PDFs are processed as text/Base64).
-   **URL Support**: Directly pass website URLs to analyze their content. (Includes automatic web scraping and multimodal injection for PDFs/Images).
-   **Safe Execution**: Includes a **Diff Preview** for file changes and asks for user confirmation before executing any tool (Human-in-the-Loop).
-   **One-Shot Execution**: Pipe input from other commands or pass prompts as arguments.
-   **Smart Log Management**: Automatically rotates and trims chat logs.
-   **Simple Configuration**: Interactive setup via `llm-cli-config`.

## Installation

Ensure you have Python 3.11 or newer.

```bash
# Clone the repository
git clone https://github.com/yosh95/llm-cli.git

# Navigate to the directory
cd llm-cli

# Install the package
pip install .

# Optional: Install MCP support
pip install ".[mcp]"
```

## Quick Start

Before using the tool, run the interactive setup script to configure your API keys:

```bash
llm-cli-config
```

## Usage

### 1. Research Automation (Example)
Search for papers, find the best one, and summarize its contributions in one command:
```bash
llm "Search arXiv for 'Direct Preference Optimization', pick the most relevant paper, and summarize its key contributions."
```

### 2. Interactive Chat
Simply type `llm` to start an interactive session:
```bash
llm
```

### 3. One-Shot Prompts and Piping
```bash
# Direct prompt
llm "What is the capital of France?"

# Analyze code from a pipe
cat main.py | llm "Explain this code"

# Analyze a local file or URL
llm "Summarize this paper" https://arxiv.org/pdf/1706.03762.pdf
```

## Command-Line Options

-   `-p, --provider <provider>`: Specify the provider (`google`, `openai`, `anthropic`, `xai`).
-   `-m, --model <alias>`: Specify the model alias (e.g., `pro`, `flash`, `gpt4o`, `opus`).
-   `-t, --tools <tool_name>`: Enable specific tools.
-   `-s, --stdout`: Print the response directly to stdout and exit.
-   `--raw`: Disable Markdown rendering in the terminal.
-   `-d, --debug`: Enable live debug mode.
-   `--mcp`: Enable Model Context Protocol (MCP) integration.
-   `--mcp-server`: Run `llm-cli` as an MCP server.
-   `--no-system-prompt`: Disable the configured system prompt.

## In-Chat Commands

-   `/<provider>`: Switch provider instantly (`/google`, `/openai`, `/anthropic`, `/xai`).
-   `/<alias>`: Switch model within the current provider (e.g., `/pro`, `/gpt4o`, `/opus`).
-   `/models` (or `/m`): List available models and their aliases.
-   `/info` (or `/i`): Show current session info (provider, model, tools, etc.).
-   `/tools`: Show currently active tools (including remote MCP tools).
-   `/checkpoint` (or `/cp`): Summarize progress and clear conversation history.
-   `/attach <path>`: Manually attach a file (Image, PDF, Audio, Video).
-   `/dump`: Dump conversation history as a JSON object.
-   `/raw`: Show the raw conversation text.
-   `/clear` (or `/c`): Clear conversation history.
-   `/debug` (or `/d`): Toggle live debug mode.
-   `!command`: Execute a local shell command.
-   `/help` (or `/h`): Show full command list.
-   `/quit` (or `/q`): Exit.

## Plugin Architecture: Adding New Tools

`llm-cli` uses a decorator-based plugin system. To add a new tool:

1. Create a new `.py` file in `llm_cli/modules/tools/`.
2. Define your function and decorate it with `@tool`.

Example (`llm_cli/modules/tools/weather.py`):
```python
from llm_cli.modules.tool_registry import tool

@tool(
    name="get_weather",
    description="Get current weather for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "The city name."}
        },
        "required": ["city"]
    }
)
def get_weather(city: str) -> dict:
    return {"weather": "sunny", "temperature": "25C"}
```

## Model Context Protocol (MCP) Support

`llm-cli` can act as both an MCP client and an MCP server.

### 1. Remote Development via SSH
Add the following to your `~/.config/llm_cli/config.toml`:

```toml
[[mcp_servers]]
name = "my_remote_box"
command = "ssh"
args = ["user@remote-host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

### 2. Running as an MCP Server
```bash
llm --mcp-server
```

## Utility Scripts

-   `llm-cli-config`: Interactive configuration tool.
-   `*-models`: List available models for each provider.
-   `translate-json`: A utility to translate specific keys in a JSON file.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

--------

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで全プロバイダを切り替え可能。
-   **エージェントモード（常時有効）**: AIが自律的にファイル操作、コマンド実行、Web検索、**論文検索**を行います。
-   **先行研究調査の自動化**: `search_arxiv` ツールを搭載。特定のトピックに関する最新論文の検索から、アブストラクトの確認、PDFの自動取得と解析までをシームレスに行えます。
-   **プラグインベースのツール設計**: デコレータを使用したプラグインシステムにより、新しいツールの追加が容易です。
-   **MCPによる分散エージェント**: **Model Context Protocol (MCP)** をサポート。
-   **ユーザー主導の履歴管理（チェックポイント機能）**: `/checkpoint` コマンドで会話の要約を作成し、履歴をリセット。
-   **安全な実行**: 全てのツール実行前にユーザーの確認を求める Human-in-the-Loop 方式。
-   **マルチモーダル対応**:
    -   **手動添付**: `/attach <path>` コマンドで画像、PDF、音声、動画を追加。
    -   **自律添付**: エージェントが必要に応じてツールを使い、メディアファイルを読み込みます。
-   **URL直接指定**: ウェブサイトのURLを渡すことで、内容を自動的に解析可能。

## 活用例：研究調査の自動化

arXivから特定のトピックに関する論文を探し、内容を分析させることができます。

```bash
llm "arXivで 'Test-time Scaling Laws' に関する論文を探して、主要な貢献を日本語でまとめて"
```

## インストールと設定

```bash
pip install .
llm-cli-config
```

## ライセンス

[Apache License 2.0](LICENSE)
