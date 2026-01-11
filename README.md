--- README.md (Lines 1 to 571) ---
# llm-cli: A Unified Command-Line Interface for Multiple LLMs

[English] | [日本語](#japanese-description)

> **Note**: Japanese documentation is available at the bottom of this page.  
> **注**: 日本語での説明は、このページの後半に記載されています。

`llm-cli` is a powerful and versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), and **local LLMs via Ollama**, allowing you to seamlessly switch between providers and leverage their unique capabilities right from your terminal using a single command: `llm`.

![llm-cli banner](images/banner.jpeg)

## Screenshots

### 🔍 Real-time Research & Tool Use

The AI can use tools like `google_search` to find the latest information. In this example, it searches for the latest AI news and summarizes it. **Agent Mode is enabled by default**, allowing the AI to autonomously use various tools to help with your tasks.

![Real-time Research](images/google_search.png)

### 🌐 Web Browsing & Interaction

The AI agent can now browse the web interactively. It can navigate to URLs, click buttons, type text, and capture screenshots to "see" the page layout. This is powered by `browser-use` and Playwright.

![Web Browsing Example](images/browser_example.png)

## Features

-   **Unified Interface**: Access Gemini, OpenAI, Claude, Grok, and **Ollama** through a single `llm` command.
-   **Local LLM Support (Ollama)**: Use models locally without cloud API costs or privacy concerns.
-   **Interactive Chat Mode**: A REPL-style interface with rich syntax highlighting and Markdown rendering.
-   **Exit anytime**: Use **Escape**, **Ctrl+C**, or **Ctrl+D** at any prompt (user input or agent confirmation) to immediately exit the session.
-   **Agent Mode (Always On)**: Autonomous task execution. The AI can manage files, execute shell commands, search the web, and **dynamically attach media files**.
-   **Interactive Browsing**: The agent can perform complex web tasks (like booking, searching, or analyzing SPAs) using a real headless browser.
-   **Integrated Image Generation (Gemini)**: The agent can generate images and slides mid-conversation using Gemini's integrated image generation capabilities.
-   **Action Explanation**: All tools require the AI to provide an `explanation` parameter, describing *what* it is about to do. This improves transparency and helps users review agent actions.
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
-   **Security Guardrails**: Whitelist-based command validation protects against command injection and dangerous operations performed by the AI.
-   **One-Shot Execution**: Pipe input from other commands or pass prompts as arguments.
-   **Smart Log Management**: Automatically rotates and trims chat logs.
-   **Simple Configuration**: Interactive setup via `llm-cli-config`.

## Built-in Tools

The AI agent comes equipped with the following tools:

| Tool | Description |
| :--- | :--- |
| `execute_command` | Execute shell commands (validated against a security whitelist). |
| `list_files` | List files in a directory to explore the project structure. |
| `read_file` | Read content from a text file (with optional line range). |
| `write_file` | Create or update a file (full overwrite). |
| `edit_file` | Precise search-and-replace to modify specific code blocks. |
| `apply_diff` | Apply a Unified Diff (patch) to a file (more robust than edit_file). |
| `google_search` | Search the web for real-time information. |
| `fetch_url` | Fetch raw HTML or media files (images/PDFs) from a URL. |
| `fetch_web_text` | Fetch a URL and extract clean text content (token-efficient). |
| `attach_file` | Manually/Autonomously inject a file into the conversation context. |
| `generate_image` | Generate an image/slide using AI (Gemini) and save it locally. |
| `browser_navigate` | Navigate to a specific URL in the browser. |
| `browser_click` | Click an element on the page using CSS selectors. |
| `browser_type` | Type text into an input field. |
| `browser_screenshot` | Capture a screenshot of the current browser view. |
| `browser_get_content` | Get the text content of the current page. |

> **Note**: To use `google_search`, you need to obtain a **Google Cloud Platform API Key** and a **Custom Search Engine ID (CX)**. These can be configured using `llm-cli-config`.

## Power User Tips

For power users who need full control over their environment:

-   **Backgrounding (`Ctrl+Z`)**: You can suspend `llm-cli` at any time using `Ctrl+Z` to return to your shell. Use `fg` to resume the session. This is the recommended way to perform complex shell operations that are restricted by the AI's guardrails.
-   **External Editor (`Ctrl+X, Ctrl+E`)**: Press `Ctrl+X` followed by `Ctrl+E` at the prompt to open your current input in your default text editor (e.g., `vim`, `nano`). You can use your editor's power (like reading shell command outputs directly into the buffer) to prepare complex prompts or filter data before sending it to the LLM.

## Security

`llm-cli` implements strict security guardrails to protect against command injection and dangerous operations initiated by the AI agent:

### Command Execution Guardrails

All shell commands executed through the AI agent (`execute_command` tool) are validated against a **whitelist** of safe commands before execution.

**Default Allowed Commands**: `ls`, `cat`, `grep`, `find` and many other read-only or low-risk commands. See `llm_cli/security/command_validator.py` for the complete list.

**Supported Operations (Validated)**:
- Command chaining and pipes (`&&`, `||`, `|`) are allowed, provided that **every command** in the chain is on the whitelist.
- Absolute paths are allowed if they point to non-existent files (useful for regex/strings) or are within the current project directory.

**Blocked Patterns**:
- Command separator (`;`)
- I/O Redirection (`>`, `<`)
- Command substitution (`` ` ``, `$()`)
- Dangerous operations (e.g., `rm -rf`, `mkfs`, `dd`)
- Risky subcommands (e.g., `git push`, `pip install`, `tar -x`)
- Access to sensitive system paths (e.g., `/etc`, `/var`, `/root`)

**MCP Server Protection**: MCP server commands loaded from config files are also validated against a separate whitelist.

### Configuration

You can customize the allowed commands in `~/.config/llm_cli/config.toml`:

```toml
[security]
# Additional commands to allow beyond the default whitelist
allowed_commands = [
    "custom_script",
    "special_tool"
]

# Additional commands allowed for MCP server spawning
allowed_mcp_commands = [
    "custom_mcp_server"
]

# WARNING: Setting this to true disables protection against shell injection
# Only enable if you fully understand the security implications
allow_dangerous_patterns = false
```

**Important**: These guardrails provide defense-in-depth but do not replace user vigilance. Always review commands before approving execution.

### Risk-based Approval Skipping

While most tools require explicit user approval (Human-in-the-Loop), certain non-destructive and interactive tools may execute without a confirmation prompt to ensure a seamless user experience. This is only permitted for tools specifically flagged as safe and interactive by the developer in the local codebase. External tools (like those from MCP servers) **always** require approval.

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

> **Note**: To use LLMs from Google, OpenAI, Anthropic, or xAI, you must obtain an API key from each respective provider. These keys can be configured using `llm-cli-config`.

## Usage

### 1. Research Automation (Example)
Search for papers using Google, find the best one, and summarize its contributions in one command:
```bash
llm "Search for the 'Direct Preference Optimization' paper on Google, fetch its abstract, and summarize its key contributions."
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

-   `-p, --provider <provider>`: Specify the provider (`google`, `openai`, `anthropic`, `xai`, `ollama`).
-   `-m, --model <alias>`: Specify the model alias (e.g., `pro`, `flash`, `gpt4o`, `opus`, `gemma`).
-   `-t, --tools <tool_name>`: Enable specific tools.
-   `-s, --stdout`: Print the response directly to stdout and exit.
-   `--raw`: Disable Markdown rendering in the terminal.
-   `-d, --debug`: Enable live debug mode.
-   `--mcp`: Enable Model Context Protocol (MCP) integration.
-   `--mcp-server`: Run `llm-cli` as an MCP server.
-   `--no-system-prompt`: Disable the configured system prompt.

## In-Chat Commands

-   `/<provider>`: Switch provider instantly (`/google`, `/openai`, `/anthropic`, `/xai`, `/ollama`).
-   `/<alias>`: Switch model within the current provider (e.g., `/pro`, `/gpt4o`, `/opus`, `/gemma`).
-   `/models` (or `/m`): List available models and their aliases.
-   `/info` (or `/i`): Show current session info (provider, model, tools, etc.).
-   `/tools [on|off]`: Show or toggle tool status.
-   `/checkpoint` (or `/cp`): Summarize progress and clear conversation history.
-   `/attach <path>`: Manually attach a file (Image, PDF, Audio, Video).
-   `/save <path>`: Save conversation history to a JSON file.
-   `/load <path>`: Load conversation history from a JSON file.
-   `/dump`: Dump conversation history as a JSON object.
-   `/raw`: Show the raw conversation text.
-   `/clear` (or `/c`): Clear conversation history.
-   `/debug` (or `/d`): Toggle live debug mode.
-   `/help` (or `/h`): Show full command list.
-   `/quit` (or `/q`): Exit.

## Plugin Architecture: Adding New Tools

`llm-cli` uses a decorator-based plugin system. All tools automatically require an `explanation` parameter to ensure the AI explains what it is doing.

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

### 3. GitHub MCP Server Integration (via Docker)
You can connect the official GitHub MCP server to give your AI agent powers to read repositories, manage issues, and analyze code.

Add the following to your `~/.config/llm_cli/config.toml`:

```toml
[[mcp_servers]]
name = "github"
command = "docker"
args = [
  "run",
  "-i",
  "--rm",
  "-e", "GITHUB_PERSONAL_ACCESS_TOKEN=YOUR_GITHUB_TOKEN",
  "-e", "GITHUB_LOCKDOWN_MODE=1",
  "ghcr.io/github/github-mcp-server"
]
```

Then run `llm-cli` with the `--mcp` flag:
```bash
llm --mcp
```

## Utility Scripts

-   `llm-cli-config`: Interactive configuration tool.
-   `*-models`: List available models for each provider (e.g., `ollama-models`).

## License

This project is licensed under the [Apache License 2.0](LICENSE).

--------

<a name="japanese-description"></a>
# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

`llm-cli` は、多様な大規模言語モデル（LLM）と対話するための、強力で汎用性の高いコマンドラインツールです。Google (Gemini)、OpenAI、Anthropic (Claude)、xAI (Grok) に加え、**Ollama を介したローカルLLM** をサポートしており、単一の `llm` コマンドだけでプロバイダをシームレスに切り替えながら、各モデルの機能をターミナルから直接活用できます。

## スクリーンショット

### 🔍 リアルタイム調査とツール利用
AIは `google_search` などのツールを活用して最新情報を取得できます。この例では、最新のAIニュースを検索して要約しています。**エージェントモードはデフォルトで有効**になっており、AIが自律的に様々なツールを使いこなしながらタスクをサポートします。

![Real-time Research](images/google_search.png)

### 🌐 Webブラウジングと操作
AIエージェントが対話的にWebサイトをブラウジングできるようになりました。URLへのアクセス、ボタンのクリック、テキスト入力、そしてスクリーンショット撮影を通じて、Webサイトの構造を「見て」操作することが可能です。これには `browser-use` と Playwright が活用されています。

![Web Browsing Example](images/browser_example.png)

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで Gemini, OpenAI, Claude, Grok, **Ollama** にアクセス可能。
-   **ローカルLLM対応 (Ollama)**: クラウドAPIの料金を気にせず、プライバシーを保ったままモデルを利用できます。
-   **対話型チャットモード**: シンタックスハイライトとMarkdownレンダリングに対応したREPL形式のインターフェース。
-   **いつでも終了**: ユーザー入力やエージェントの確認プロンプトにおいて、**Escape**、**Ctrl+C**、または **Ctrl+D** を押すことで、即座にセッションを終了できます。
-   **エージェントモード（常時有効）**: 自律的なタスク実行。ファイルの管理、シェルコマンド実行、Web検索、**メディアファイルの動的添付**が可能です。
-   **対話型ブラウジング**: ヘッドレスブラウザを使用して、複雑なWeb操作（予約、検索、SPAの解析など）をエージェントが行えます。
-   **統合画像生成 (Gemini)**: 会話の途中でGeminiの画像生成機能を使い、図解やスライド画像を生成できます。
-   **実行内容の説明**: すべてのツール実行において、AIに `explanation` パラメータ（これから何をするのかという説明）の提供を強制します。これにより、ツール実行の意図が明確になり、ユーザーがエージェントの動作を確認しやすくなります。
-   **プラグインベースのツール設計**: デコレータを使用したプラグインシステムにより、新しいツールの追加が容易です。
-   **Distributed Agent via MCP**: **Model Context Protocol (MCP)** をサポート。SSH経由でリモートの `llm-cli` インスタンスに接続し、リモートサーバー上のファイル操作やテスト実行をローカルツールのように行えます。
-   **OpenAI互換カスタムエンドポイント**: `api_url` を設定することで、ローカルLLM（Ollama, vLLM 等）やその他のOpenAI互換サービスを利用可能。
-   **ユーザー主導の履歴管理（チェックポイント機能）**: `/checkpoint` コマンドで会話の要約を作成し、履歴をリセットしてコンテキストを整理。
-   **マルチモーダル対応**:
    -   **手動添付**: `/attach <path>` コマンドで画像、PDF、音声、動画を会話の途中から注入。
    -   **自律添付**: エージェントが必要に応じてツールを使い、メディアファイルをコンテキストに読み込みます。
    -   **Gemini**: テキスト、ローカル画像、PDF、**音声**、**動画**をサポート。
    -   **OpenAI / Claude / Grok**: テキスト、ローカル画像をサポート（PDFはテキストまたはBase64として処理）。
-   **URL直接指定**: ウェブサイトのURLを渡すことで、内容を自動的に解析可能（自動スクレイピング、PDF/画像のマルチモーダル注入を含む）。
-   **安全な実行**: ファイル変更時の **Diffプレビュー** 表示と、ツール実行前のユーザー確認（Human-in-the-Loop）。
-   **セキュリティガードレール**: ホワイトリストベースのコマンド検証により、AIによるコマンドインジェクションや危険な操作を防止。
-   **ワンショット実行**: 他のコマンドからのパイプ入力や、引数としてのプロンプト実行に対応。
-   **ログ管理**: チャットログの自動ローテーションとトリミング機能を搭載。
-   **簡単設定**: `llm-cli-config` による対話形式のセットアップ。

## 組み込みツール一覧

AIエージェントは以下のツールを標準で備えています：

| ツール名 | 説明 |
| :--- | :--- |
| `execute_command` | シェルコマンドを実行（ホワイトリストによる安全検証付き）。 |
| `list_files` | ディレクトリ内のファイル一覧を表示し、プロジェクト構造を把握。 |
| `read_file` | テキストファイルの内容を読み取り（行指定可能）。 |
| `write_file` | ファイルを新規作成または更新（全体書き換え）。 |
| `edit_file` | 精密な検索と置換により、特定のコードブロックを修正。 |
| `google_search` | Google検索を使用してリアルタイムの情報を取得. |
| `fetch_url` | 指定したURLから生のHTMLやメディアファイル（画像/PDF等）を取得。 |
| `fetch_web_text` | URLから本文テキストのみを抽出。トークンを節約しつつ情報を収集。 |
| `attach_file` | ファイルを会話のコンテキストに注入。 |
| `generate_image` | AI (Gemini) を使用して画像やスライドを生成し、ローカルに保存。 |
| `browser_navigate` | ブラウザで指定されたURLに移動。 |
| `browser_click` | ページ上の要素をクリック。 |
| `browser_type` | 入力フィールドにテキストを入力。 |
| `browser_screenshot` | 現在のブラウザ画面のスクリーンショットを撮影。 |
| `browser_get_content` | 現在のページのテキストコンテンツを取得。 |

> **注**: `google_search` を利用するには、**Google Cloud Platform の API キー**と**カスタム検索エンジン ID (CX)** の取得が必要です。これらは `llm-cli-config` で設定できます。

## パワーユーザー向けのTips

環境を完全にコントロールしたいパワーユーザー向け：

-   **バックグラウンド実行 (`Ctrl+Z`)**: プロンプトで `Ctrl+Z` を押すことで、いつでも `llm-cli` をサスペンドしてシェルに戻ることができます。`fg` コマンドでセッションに復帰可能です。AIのガードレールに制限されない複雑なシェル操作を行いたい場合に推奨される方法です。
-   **外部エディタ連携 (`Ctrl+X, Ctrl+E`)**: プロンプトで `Ctrl+X` に続いて `Ctrl+E` を押すと、現在の入力内容をデフォルトのテキストエディタ（`vim`, `nano` 等）で開くことができます。エディタの機能（シェルコマンドの実行結果をバッファに読み込むなど）を使い、複雑なプロンプトの作成やデータのフィルタリングを行ってからLLMに送信できます。

## セキュリティ

`llm-cli` は、AIエージェントによるコマンドインジェクションや危険な操作を防止するため、厳格なセキュリティガードレールを実装しています：

### コマンド実行ガードレール

AIエージェント (`execute_command` ツール) が実行するシェルコマンドは、実行前に安全なコマンドの**ホワイトリスト**に対して検証されます。

**デフォルトで許可されているコマンド**: `ls`, `cat`, `grep`, `find` など、読み取り専用または低リスクのコマンド。完全なリストは `llm_cli/security/command_validator.py` を参照してください。

**サポートされる操作（検証付き）**:
- コマンドチェーンおよびパイプ (`&&`, `||`, `|`) は、チェーン内の**すべてのコマンド**がホワイトリストに含まれている場合に限り許可されます。
- 絶対パスは、実在しないパス（検索パターンなど）であるか、現在のプロジェクトディレクトリ内を指している場合に許可されます。

**ブロックされるパターン**:
- コマンドセパレータ (`;`)
- I/O リダイレクト (`>`, `<`)
- コマンド置換 (`` ` ``, `$()`)
- 危険な操作 (例: `rm -rf`, `mkfs`, `dd`)
- 危険なサブコマンド (例: `git push`, `pip install`, `tar -x`)
- 重要なシステムパスへのアクセス (例: `/etc`, `/var`, `/root`)

**MCP サーバー保護**: 設定ファイルから読み込まれる MCP サーバーコマンドも、別のホワイトリストに対して検証されます。

### 設定

`~/.config/llm_cli/config.toml` で許可するコマンドをカスタマイズできます：

```toml
[security]
# デフォルトのホワイトリストに追加で許可するコマンド
allowed_commands = [
    "custom_script",
    "special_tool"
]

# MCP サーバー起動で許可する追加のコマンド
allowed_mcp_commands = [
    "custom_mcp_server"
]

# 警告: これを true に設定すると、シェルインジェクションに対する保護が無効になります
# セキュリティへの影響を十分に理解した上でのみ有効にしてください
allow_dangerous_patterns = false
```

**重要**: これらのガードレールは多層防御を提供しますが、ユーザーの注意を置き換えるものではありません。実行を承認する前に常にコマンドを確認してください。

### リスクベースの承認スキップ

ほとんどのツールは実行前にユーザーの明示的な承認（Human-in-the-Loop）を必要としますが、非破壊的かつインタラクティブなツールについては、ユーザー体験を損なわないよう承認プロンプトなしで実行される場合があります。これは、開発者によってローカルコード内で安全かつインタラクティブであると明示的にフラグを立てられたツールにのみ許可されます。MCPサーバーなどの外部ツールについては、**常に**承認が必要です。

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

> **注**: Google, OpenAI, Anthropic, xAI の LLM を利用するには、各プロバイダの API キーが必要です。これらは `llm-cli-config` で設定できます。

## 使い方

### 1. 研究調査の自動化（例）
Google検索を用いて特定のトピックに関する論文を探し、内容を要約させることができます。
```bash
llm "Googleで 'Direct Preference Optimization' に関する論文を探して、内容を読み、その主要な貢献をまとめて。"
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

-   `-p, --provider <provider>`: プロバイダを指定 (`google`, `openai`, `anthropic`, `xai`, `ollama`)。
-   `-m, --model <alias>`: モデルのエイリアスを指定 (例: `pro`, `flash`, `gpt4o`, `opus`, `gemma`)。
-   `-t, --tools <tool_name>`: 特定のツールを有効化。
-   `-s, --stdout`: 応答を直接標準出力に表示して終了。
-   `--raw`: Markdownレンダリングを無効化。
-   `-d, --debug`: ライブデバッグモードを有効化。
-   `--mcp`: MCP（Model Context Protocol）連携を有効化。
-   `--mcp-server`: `llm-cli` を MCP サーバーとして起動。
-   `--no-system-prompt`: 設定されたシステムプロンプトを無効化。

## チャット内コマンド

-   `/<provider>`: プロバイダを即座に切り替え (`/google`, `/openai`, `/anthropic`, `/xai`, `/ollama`)。
-   `/<alias>`: 現在のプロバイダ内でモデルを切り替え (例: `/pro`, `/gpt4o`, `/opus`, `/gemma`)。
-   `/models` (または `/m`): 利用可能なモデルとエイリアスを表示。
-   `/info` (または `/i`): 現在のセッション情報（プロバイダ、モデル、ツール等）を表示。
-   `/tools [on|off]`: ツールの有効・無効を切り替え。
-   `/checkpoint` (または `/cp`): 進捗を要約し、会話履歴をクリア。
-   `/attach <path>`: ファイル（画像、PDF、音声、動画）を手動で添付。
-   `/save <path>`: 会話履歴をJSONファイルに保存。
-   `/load <path>`: 会話履歴をJSONファイルから読み込み。
-   `/dump`: 会話履歴をJSON形式でダンプ。
-   `/raw`: 生の会話テキストを表示。
-   `/clear` (or `/c`): 会話履歴をクリア。
-   `/debug` (または `/d`): ライブデバッグモードのON/OFF切り替え。
-   `/help` (または `/h`): 全コマンドリストを表示。
-   `/quit` (または `/q`): 終了。

## プラグイン・アーキテクチャ: ツールの追加

`llm-cli` はデコレータベースのプラグインシステムを採用しています。登録されたすべてのツールには、AIによる実行内容の説明を明示するための `explanation` パラメータが自動的に付与されます。

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

### 3. GitHub MCP Server との連携 (Docker利用)
GitHub公式のMCPサーバーを連携させることで、AIエージェントにリポジトリの読み書き、Issueの管理、コード解析などの権限を与えることができます。

`~/.config/llm_cli/config.toml` に以下のエントリを追加します：

```toml
[[mcp_servers]]
name = "github"
command = "docker"
args = [
  "run",
  "-i",
  "--rm",
  "-e", "GITHUB_PERSONAL_ACCESS_TOKEN=あなたのGitHubトークン",
  "-e", "GITHUB_LOCKDOWN_MODE=1",
  "ghcr.io/github/github-mcp-server"
]
```

その後、`--mcp` フラグを付けて `llm-cli-config` で設定したプロバイダで `llm-cli` を起動します：
```bash
llm --mcp
```

## ユーティリティ・スクリプト

-   `llm-cli-config`: 対話型設定ツール。
-   `*-models`: 各プロバイダの利用可能なモデルリスト (例: `ollama-models`)。

## License

[Apache License 2.0](LICENSE) で提供されています。
