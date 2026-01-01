# llm-cli: A Unified Command-Line Interface for Multiple LLMs

`llm-cli` is a powerful and versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), and xAI (Grok), allowing you to seamlessly switch between providers and leverage their unique capabilities right from your terminal using a single command: `llm`.

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
```

## MCP (Model Context Protocol) Support

`llm-cli` can act as both an MCP client and an MCP server. This allows for powerful remote development workflows.

### 1. Remote Development via SSH
You can let your local LLM session control a remote server. Add the following to your `~/.config/llm_cli/config.toml`:

```toml
[[mcp_servers]]
name = "my_remote_box"
command = "ssh"
args = ["user@remote-host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

When you start `llm`, it will automatically connect via SSH, and you'll see tools like `my_remote_box__execute_command` and `my_remote_box__read_file` available in the chat.

### 2. Running as an MCP Server
To expose your local tools to another MCP client:

```bash
llm --mcp-server
```

## Configuration

Before using the tools, run the interactive setup script:

```bash
llm-cli-config
```

Settings are saved to `~/.config/llm_cli/config.toml`.

## Usage

### 1. Interactive Chat

```bash
llm
```

**Common In-Chat Commands:**
-   `/<provider>`: Switch provider instantly.
-   `/<alias>`: Switch model within the current provider (e.g., `/pro`, `/gpt4`, `/opus`).
-   `/info` (or `/i`): Show session info.
-   `/tools`: Show currently active tools (including remote MCP tools).
-   `/checkpoint` (or `/cp`): Summarize progress and clear conversation history.
-   `/clear` (or `/c`): Clear conversation history (without summary).
-   `!command`: Execute a local shell command.
-   `/help` (or `/h`): Show full command list.
-   `/quit` (or `/q`): Exit.

### 2. One-Shot Prompts

```bash
# Analyze code from a pipe
cat main.py | llm "Explain this code"
```

## License

This project is licensed under the [Apache License 2.0](LICENSE).

--------

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで全プロバイダを切り替え可能。
-   **エージェントモード（常時有効）**: AIが自律的にファイル操作、コマンド実行、**Web検索**を行います。
-   **MCPによる分散エージェント**: **Model Context Protocol (MCP)** をサポート。SSH経由でリモートサーバー上の `llm-cli` に接続し、遠隔地のファイルを操作したりテストを実行したりといった操作を、ローカルのツールと同じ感覚でAIに行わせることができます。
-   **ユーザー主導の履歴管理（チェックポイント機能）**: `/checkpoint` コマンドで会話の要約を作成し、履歴をリセット。トークン消費を抑えつつ重要な進捗を維持します。
-   **安全な実行**: 全てのツール実行前にユーザーの確認を求める Human-in-the-Loop 方式。
-   **マルチモーダル対応**: Gemini (動画/音声対応), OpenAI, Claude, Grok。

## MCP (Model Context Protocol) 対応

`llm-cli` は、自分自身を MCP サーバーとして動かすことも、外部の MCP サーバーに接続するクライアントとして動かすことも可能です。

### 1. SSH経由のリモート開発
ローカルのチャットセッションからリモートサーバーを操作させるには、`~/.config/llm_cli/config.toml` に以下を追加します：

```toml
[[mcp_servers]]
name = "remote_server"
command = "ssh"
args = ["user@remote-host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

これにより、`remote_server__execute_command` などのツールが自動的にチャット内で利用可能になります。

### 2. MCPサーバーとして起動
ローカルのツールを他のクライアント（別のターミナルの `llm-cli` など）に公開する場合：

```bash
llm --mcp-server
```

## インストールと設定

```bash
pip install .
llm-cli-config
```

## 使い方

### 対話モード
```bash
llm
```

**主なコマンド:**
-   `/checkpoint` (or `/cp`): これまでの会話を要約し、履歴をクリアします。
-   `/info` (or `/i`): 現在のセッション状態や、接続されているリモートツールを確認できます。
-   `/help` (or `/h`): 全コマンドを表示します。
