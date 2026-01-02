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
-   **OpenAI-Compatible Custom Endpoints**: Use local LLMs (via Ollama, vLLM, etc.) or other OpenAI-compatible services by specifying a custom `api_url` in the configuration.
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

`llm-cli` は、多様な大規模言語モデル（LLM）と対話するための、強力で汎用性の高いコマンドラインツールです。Google (Gemini)、OpenAI、Anthropic (Claude)、xAI (Grok) をサポートしており、単一の `llm` コマンドだけでプロバイダをシームレスに切り替えながら、各モデルの機能をターミナルから直接活用できます。

## スクリーンショット

### 📄 PDF解析（マルチモーダル）
"Attention is All You Need" 論文のPDFを読み込み、その要点を解説するデモ。
![PDF Analysis](images/chat.png)

### 🤖 エージェントモード & ツール利用
AIは `google_search` や `search_arxiv` を使ってリアルタイム情報を検索したり、`execute_command` で任意のコマンドを実行したりできます。**エージェントモードはデフォルトで有効**になっており、AIが自律的にタスクをサポートします。
![AI agent supports your coding](images/agent.png)

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで Gemini, OpenAI, Claude, Grok にアクセス可能。
-   **対話型チャットモード**: シンタックスハイライトとMarkdownレンダリングに対応したREPL形式のインターフェース。
-   **エージェントモード（常時有効）**: 自律的なタスク実行。ファイルの読み書き、シェルコマンド実行、Web検索、**メディアファイルの動的添付**が可能です。
-   **先行研究調査の自動化**: `search_arxiv` ツールを搭載。特定のトピックに関する最新論文の検索から、アブストラクトの確認、PDFの自動取得と解析までをシームレスに行えます。
-   **プラグインベースのツール設計**: デコレータを使用したプラグインシステムにより、新しいツールの追加が容易です。
-   **MCPによる分散エージェント**: **Model Context Protocol (MCP)** をサポート。SSH経由でリモートの `llm-cli` インスタンスに接続し、リモートサーバー上のファイル操作やテスト実行をローカルツールのように行えます。
-   **OpenAI互換カスタムエンドポイント**: `api_url` を設定することで、ローカルLLM（Ollama, vLLM 等）やその他のOpenAI互換サービスを利用可能。
-   **ユーザー主導の履歴管理（チェックポイント機能）**: `/checkpoint` コマンドで会話の要約を作成し、履歴をリセットしてコンテキストを整理。
-   **マルチモーダル対応**:
    -   **手動添付**: `/attach <path>` コマンドで画像、PDF、音声、動画を会話の途中から注入。
    -   **自律添付**: エージェントが必要に応じてツールを使い、メディアファイルをコンテキストに読み込みます。
    -   **Gemini**: テキスト、ローカル画像、PDF、**音声**、**動画**をサポート。
    -   **OpenAI / Claude / Grok**: テキスト、ローカル画像をサポート（PDFはテキストまたはBase64として処理）。
-   **URL直接指定**: ウェブサイトのURLを渡すことで、内容を自動的に解析可能（自動スクレイピング、PDF/画像のマルチモーダル注入を含む）。
-   **安全な実行**: ファイル変更時の **Diffプレビュー** 表示と、ツール実行前のユーザー確認（Human-in-the-Loop）。
-   **ワンショット実行**: 他のコマンドからのパイプ入力や、引数としてのプロンプト実行に対応。
-   **ログ管理**: チャットログの自動ローテーションとトリミング機能を搭載。
-   **簡単設定**: `llm-cli-config` による対話形式のセットアップ。

## インストール

Python 3.11 以上が必要です。

```bash
# リポジトリをクローン
git clone https://github.com/yosh95/llm-cli.git

# ディレクトリに移動
cd llm-cli

# パッケージをインストール
pip install .

# オプション: MCPサポートをインストール
pip install ".[mcp]"
```

## クイックスタート

最初に使用する前に、セットアップスクリプトを実行してAPIキーを設定してください：

```bash
llm-cli-config
```

## 使い方

### 1. 研究調査の自動化（例）
特定のトピックに関する論文を探し、最適なものを選んで日本語でまとめさせることができます。
```bash
llm "arXivで 'Direct Preference Optimization' に関する論文を探して、最も関連性の高いものを選び、その主要な貢献をまとめて。"
```

### 2. インタラクティブ・チャット
単に `llm` と打つだけでセッションが開始されます：
```bash
llm
```

### 3. ワンショットプロンプトとパイプ利用
```bash
# 直接プロンプトを実行
llm "フランスの首都は？"

# パイプからコードを解析
cat main.py | llm "このコードを解説して"

# ローカルファイルやURLを解析
llm "この論文を要約して" https://arxiv.org/pdf/1706.03762.pdf
```

## コマンドライン・オプション

-   `-p, --provider <provider>`: プロバイダを指定 (`google`, `openai`, `anthropic`, `xai`)。
-   `-m, --model <alias>`: モデルのエイリアスを指定 (例: `pro`, `flash`, `gpt4o`, `opus`)。
-   `-t, --tools <tool_name>`: 特定のツールを有効化。
-   `-s, --stdout`: 応答を直接標準出力に表示して終了。
-   `--raw`: Markdownレンダリングを無効化。
-   `-d, --debug`: ライブデバッグモードを有効化。
-   `--mcp`: MCP（Model Context Protocol）連携を有効化。
-   `--mcp-server`: `llm-cli` を MCP サーバーとして起動。
-   `--no-system-prompt`: 設定されたシステムプロンプトを無効化。

## チャット内コマンド

-   `/<provider>`: プロバイダを即座に切り替え (`/google`, `/openai`, `/anthropic`, `/xai`)。
-   `/<alias>`: 現在のプロバイダ内でモデルを切り替え (例: `/pro`, `/gpt4o`, `/opus`)。
-   `/models` (または `/m`): 利用可能なモデルとエイリアスを表示。
-   `/info` (または `/i`): 現在のセッション情報（プロバイダ、モデル、ツール等）を表示。
-   `/tools`: 現在有効なツールを表示（リモートのMCPツール含む）。
-   `/checkpoint` (または `/cp`): 進捗を要約し、会話履歴をクリア。
-   `/attach <path>`: ファイル（画像、PDF、音声、動画）を手動で添付。
-   `/dump`: 会話履歴をJSON形式でダンプ。
-   `/raw`: 生の会話テキストを表示。
-   `/clear` (または `/c`): 会話履歴をクリア。
-   `/debug` (または `/d`): ライブデバッグモードのON/OFF切り替え。
-   `!command`: ローカルのシェルコマンドを実行。
-   `/help` (または `/h`): 全コマンドリストを表示。
-   `/quit` (または `/q`): 終了。

## プラグイン・アーキテクチャ: ツールの追加

`llm-cli` はデコレータベースのプラグインシステムを採用しています。新しいツールを追加するには：

1. `llm_cli/modules/tools/` に新しい `.py` ファイルを作成。
2. 関数を定義し、`@tool` デコレータを付与。

例 (`llm_cli/modules/tools/weather.py`):
```python
from llm_cli.modules.tool_registry import tool

@tool(
    name="get_weather",
    description="指定した都市の現在の天気を取得します。",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "都市名。"}
        },
        "required": ["city"]
    }
)
def get_weather(city: str) -> dict:
    return {"weather": "sunny", "temperature": "25C"}
```

## MCP (Model Context Protocol) サポート

`llm-cli` は MCP クライアントとしてもサーバーとしても動作します。

### 1. SSH経由のリモート開発
`~/.config/llm_cli/config.toml` に以下を追加します：

```toml
[[mcp_servers]]
name = "my_remote_box"
command = "ssh"
args = ["user@remote-host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

### 2. MCPサーバーとして実行
```bash
llm --mcp-server
```

## ユーティリティ・スクリプト

-   `llm-cli-config`: 対話型設定ツール。
-   `*-models`: 各プロバイダの利用可能なモデルリスト。
-   `translate-json`: JSONファイル内の特定のキーを翻訳するユーティリティ。

## ライセンス

[Apache License 2.0](LICENSE) で提供されています。
