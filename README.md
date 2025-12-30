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
-   **Safe Execution**: Includes a **Diff Preview** for file changes (via `write_file`) and asks for user confirmation before executing any tool or shell command.
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

## Configuration

Before using the tools, run the interactive setup script:

```bash
llm-cli-config
```

Settings are saved to `~/.config/llm_cli/config.toml`. You can also configure model aliases (e.g., `pro`, `opus`, `gpt4`) there.

## Usage

### 1. Interactive Chat

```bash
llm
```

**Common In-Chat Commands:**
-   `/<provider>`: Switch provider instantly.
    -   `/google` (or `/gemini`)
    -   `/openai` (or `/gpt`)
    -   `/anthropic` (or `/claude`)
    -   `/xai` (or `/grok`)
-   `/<alias>`: Switch model within the current provider (e.g., `/pro`, `/gpt4`, `/opus`).
-   `/info` (or `/i`): Show session info (current provider, model, tools, and history count).
-   `/tools`: Show currently active tools.
-   `/clear` (or `/c`): Clear conversation history.
-   `!command`: Execute a local shell command. You can choose to add the output to the chat context.
-   `/help` (or `/h`): Show full command list.
-   `/quit` (or `/q`): Exit.

**Keyboard Shortcuts:**
-   `Ctrl+J`: Insert a newline for multi-line input.
-   `Ctrl+C`: Cancel current prompt or exit.

### 2. One-Shot Prompts

```bash
# Analyze code from a pipe
cat main.py | llm "Explain this code"

# Specific provider with file input
llm -p google "What happens in this video?" presentation.mp4
```

**CLI Options:**
-   `-p, --provider`: Specify provider.
-   `-m, --model`: Use a specific model alias.
-   `-t, --tools`: Enable specific tools (e.g., `-t google_search`).
-   `-s, --stdout`: Non-interactive output (prints only the response).
-   `--raw`: Disable Markdown rendering.
-   `--no-system-prompt`: Disable the configured system prompt for this session.

### 3. Utility Commands

-   `translate-json in.json out.json -k key.name`: Batch translate JSON values using LLM.
-   `gemini-models`, `openai-models`, `claude-models`, `grok-models`: List available models and their aliases for each provider.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

--------

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

`llm-cli`は、Gemini, OpenAI, Claude, Grokを一つの `llm` コマンドで自在に操れる、強力なコマンドラインツールです。

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで全プロバイダを切り替え可能。
-   **エージェントモード（常時有効）**: AIが自律的にファイル操作、コマンド実行、**Web検索**を行います。デフォルトで有効になっており、いつでもツールを利用可能です。
-   **安全な実行**: ファイル書き込み（`write_file`）時は**Diff（差分）表示**を行い、すべてのツール実行やシェルコマンド実行前にユーザーの確認を求めます。
-   **マルチモーダル対応**:
    -   **Gemini**: テキスト、画像、PDF、**音声**、**動画**。 (大容量ファイルやメディアは自動的に Gemini File API を使用)。
    -   **OpenAI / Claude / Grok**: テキスト、画像。
-   **URL解析**: URLを渡すだけでウェブサイトの内容を解析します（PDFや画像URLの場合はマルチモーダルデータとして注入）。
-   **シェル連携**: `!コマンド` でローカルコマンドを実行し、その結果をチャットのコンテキストに反映できます。
-   **高度な入力**: `Ctrl+J` による複数行入力、Markdownレンダリング、シンタックスハイライトに対応。
-   **自動ログ管理**: チャット履歴やコマンド履歴を自動的にローテーション・トリミングします。

## インストール

Python 3.11 以上が必要です。

```bash
# リポジトリをクローン
git clone https://github.com/yosh95/llm-cli.git

# ディレクトリに移動
cd llm-cli

# インストール
pip install .
```

## 使い方

### 1. 対話モード

```bash
llm
```

**主なコマンド:**
-   `/<プロバイダ>`: `/google`, `/openai`, `/anthropic`, `/xai` 等でプロバイダを即座に切り替え。
-   `/<エイリアス>`: `/pro`, `/gpt4`, `/opus` 等でモデルを切り替え。
-   `/info` (または `/i`): セッション情報の表示（プロバイダ、モデル、有効なツール、履歴数）。
-   `/tools`: 有効なツールの一覧を表示。
-   `/clear` (または `/c`): 会話履歴をクリア。
-   `!コマンド`: シェルコマンドの実行。結果をコンテキストに追加するか選択可能。
-   `/help` (または `/h`): ヘルプを表示。

### 2. ワンショット実行

```bash
# パイプから入力
cat file.txt | llm "この内容を要約して"

# 画像や動画を解析 (Geminiの場合)
llm -p google "この動画の内容を説明して" video.mp4
```

### 3. ユーティリティ

-   `llm-cli-config`: 初期設定とAPIキーの設定。
-   `translate-json`: LLMを使用したJSONデータの翻訳。
-   `gemini-models`, `openai-models` 等: 各プロバイダの利用可能なモデル一覧を表示。

## ライセンス

[Apache License 2.0](LICENSE)
