# llm-cli: A Unified Command-Line Interface for Multiple LLMs (v0.1.0)

## TL;DR (Quick Start)
- **Install**: `pip install .` then `llm-cli-config` for API keys.
- **Chat**: `llm` (agent mode ON by default).
- **One-shot**: `llm "Summarize this" file.pdf`.
- **Switch**: `/p gemini` or `/m gpt4o`.
- **Tools**: Auto file ops, search, MCP remote.
- **Safe**: Whitelist + approval.

[English] | [日本語](#japanese-description)

> **Note**: Japanese documentation is available at the bottom of this page.  
> **注**: 日本語での説明は、このページの後半に記載されています。

`llm-cli` is a powerful and versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), and **local LLMs via Ollama**, allowing you to seamlessly switch between providers and leverage their unique capabilities right from your terminal using a single command: `llm`.

### Quick config.toml Example
```toml
[security]
allowed_commands = ["my_safe_script"]  # Add custom (user responsibility)

[templates]
proofread = "Proofread this text:"
```


<p align="center">
  <img src="images/llm_cli_overview_en.jpg" width="800" alt="llm-cli overview" />
</p>

## Screenshots

### 🔍 Real-time Research & Tool Use

The AI can use tools like `google_search` to find the latest information. In this example, it searches for the latest AI news and summarizes it. **Agent Mode is enabled by default**, allowing the AI to autonomously use various tools to help with your tasks.

<p align="center">
  <img src="images/google_search.png" width="700" alt="Real-time Research" />
</p>

## Features

-   **Unified Interface**: Access Gemini, OpenAI, Claude, Grok, and **Ollama** through a single `llm` command.
-   **Local LLM Support (Ollama)**: Use models locally without cloud API costs or privacy concerns.
-   **Interactive Chat Mode**: A REPL-style interface with rich syntax highlighting and Markdown rendering.
-   **Exit anytime**: Use **Escape**, **Ctrl+C**, or **Ctrl+D** at any prompt (user input or agent confirmation) to immediately exit the session.
-   **Agent Mode (Always On)**: Autonomous task execution. The AI can manage files, execute shell commands, search the web, and **dynamically attach media files**.
-   **Multimodal Output (Gemini / OpenAI / Grok)**: Generate images mid-conversation by switching to an image generation model (e.g., via `/m image`, `/m dall-e-3` or `/m grok-2-image`). Images are automatically saved locally.
-   **Action Explanation**: All tools require the AI to provide an `explanation` parameter, describing *what* it is about to do. This improves transparency and helps users review agent actions.
-   **Reasoning / Thought Toggle (New!)**: Explicitly control when the AI performs internal reasoning (e.g., DeepSeek-R1 via Ollama, Claude 3.7 Thinking, Gemini 2.0 Thinking). **Disabled by default to save tokens**. Toggle mid-session using `/thought on|off`.
-   **Plugin-based Tool Architecture**: Easily extend the agent's capabilities by adding new tool modules.
-   **Distributed Agent via MCP**: Support for **Model Context Protocol (MCP)**. You can connect to remote `llm-cli` instances via SSH and let the LLM manage files or run tests on a remote server as if they were local tools.
-   **OpenAI-Compatible Custom Endpoints**: Use local LLMs (via Ollama, vLLM, etc.) or other OpenAI-compatible services by specifying a custom `api_url` in the configuration.
-   **User-Driven Context Management (Checkpointing)**: Manually trigger `/checkpoint` to summarize the conversation and clear history.
-   **Multimodal Input & Support**:
    -   **Manual Attachment**: Use the `/attach <path>` command mid-session to inject images, PDFs, videos, or audio.
    -   **Autonomous Attachment**: Agents can use the `read_image_file`, `read_pdf_file` or `fetch_url` tools to bring media files into the context when needed.
    -   **Gemini**: Text, local images, PDFs, **Audio**, and **Video**.
    -   **OpenAI**: Text, local images, and **DALL-E image generation**.
    -   **Claude**: Text and local images (PDFs are processed as text/Base64).
    -   **Grok**: Text, local images, and **Image Generation**.
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
| `read_text_file` | Read content from a text file (with optional line range). |
| `read_pdf_file` | Read a PDF file and add it to the context. |
| `write_file` | Create or update a file (full overwrite). |
| `edit_file` | Precise search-and-replace to modify specific code blocks. |
| `google_search` | Search the web for real-time information. |
| `fetch_web_text` | Fetch a URL and extract clean text content (token-efficient). |

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
- Command separators (`;`, `&`, `\n`)
- I/O Redirection (`>`, `<`)
- Command substitution (`` ` ``, `$()`)
- Dangerous operations (e.g., `rm -rf`, `mkfs`, `dd`, `find -exec`, `find -delete`)
- Risky subcommands (e.g., `git push`, `pip install`)
- Access to sensitive system paths (e.g., `/etc`, `/var`, `/root`)
- **Note**: `awk`, `sed`, `tar`, `gzip`, `zip` and system reconnaissance tools (e.g., `whoami`, `ps`, `env`) are removed from the whitelist to minimize the attack surface. Please use Python scripts or built-in tools for complex processing.

**MCP Server Protection**:
MCP server commands defined in `config.toml` are executed as-is, trusting the user's configuration.
> **Warning**: Adding third-party MCP servers to your `config.toml` is done at your own risk. Do not register MCP servers from untrusted sources, as they may execute arbitrary code or compromise your system. Always verify the safety and integrity of the MCP server implementation before use.

### Resource Limits

To prevent resource exhaustion, commands executed by the agent are subject to the following limits:
- **CPU Time**: 30 seconds
- **Max File Write**: 50 MB
- **Memory (RLIMIT_AS)**: 1024 MB (1GB) (Default)

If a tool fails with `Exit Code: 134 (Aborted)` (commonly seen with memory-heavy tools like `ruff` or compilers), you can increase the memory limit in your configuration:

```toml
[general]
max_command_memory_mb = 1024
```

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

### Advanced Security & MCP Hardening

`llm-cli` incorporates advanced security concepts derived from CISSP ISSAP domains to ensure integrity and access control, especially when operating as an MCP server.

-   **Root of Trust**: Automatically verifies the integrity of critical application files at startup to detect tampering.
-   **Workload Identity**: Uses JWT-based identity propagation for secure client-server communication.
-   **Zero Trust Policy Engine**: Implements Role-Based Access Control (RBAC).
-   **Dual Authentication Mode**:
    -   **Strict Mode**: Requires a valid auth token (for internal `llm-cli` connections).
    -   **Guest Mode**: Allows unauthenticated clients (like Claude Desktop) restricted, read-only access.

**Configuring MCP Server Access**:
You can control how unauthenticated clients are treated in `config.toml`:

```toml
[security]
# "guest" (Default): Read-only access (Safe for Claude Desktop)
# "deny": Reject all unauthenticated connections (Zero Trust strict mode)
missing_token_policy = "guest"
```

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

### 1. Template Management (New!)
You can define frequently used prompts as templates in your `config.toml` and quickly insert them into the input buffer using the `/t` command.

1.  Add templates to `~/.config/llm_cli/config.toml`:

    ```toml
    [templates]
    proofread = "Proofread the following text for grammar and clarity:"
    summarize = "Summarize the following content into 3 key points:"
    code_review = "Review this code for bugs and improvements:"
    ```

2.  Use the template in chat:
    ```bash
    > /t proofread
    ```

    The template text will be inserted into your prompt input, allowing you to edit or append text before sending.

### 2. Research Automation (Example)
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
-   `-s, --stdout`: Print the response directly to stdout and exit.
-   `--raw`: Disable Markdown rendering in the terminal.
-   `--mcp`: Enable Model Context Protocol (MCP) integration.
-   `--mcp-server`: Run `llm-cli` as an MCP server.
-   `--session <path>`: Load a saved session JSON file on startup.

## In-Chat Commands

-   `/provider` (or `/p`): List available providers or switch provider (e.g., `/p openai`).
-   `/model` (or `/m`): List available models or switch model (e.g., `/m gpt4o`).
-   `/template` (or `/t`): Insert a template prompt into the input buffer (e.g., `/t proofread`).
-   `/info` (or `/i`): Show current session info (provider, model, tools, etc.).
-   `/tools [on|off]`: Show or toggle tool status.
-   `/thought` (or `/reasoning`) `[on|off]`: Toggle reasoning/thought display.
-   `/budget` (or `/thinking`) `<number|minimal>`: Set thinking budget for supported models.
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

## Reasoning / Extended Thinking

Modern LLMs support "reasoning" or "extended thinking" modes where the model performs internal deliberation before generating a response. This can improve the quality of responses for complex tasks.

### Provider Support

| Provider | Thinking Content Visible | Configuration |
| :--- | :--- | :--- |
| **Gemini** | ✅ Full content | `include_thoughts = true`, `thinking_level` |
| **Claude** | ✅ Summarized (Claude 4) / Full (3.7) | `thinking_budget` (tokens) |
| **OpenAI** | ⚠️ Summary only | `reasoning_effort`, `reasoning_summary` |
| **xAI (Grok)** | ❌ Not available | N/A (reasoning tokens still billed) |

### Configuration

Reasoning settings were previously configured in `defaults.toml` and `config.toml`. However, to save tokens, **reasoning is now disabled by default**.

### Toggling Reasoning Display

Use the `/thought` command (or `/reasoning`) in chat to toggle reasoning:

```bash
> /thought on   # Enable reasoning (and display thinking content if supported)
> /thought off  # Disable reasoning
> /thought      # Show current status
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

<p align="center">
  <img src="images/llm_cli_overview.jpg" width="800" alt="llm-cli 概要図" />
</p>

## スクリーンショット

### 🔍 リアルタイム調査とツール利用
AIは `google_search` などのツールを活用して最新情報を取得できます。この例では、最新のAIニュースを検索して要約しています。**エージェントモードはデフォルトで有効**になっており、AIが自律的に様々なツールを使いこなしながらタスクをサポートします。

<p align="center">
  <img src="images/google_search.png" width="700" alt="リアルタイム調査" />
</p>

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで Gemini, OpenAI, Claude, Grok, **Ollama** にアクセス可能。
-   **ローカルLLM対応 (Ollama)**: クラウドAPIの料金を気にせず、プライバシーを保ったままモデルを利用できます。
-   **対話型チャットモード**: シンタックスハイライトとMarkdownレンダリングに対応したREPL形式のインターフェース。
-   **いつでも終了**: ユーザー入力やエージェントの確認プロンプトにおいて、**Escape**、**Ctrl+C**、または **Ctrl+D** を押すことで、即座にセッションを終了できます。
-   **エージェントモード（常時有効）**: 自律的なタスク実行。ファイルの管理、シェルコマンド実行、Web検索、**メディアファイルの動的添付**が可能です。
-   **マルチモーダル出力 (Gemini / OpenAI / Grok)**: 会話の途中で画像生成モデルに切り替える（例： `/m image`、`/m dall-e-3`、`/m grok-2-image`）ことで、画像を生成できます。生成された画像は自動的にローカルに保存されます。
-   **実行内容の説明**: すべてのツール実行において、AIに `explanation` パラメータ（これから何をするのかという説明）の提供を強制します。これにより、ツール実行の意図が明確になり、ユーザーがエージェントの動作を確認しやすくなります。
-   **推論 / 思考トグル**: AIが内部推論を行うタイミングを明示的に制御します（例: Ollama経由のDeepSeek-R1、Claude 3.7 Thinking、Gemini 2.0 Thinking）。**トークン節約のためデフォルトでは無効**です。セッション中に `/thought on|off` で切り替えられます。
-   **プラグインベースのツール設計**: デコレータを使用したプラグインシステムにより、新しいツールの追加が容易です。
-   **Distributed Agent via MCP**: **Model Context Protocol (MCP)** をサポート。SSH経由でリモートの `llm-cli` インスタンスに接続し、リモートサーバー上のファイル操作やテスト実行をローカルツールのように行えます。
-   **OpenAI互換カスタムエンドポイント**: `api_url` を設定することで、ローカルLLM（Ollama, vLLM 等）やその他のOpenAI互換サービスを利用可能。
-   **ユーザー主導の履歴管理（チェックポイント機能）**: `/checkpoint` コマンドで会話の要約を作成し、履歴をリセットしてコンテキストを整理。
-   **マルチモーダル対応**:
    -   **手動添付**: `/attach <path>` コマンドで画像、PDF、音声、動画を会話の途中から注入。
    -   **自律添付**: エージェントが必要に応じてツールを使い、メディアファイルをコンテキストに読み込みます。
    -   **Gemini**: テキスト、ローカル画像、PDF、**音声**、**動画**をサポート。
    -   **OpenAI**: テキスト、ローカル画像、および **DALL-E による画像生成**をサポート。
    -   **Claude / Grok**: テキスト、ローカル画像をサポート（PDFはテキストまたはBase64として処理）。
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
| `edit_file` | 精密な検索と置換により、特定のコードブロックを修正. |
| `google_search` | Google検索を使用してリアルタイムの情報を取得. |
| `fetch_web_text` | URLから本文テキストのみを抽出。トークンを節約しつつ情報を収集。 |
| `read_text_file` | テキストファイルの内容を読み取り（行指定可能）。 |
| `read_pdf_file` | PDFファイルを読み込んでコンテキストに追加。 |

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
- コマンドセパレータ (`;`, `&`, `\n`)
- I/O リダイレクト (`>`, `<`)
- コマンド置換 (`` ` ``, `$()`)
- 危険な操作 (例: `rm -rf`, `mkfs`, `dd`, `find -exec`, `find -delete`)
- 危険なサブコマンド (例: `git push`, `pip install`, `tar -x`)
- 重要なシステムパスへのアクセス (例: `/etc`, `/var`, `/root`)
- **注**: `awk` は `system()` 関数によるリスクがあるため、ホワイトリストから削除されました。代わりに `grep`, `sed`, `cut` を使用してください。

**MCPサーバーの保護**:
`config.toml` で定義されたMCPサーバーの起動コマンドは、ユーザーの設定を信頼してそのまま実行されます。
> **警告**: サードパーティ製のMCPサーバーを `config.toml` に追加する場合は、**自己責任**で行ってください。信頼できないソースからのMCPサーバーは、任意のコードを実行したりシステムを侵害したりする可能性があるため、登録しないでください。使用する前に、必ずMCPサーバーの実装の安全性と整合性を確認してください。

### リソース制限

リソースの枯渇を防ぐため、エージェントが実行するコマンドには以下の制限が適用されます。
- **CPU時間**: 30秒
- **最大ファイル書き込み**: 50 MB
- **メモリ (RLIMIT_AS)**: 1024 MB (1GB) (デフォルト)

`ruff` やコンパイラなどのメモリ消費の激しいツールを実行した際に `Exit Code: 134 (Aborted)` で失敗する場合は、設定ファイル（`~/.config/llm_cli/config.toml`）の `[general]` セクションでメモリ制限を増やすことができます。

```toml
[general]
max_command_memory_mb = 1024
```

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

### 高度なセキュリティ機能とMCPの堅牢化

`llm-cli` は、CISSP ISSAPドメインの知識に基づいた高度なセキュリティ実装を取り入れ、特にMCPサーバーとして動作する際の堅牢性を高めています。

-   **Root of Trust (信頼の基点)**: 起動時に重要ファイルのハッシュ値を検証し、改ざんを検知します。
-   **Workload Identity (ワークロード認証)**: クライアント-サーバー間でJWTを用いたIDプロパゲーションを行い、正規のクライアントのみを認証します。
-   **Zero Trust Policy Engine**: ロールベースアクセス制御 (RBAC) により、デフォルトですべての操作を拒否し、許可された操作のみを通します。
-   **デュアル認証モード**:
    -   **Strictモード**: 正規のトークンを持つ `llm-cli` クライアントのみ許可します。
    -   **Guestモード**: Claude Desktopなどのトークンを持たないクライアントに対し、読み取り専用（Guest）権限での接続を許可します。

**MCPサーバー接続設定**:
`config.toml` で、認証トークンを持たないクライアントの扱いを設定できます。

```toml
[security]
# "guest" (デフォルト): 読み取り専用アクセス（Claude Desktop等との互換性重視）
# "deny": 未認証の接続を全て拒否（厳格なゼロトラスト環境向け）
missing_token_policy = "guest"
```

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

> **Note**: Google, OpenAI, Anthropic, xAI の LLM を利用するには、各プロバイダの API キーが必要です。これらは `llm-cli-config` で設定できます。

## 使い方

### 1. テンプレート管理
事前に定義されたプロンプトテンプレートを挿入できます：
```bash
> /t proofread
```
テンプレートのテキストが入力欄に挿入され、送信前に編集や追記が可能です。

### 2. 研究調査の自動化（例）
Google検索を用いて特定のトピックに関する論文を探し、内容を要約させることができます。
```bash
llm "Googleで 'Direct Preference Optimization' に関する論文を探して、内容を読み、その主要な貢献をまとめて。"
```

### 3. インタラクティブ・チャット
単に `llm` と打つだけでセッションが開始されます：
```bash
llm
```

### 4. ワンショットプロンプトとパイプ利用
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
-   `-s, --stdout`: 応答を直接標準出力に表示して終了。
-   `--raw`: Markdownレンダリングを無効化。
-   `--mcp`: MCP（Model Context Protocol）連携を有効化。
-   `--mcp-server`: `llm-cli` を MCP サーバーとして起動。
-   `--session <path>`: 保存されたセッションJSONファイルを起動時に読み込み。

## チャット内コマンド

-   `/provider` (または `/p`): 利用可能なプロバイダを表示、またはプロバイダを切り替え (例: `/p openai`)。
-   `/model` (または `/m`): 利用可能なモデルを表示、またはモデルを切り替え (例: `/m gpt4o`)。
-   `/template` (または `/t`): 定型プロンプトを呼び出し、入力欄にセット (例: `/t proofread`)。
-   `/info` (または `/i`): 現在のセッション情報（プロバイダ、モデル、ツール等）を表示。
-   `/tools [on|off]`: ツールの有効・無効を切り替え、または状態表示。
-   `/thought` (または `/reasoning`) `[on|off]`: 推論（thought）表示の有効・無効を切り替え。
-   `/budget` (または `/thinking`) `<number|minimal>`: 対応モデルの思考トークン予算（Thinking Budget）を設定。
-   `/checkpoint` (または `/cp`): 会話の要約を作成し、履歴をリセット（チェックポイント）。
-   `/attach <path>`: ファイル（画像、PDF、音声、動画）を手動添付。
-   `/save <path>`: 会話履歴をJSONファイルに保存。
-   `/load <path>`: 会話履歴をJSONファイルから読み込み。
-   `/dump`: 会話履歴をJSONオブジェクトとしてダンプ。
-   `/raw`: 生の会話テキストを表示。
-   `/clear` (または `/c`): 会話履歴を消去。
-   `/debug` (または `/d`): ライブデバッグモードの切り替え。
-   `/help` (または `/h`): コマンドリストを表示。
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

## Reasoning / 拡張思考機能

最新のLLMは「reasoning」や「extended thinking」モードをサポートしており、応答生成前にモデルが内部で熟考を行います。これにより、複雑なタスクに対する応答品質が向上します。

### プロバイダ別サポート状況

| プロバイダ | 思考内容の表示 | 設定 |
| :--- | :--- | :--- |
| **Gemini** | ✅ 完全表示 | `/thought on` で有効化 |
| **Claude** | ✅ 要約版（Claude 4）/ 完全版（3.7） | `/thought on` で有効化 |
| **OpenAI** | ⚠️ 要約のみ | `/thought on` で有効化 |
| **xAI (Grok)** | ❌ 非対応 | N/A（推論トークンは課金される） |

### 推論（thought）の切り替え

以前は `config.toml` での常時設定が必要でしたが、**トークン節約のため現在はデフォルトで無効**になっています。チャット内で `/thought` コマンドを使用していつでも切り替えが可能です。

```bash
> /thought on   # 推論（thought）を有効化（対応モデルで思考プロセスを表示・取得）
> /thought off  # 推論を無効化
> /thought      # 現在の状態を表示
```

## ユーティリティ・スクリプト

-   `llm-cli-config`: 対話型設定ツール。
-   `*-models`: 各プロバイダの利用可能なモデルリスト (例: `ollama-models`)。

## License

[Apache License 2.0](LICENSE) で提供されています。
