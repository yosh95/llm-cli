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
-   **Agent Mode (Always On)**: Autonomous task execution. The AI can read/write files, execute shell commands, and **search the web**. It includes a **Diff Preview** for file changes to ensure safety before execution.
-   **One-Shot Execution**: Pipe input from other commands or pass prompts as arguments.
-   **Multimodal Input**: Process text, local images, PDFs, **Audio**, and **Video** (Gemini) as input for your prompts.
-   **URL Support**: Directly pass website URLs to analyze their content (includes automatic web scraping).
-   **Configurable System Prompts**: Define custom system prompts per provider and toggle them during sessions.
-   **Shell Integration**: Execute shell commands with `!command` and optionally feed the output back to the LLM.
-   **Tool Use**: Extensible tool system. All safety-checked tools are active by default.
-   **Simple Configuration**: Interactive setup via `llm-cli-config`.
-   **Smart Log Management**: Automatically rotates and trims chat logs and command history to save space.

## Installation

Ensure you have Python 3.11 or newer.

```bash
pip install llm-cli
```

## Configuration

Before using the tools, run the interactive setup script:

```bash
llm-cli-config
```

Settings are saved to `~/.config/llm_cli/config.toml`. You can also configure model aliases (e.g., `pro`, `opus`) there.

## Usage

### 1. Interactive Chat

```bash
llm
```

**Common In-Chat Commands:**
-   `/<provider>`: Switch to `/google`, `/openai`, `/claude`, or `/grok` instantly.
-   `/<alias>`: Switch model (e.g., `/pro`, `/gpt4`, `/opus`).
-   `/info` or `/i`: **Show session info** (current provider, model, and history).
-   `/tools`: Show active tools.
-   `/systemprompt` or `/sp`: Toggle system prompt.
-   `/clear` or `/c`: Clear conversation history.
-   `!command`: Execute a local shell command.
-   `/help` or `/h`: Show full command list.

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
-   `-t, --tools`: Comma-separated list of tools to enable.
-   `-s, --stdout`: Non-interactive output (prints only the response).

### 3. Utility Commands

-   `translate-json in.json out.json`: Batch translate JSON keys.
-   `gemini-models`, `openai-models`, etc.: List available models from providers.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

--------

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

`llm-cli`は、Gemini, OpenAI, Claude, Grokを一つの `llm` コマンドで自在に操れるツールです。

## 主な機能

-   **統合インターフェース**: `llm` コマンド一つで全プロバイダを切り替え可能。
-   **エージェントモード（常時有効）**: AIが自律的にファイル操作、コマンド実行、**Web検索**を行います。デフォルトで有効になっており、いつでもツールを利用可能です。ファイル書き込み時は**Diff（差分）表示**により、実行前に変更内容を確認できます。
-   **マルチモーダル**: 画像、PDF、**音声**、**動画** (Gemini) を直接プロンプトとして入力可能。
-   **URL解析**: URLを渡すだけでウェブサイトの内容をスクレイピングして解析します。
-   **シェル連携**: `!コマンド` でローカルコマンドを実行し、その結果をチャットに反映できます。
-   **高度な入力**: `Ctrl+J` による複数行入力、Markdownレンダリング、シンタックスハイライトに対応。
-   **自動ログ管理**: チャット履歴やコマンド履歴を自動的にローテーション・トリミングします。

## 使い方

### 1. 対話モード

```bash
llm
```

**主なコマンド:**
-   `/<プロバイダ>`: `/google`, `/openai`, `/claude`, `/grok` で即座に切り替え。
-   `/info` または `/i`: セッション情報の表示（プロバイダ、モデル、履歴数など）。
-   `/tools`: 有効なツールの一覧を表示。
-   `!コマンド`: シェルコマンドの実行。
-   `/help` または `/h`: ヘルプを表示。
-   `Ctrl+J`: 改行を入力。

### 2. ワンショット実行

```bash
# パイプから入力
cat file.txt | llm "この内容を要約して"

# 画像を解析
llm "この画像に写っているものを説明して" image.jpg
```

### 3. ユーティリティ

-   `llm-cli-config`: 初期設定とAPIキーの設定。

## ライセンス

[Apache License 2.0](LICENSE)
