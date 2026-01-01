# llm-cli: A Unified Command-Line Interface for Multiple LLMs

`llm-cli` is a powerful and versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), and xAI (Grok), allowing you to seamlessly switch between providers and leverage their unique capabilities right from your terminal using a single command: `llm`.

![llm-cli banner](images/banner.png)

## Screenshots

### 📄 PDF Analysis (Multimodal)

Demonstrating how the system loads the "Attention is All You Need" paper PDF and explains its key points.

![PDF Analysis](images/chat.png)

### 🤖 Agent Mode & Tool Use

The AI can use tools like `google_search` to find real-time information or `execute_command` to run various commands. **Agent Mode is enabled by default**, allowing the AI to autonomously help with your tasks.

![AI agent supports your coding](images/agent.png)

## Features

-   **Unified Interface**: Access Gemini, OpenAI, Claude, and Grok through a single `llm` command.
-   **Interactive Chat Mode**: A REPL-style interface with rich syntax highlighting and Markdown rendering.
-   **Agent Mode (Always On)**: Autonomous task execution. The AI can read/write files, execute shell commands, and **search the web**.
-   **Distributed Agent via MCP**: Support for **Model Context Protocol (MCP)**. You can connect to remote `llm-cli` instances via SSH and let the LLM manage files or run tests on a remote server as if they were local tools.
-   **User-Driven Context Management (Checkpointing)**: Manually trigger `/checkpoint` to summarize the conversation and clear history. This keeps the context window efficient while maintaining vital progress info.
-   **Safe Execution**: Includes a **Diff Preview** for file changes (via `write_file`) and asks for user confirmation before executing any tool or shell command (Human-in-the-Loop).
-   **One-Shot Execution**: Pipe input from other commands or pass prompts as arguments.
-   **Multimodal Input**:
    -   **Gemini**: Text, local images, PDFs, **Audio**, and **Video**. (Automatically uses Gemini File API for large files and media).
    -   **OpenAI / Claude / Grok**: Text and local images.
-   **URL Support**: Directly pass website URLs to analyze their content. (Includes automatic web scraping and multimodal injection for PDFs/Images).
-   **Shell Integration**: Execute shell commands with `!command` and optionally feed the output back to the LLM.
-   **Smart Log Management**: Automatically rotates and trims chat logs and command history to save space.
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

Settings are saved to `~/.config/llm_cli/config.toml`.

## Usage

### 1. Interactive Chat

Simply type `llm` to start an interactive session:

```bash
llm
```

### 2. One-Shot Prompts and Piping

You can pass a prompt directly or pipe content from other commands:

```bash
# Direct prompt
llm "What is the capital of France?"

# Analyze code from a pipe
cat main.py | llm "Explain this code"

# Analyze a local file or URL
llm "Summarize this paper" https://arxiv.org/pdf/1706.03762.pdf
```

## Command-Line Options

You can customize the behavior of the `llm` command using the following options:

-   `-p, --provider <provider>`: Specify the provider to use (`google`, `openai`, `anthropic`, `xai`).
-   `-m, --model <alias>`: Specify the model alias (e.g., `pro`, `flash`, `gpt4o`, `opus`).
-   `-t, --tools <tool_name>`: Enable specific tools (can be used multiple times).
-   `-s, --stdout`: Print the response directly to stdout and exit (non-interactive mode).
-   `--raw`: Disable Markdown rendering in the terminal.
-   `-d, --debug`: Enable live debug mode to see raw API requests and responses.
-   `--mcp`: Enable Model Context Protocol (MCP) integration.
-   `--mcp-server`: Run `llm-cli` as an MCP server.
-   `--no-system-prompt`: Disable the configured system prompt for the session.

## In-Chat Commands

While in the interactive chat, you can use the following slash commands:

-   `/<provider>`: Switch provider instantly (`/google`, `/openai`, `/anthropic`, `/xai`).
-   `/<alias>`: Switch model within the current provider (e.g., `/pro`, `/gpt4o`, `/opus`).
-   `/models` (or `/m`): List available models and their aliases.
-   `/info` (or `/i`): Show current session info (provider, model, tools, etc.).
-   `/tools`: Show currently active tools (including remote MCP tools).
-   `/checkpoint` (or `/cp`): Summarize progress and clear conversation history to save tokens.
-   `/dump`: Dump conversation history as a JSON object.
-   `/raw`: Show the raw conversation text (useful for copy-pasting).
-   `/clear` (or `/c`): Clear conversation history (without summary).
-   `/debug` (or `/d`): Toggle live debug mode.
-   `!command`: Execute a local shell command.
-   `/help` (or `/h`): Show full command list.
-   `/quit` (or `/q`): Exit.

## Model Context Protocol (MCP) Support

`llm-cli` can act as both an MCP client and an MCP server. This allows for powerful remote development workflows.

### 1. Remote Development via SSH
You can let your local LLM session control a remote server. Add the following to your `~/.config/llm_cli/config.toml`:

```toml
[[mcp_servers]]
name = "my_remote_box"
command = "ssh"
args = ["user@remote-host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

When you start `llm --mcp`, it will automatically connect via SSH, and you'll see tools like `my_remote_box__execute_command` and `my_remote_box__read_file` available in the chat.

### 2. Running as an MCP Server
To expose your local tools to another MCP client:

```bash
llm --mcp-server
```

## Utility Scripts

The package includes several helper scripts:

-   `llm-cli-config`: Interactive configuration tool.
-   `gemini-models`, `openai-models`, `claude-models`, `grok-models`: List available models for each provider directly from their APIs.
-   `translate-json`: A utility to translate specific keys in a JSON file using LLMs.
    ```bash
    translate-json input.json output.json -k "messages.text" -p google
    ```

## License

This project is licensed under the [Apache License 2.0](LICENSE).

--------

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで全プロバイダ（Gemini, OpenAI, Claude, Grok）を切り替え可能。
-   **エージェントモード（常時有効）**: AIが自律的にファイル操作、コマンド実行、**Web検索**を行います。
-   **MCPによる分散エージェント**: **Model Context Protocol (MCP)** をサポート。SSH経由でリモートサーバー上の `llm-cli` に接続し、遠隔地のファイルを操作したりテストを実行したりといった操作を、ローカルのツールと同じ感覚でAIに行わせることができます。
-   **ユーザー主導の履歴管理（チェックポイント機能）**: `/checkpoint` コマンドで会話の要約を作成し、履歴をリセット。トークン消費を抑えつつ重要な進捗を維持します。
-   **安全な実行**: 全てのツール実行前にユーザーの確認を求める Human-in-the-Loop 方式。ファイル書き換え時には差分（Diff）を表示します。
-   **マルチモーダル対応**:
    -   **Gemini**: テキスト、画像、PDFに加え、**音声**および**動画**に対応（Gemini File APIを自動利用）。
    -   **OpenAI / Claude / Grok**: テキストおよびローカル画像に対応。
-   **URL直接指定**: ウェブサイトのURLを渡すことで、内容を自動的にスクレイピングして解析可能。

## インストールと設定

```bash
pip install .
pip install ".[mcp]" # MCP機能を使用する場合
llm-cli-config       # 初回設定（APIキー入力）
```

## 使い方

### コマンドラインオプション

`llm` コマンドでは以下のオプションが利用可能です：

-   `-p, --provider <provider>`: プロバイダを指定 (`google`, `openai`, `anthropic`, `xai`)。
-   `-m, --model <alias>`: モデルのエイリアスを指定 (例: `pro`, `flash`, `gpt4o`, `opus`)。
-   `-t, --tools <tool_name>`: 特定のツールを有効化（複数指定可）。
-   `-s, --stdout`: 結果を標準出力に表示して終了（非対話モード）。
-   `--raw`: Markdownレンダリングを無効化。
-   `-d, --debug`: デバッグモード（APIリクエスト/レスポンスを表示）。
-   `--mcp`: MCP (Model Context Protocol) 連携を有効化。
-   `--mcp-server`: MCPサーバーとして起動。
-   `--no-system-prompt`: 設定されたシステムプロンプトを無効化。

### 対話モード
```bash
llm
```

**主なチャット内コマンド:**
-   `/<provider>`: プロバイダの切り替え (`/google`, `/openai`, `/claude`, `/grok`)
-   `/checkpoint` (or `/cp`): これまでの会話を要約し、履歴をクリアします。
-   `/info` (or `/i`): 現在のセッション状態や、接続されているリモートツールを確認できます。
-   `/models` (or `/m`): 利用可能なモデルとエイリアスの一覧を表示します。
-   `/debug` (or `/d`): APIのリクエスト/レスポンスをリアルタイムで表示します。
-   `/raw`: 会話履歴をプレーンテキストで表示します（コピペ用）。
-   `/help` (or `/h`): 全コマンドを表示します。

### ワンショット実行
```bash
cat code.py | llm "このコードをレビューして"
```

## MCP (Model Context Protocol) 対応

### SSH経由のリモート開発
ローカルのチャットセッションからリモートサーバーを操作させるには、`~/.config/llm_cli/config.toml` に以下を追加します：

```toml
[[mcp_servers]]
name = "remote_server"
command = "ssh"
args = ["user@remote-host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

起動時に `--mcp` オプションを付けることで、`remote_server__execute_command` などのツールが自動的にチャット内で利用可能になります。

## ユーティリティ

-   `translate-json`: LLMを使用してJSONファイル内の特定のキーを翻訳します。
-   `*-models`: 各プロバイダが提供しているモデル一覧を取得します。
