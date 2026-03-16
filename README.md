# llm-cli: A Unified Command-Line Interface for Multiple LLMs

![CI](https://github.com/yosh95/llm-cli/actions/workflows/ci.yml/badge.svg?branch=main)

## 📄 Technical Reports (Pre-prints)
Detailed architectural insights and security analysis are available in the following reports:
- **[A Comprehensive Security Framework for Autonomous AI Agents](paper/comprehensive_framework/paper.pdf)**: Integrating Structural Guardrails, Behavioral Zero-Trust, and Post-Quantum Resilience.

[English] | [日本語](#japanese-description)

---

`llm-cli` is a versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), and **Local LLMs via Ollama**, allowing you to switch between providers and leverage their capabilities from your terminal using a single command: `llm`.

<p align="center">
  <img src="images/architecture_diagram_en.png" width="800" alt="llm-cli Architecture & Security Guardrails" />
</p>

## Design Philosophy: Focus & Stability
`llm-cli` is designed for "deep work" environments where stability and clarity are key.
- **Eye-Friendly Interface**: Minimizes UI flicker and rapid text movement for long-term usage.
- **Reliable Performance**: Simple terminal output ensures consistent behavior across various terminal emulators and SSH sessions.
- **Cognitive Clarity**: A stable output format helps users maintain focus on the task without distracting animations.

## TL;DR (Quick Start)
- **Install**: `pip install .`
- **Configure**: `llm-cli-config` (Set API keys & Ollama URL).
- **Chat**: `llm` (Agent mode + Reasoning Monitor ON).
- **One-shot**: `llm "Summarize this" file.pdf`.
- **Switch**: `/p gemini` or `/m image`.
- **Safe**: Diff preview + Human-in-the-loop approval + Anomaly Detection.

## Key Features

- **Unified Interface**: Access major cloud LLMs (Gemini, OpenAI, Claude, Grok) and **Local LLMs (Ollama)** via a single `llm` command.
- **Reasoning Anomaly Monitor**: A lightweight **pure NumPy SSM** (Mamba) that monitors AI reasoning processes for statistical anomalies in real-time. It features a **Self-Calibrating engine** that automatically adjusts detection thresholds based on the model's learning progress (EMA loss), eliminating the need for manual tuning.
- **PQC Client Verification**: Verifies client-side integrity and generates PQC-signed (ML-DSA) tokens embedded in tool calls to provide non-repudiation.
- **Local LLM Support**: Use models locally via **Ollama** for privacy and offline usage.
- **Autonomous Agent**: The AI can manage files, **interact with the system via Python**, search the web, and attach media files.
- **Multimodal Input & Output**:
    -   **Input**: Images, PDFs, Audio, and Video.
    -   **Output**: Generate images and videos mid-conversation.
- **Distributed Agent via MCP**: Support for **Model Context Protocol**. Connect to remote instances via SSH to manage files or run tests.
- **URL Support**: Directly pass website URLs to analyze content with automatic scraping.
- **Secure Execution**: **No-Shell Architecture** (avoids shell injection), **Diff Preview** for file changes, **Static Analysis**, and **Human-in-the-Loop** confirmation.
- **Layered Security**: Hybrid PQC signatures (RSA + ML-DSA), **Client Verification**, **Linux Sandboxing (Bubblewrap)**, **Entropy-Based Secret Detection**, and **Reasoning Integrity** tracking.

## Screenshots

### 🤖 Autonomous Agent & Tool Use
The AI agent autonomously uses tools to perform complex tasks, such as understanding project structures before editing code.

<p align="center">
  <img src="images/screenshot-tool-calling.png" width="800" alt="Autonomous Agent and Tool Use" />
</p>

## Installation & Setup

### 1. Installation
Ensure you have Python 3.11 or newer.
```bash
git clone https://github.com/yosh95/llm-cli.git
cd llm-cli
pip install .
```

### 2. Configuration
Run the interactive setup to configure your API keys:
```bash
llm-cli-config
```
Alternatively, use environment variables:
```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="AIza..."
export XAI_API_KEY="xai-..."
```

## Development

A `Makefile` is provided for common development tasks:
- `make install`: Install the package in editable mode with dev/test dependencies.
- `make lint`: Run `ruff` and `mypy` for static analysis.
- `make format`: Run `ruff format` to format code.
- `make test`: Run tests with coverage report.
- `make clean`: Remove temporary files, caches (`.ruff_cache`, `__pycache__`, etc.), and build artifacts.

Alternatively, you can run the cleanup script directly:
```bash
python scripts/clean.py
```

## Usage & Commands

### 1. Interactive Chat
Simply type `llm` to start an interactive session:
```bash
llm
```

### 2. One-Shot Prompts and Piping
```bash
# Direct prompt
llm "What is the capital of France?"

# Analyze code from a pipe
cat main.py | llm "Explain this code"

# Analyze a local file or URL
llm "Summarize this paper" https://arxiv.org/pdf/1706.03762.pdf
```

### 3. Template Management
Define frequently used prompts in `~/.config/llm_cli/config.toml`:
```toml
[templates]
proofread = "Proofread the following text for grammar and clarity:"
```
Use them in chat: `> /t proofread`.

### 4. CLI Options
- `-p, --provider <provider>`: Specify provider (`google`, `openai`, `anthropic`, `xai`, `ollama`).
- `-m, --model <alias>`: Specify model alias (e.g., `pro`, `flash`, `mini`, `opus`).
- `-s, --stdout`: Print response directly to stdout and exit.
- `--raw`: Disable Markdown rendering in output.
- `--mcp`: Enable MCP integration.
- `--mcp-server`: Run as an MCP server.
- `--session <path>`: Load a saved session JSON.

### 5. In-Chat Commands
- `/p`, `/m`: Switch provider/model.
- `/t <template>`: Insert a template.
- `/i`: Show session info & Reasoning Integrity scores.
- `/cp`: Checkpoint (Summarize and clear history).
- `/attach <path>`: Manually attach a file/URL.
- `/save` / `/load`: Manage conversation history.
- `/tools on|off`: Toggle tool execution.
- `/debug`: Toggle live debug mode.
- `/reload`: Reload configuration from disk.
- `/clear`: Clear conversation history.
- `/q` / `/quit`: Exit. (Or use **Ctrl+C** / **Ctrl+D** anytime).

## Built-in Tools

| Tool | Description |
| :--- | :--- |
| `list_files_in_directory` | List files in a directory tree. |
| `search_files` | Search for a regex pattern in files. |
| `read_file_content` | Read content from a text file. |
| `execute_python` | Execute Python code for system interaction (Replaces shell commands). |
| `edit_file` | Edit a file with Diff preview. |
| `create_or_overwrite_file` | Create a new file. |
| `search_web` | Search the web using Brave Search. |
| `read_url_content` | Fetch a URL (HTML or PDF) and convert it to Markdown or text. |


## Security & Guardrails

`llm-cli` implements several security measures to protect your system:

### 🛡️ Structured System Interaction (No-Shell)
To reduce the risk of command injection, `llm-cli` avoids direct shell access. System interactions are performed via **Python code execution** with `shell=False`.

### 🛡️ Verified Tool Execution
- **Asymmetric Identity**: Uses **RS256** signatures to verify the source of tool execution requests.
- **Post-Quantum Cryptography (PQC)**: 
    - **Signatures (ML-DSA)**: Uses hybrid signatures (RSA + ML-DSA) for long-term verification.
    - **Encryption (ML-KEM)**: Protects sensitive data in transit and audit logs using hybrid encryption (ML-KEM + AES-256-GCM).
- **Client Verification**: The client calculates its own source code hash (SHA-256) and generates a PQC-signed token. This is included in the **Hybrid Identity Token (JWT)** to help remote servers confirm the client's state.
- **Adaptive Security Scaling**: Adjusts PQC security levels based on the perceived risk of the tool being called.
- **Audit Logging**: Chained hashing for tamper-evidence, with optional **ML-KEM encryption for sensitive arguments**.

### 🛡️ Reasoning Monitor (SSM-based)
Uses a **NumPy implementation of Mamba (State Space Model)** to monitor the LLM's reasoning process.
- **Statistical Monitoring**: Tracks the internal state of the Mamba model to detect statistical anomalies or significant shifts in the generated output pattern.
- **Reasoning Integrity**: If the output deviates significantly from expected patterns, the monitor flags it.
- **User Intervention**: If a high anomaly score is detected, the system can automatically switch to **Forced Human-in-the-Loop** mode.

### 🧠 Intent Analyzer: Semantic Verification
A secondary, lightweight LLM (Verifier) can be used to audit the actions of the main agent before execution. It checks if the generated code aligns with the user's original request.

### 🛡️ Secret Leak Prevention
Helps prevent accidental transmission of API keys or passwords.
- **Detection**: Combines **Entropy analysis** with model-based scoring to identify potential secrets in both prompts and AI responses.
- **Confirmation**: Alerts the user and requires explicit approval before sending or displaying data that looks like a secret.

### 🛡️ Resource Limits & Sandboxing
- **Static Analysis**: Scans Python code for potentially risky patterns (e.g., suspicious imports) before execution.
- **Linux Sandboxing (Bubblewrap)**: On Linux, provides an optional isolated environment for Python execution using `bubblewrap`.
- **Resource Constraints**: Apply timeouts and memory limits to tool execution.
- **Path Guardrails**: Restricts file operations to `allowed_paths`.
- **Human-in-the-Loop**: By default, code execution and file modifications **require human approval**.
- **Output Truncation**: Prevents very large outputs from consuming too many resources.

### 🔑 Role-Based Tool Access
- **Roles**: Tools can be assigned to different roles (e.g., `admin`, `user`).
- **Control**: Users can restrict which tools are available in a session via configuration.

## Advanced Features

### 🔌 Plugin Architecture: Adding New Tools
`llm-cli` uses a decorator-based plugin system. All tools automatically require an `explanation` parameter.
```python
@tool(name="get_weather", description="Get weather", parameters={...})
def get_weather(city: str) -> dict:
    return {"weather": "sunny"}
```

### 🌐 Model Context Protocol (MCP) Support
Connect to remote servers via SSH or integrate with services like GitHub via Docker.
```toml
[[mcp_servers]]
name = "remote"
command = "ssh"
args = ["user@host", "python3", "-m", "llm_cli.apps.mcp_server"]
```

### 🧠 Reasoning Integrity & Sentinel Updates
The built-in Reasoning Sentinel (SSM) continuously learns from verified reasoning patterns. It provides real-time protection against semantic shifts and prompt injection without external dependencies.

### 💡 Power User Tips
- **Backgrounding (`Ctrl+Z`)**: Suspend the session to perform shell operations, then use `fg` to return.
- **External Editor (`Ctrl+X, Ctrl+E`)**: Open the current prompt in `vim` or `nano` for complex editing.

### 🔑 Security Key Management
Manage your RSA and PQC (ML-DSA/ML-KEM) identity keys:
```bash
# Generate all keys (RSA, ML-DSA, ML-KEM)
llm-cli-security keygen

# Rebuild integrity manifest for remote attestation
llm-cli-security manifest

# Decrypt PQC-encrypted audit logs (ML-KEM)
llm-cli-security decrypt-log ~/.llm_cli/audit.jsonl -o decrypted.jsonl
```

## License
Licensed under [Apache License 2.0](LICENSE).

---

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

## 📄 技術レポート (Pre-prints)
詳細な解説については、以下のレポート（英語）を参照してください。
- **[A Comprehensive Security Framework for Autonomous AI Agents](paper/comprehensive_framework/paper.pdf)**: Integrating Structural Guardrails, Behavioral Zero-Trust, and Post-Quantum Resilience.

[English] | [日本語](#japanese-description)

---

`llm-cli` は、Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), および **Ollama を介したローカルLLM** を一元的に操作できる、実用性を重視したコマンドラインツールです。プロバイダーをシームレスに切り替え、ターミナルから `llm` コマンド一つで各モデルを活用できます。

<p align="center">
  <img src="images/architecture_diagram_ja.png" width="800" alt="llm-cli アーキテクチャと多層防御" />
</p>

## 設計思想：集中力と安定性の追求
`llm-cli` は、作業中の認知的負荷を抑え、安定した動作を提供することを目指しています。
- **落ち着いたUI**: 画面の激しい動きを最小限に留め、長時間使用しても疲れにくい表示環境を提供します。
- **環境を選ばない安定性**: シンプルなターミナル出力を採用することで、あらゆる環境やSSH越しの操作において一貫した動作を維持します。
- **情報の明瞭さ**: 安定した形式で出力を行うことで、ユーザーがAIとの対話や本来の作業に集中できるよう配慮しています。

## クイックスタート (TL;DR)
- **インストール**: `pip install .`
- **初期設定**: `llm-cli-config` (APIキーとOllamaの設定)
- **チャット**: `llm` (自律エージェント + 推論モニタ有効)
- **ワンショット**: `llm "要約して" file.pdf`
- **切り替え**: `/p gemini` または `/m image`
- **安全**: Diffプレビュー、人間による承認、および異常検知。

## 主な機能

- **統合インターフェース**: `llm` コマンド一つで主要なクラウドLLM (Gemini, OpenAI, Claude, Grok) と **Ollama (Local)** にアクセス。
- **推論異常モニタ**: **NumPyのみで実装された軽量SSM** (Mamba) が、AIの推論プロセスをリアルタイムで監視。モデルの学習進捗（EMA損失）に基づき、検知基準を自動で最適化する **「自己校正型エンジン」** を搭載しており、手動の閾値調整なしで高度な異常検知を実現します。
- **PQC クライアント整合性検証**: クライアントのソースコードの整合性を検証し、PQC署名 (ML-DSA) されたトークンを発行。MCPツール実行時に自身の健全性を証明します。
- **ローカルLLM対応**: **Ollama** を利用し、プライバシーを確保しながらオフラインでもモデルを実行。
- **自律型エージェント**: ファイル操作、**Python実行**、Web検索、メディア添付を自律的に実行。
- **マルチモーダル入出力**: 
    - **入力**: 画像、PDF、音声、動画の添付をサポート。
    - **出力**: 会話の流れで画像や動画の生成が可能。
- **Distributed Agent via MCP**: Model Context Protocol により、リモートサーバーの操作もサポート。
- **URL解析**: WebサイトのURLの内容を自動的に取得して解析。
- **安全な実行**: **No-Shell アーキテクチャ** (シェルインジェクションの防止)、ファイル変更の **Diff プレビュー**、**静的解析**、および **Human-in-the-Loop** による承認。
- **多層的なセキュリティ**: ハイブリッドPQC署名、**クライアント検証**、**Linuxサンドボックス (Bubblewrap)**、**エントロピーベースの機密情報検知**、および **推論整合性** トラッキング。

## スクリーンショット

### 🤖 自律型エージェントのツール実行
AIがディレクトリ構造を確認し、コードを読み取ってから作業を行う様子。

<p align="center">
  <img src="images/screenshot-tool-calling.png" width="800" alt="自律型エージェントのツール実行" />
</p>

## インストールと設定

### 1. インストール
Python 3.11以上が必要です。
```bash
git clone https://github.com/yosh95/llm-cli.git
cd llm-cli
pip install .
```

### 2. APIキーの設定
対話型スクリプトを実行：
```bash
llm-cli-config
```
または環境変数を使用：
```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="AIza..."
export XAI_API_KEY="xai-..."
```

## 開発用コマンド

開発時に便利な `Makefile` を用意しています。
- `make install`: 開発・テスト用依存関係を含めてインストール。
- `make lint`: `ruff` と `mypy` による静的解析を実行。
- `make format`: `ruff` によるコードフォーマット。
- `make test`: カバレッジレポート付きでテストを実行。
- `make clean`: キャッシュやビルド生成物を削除。

また、以下のコマンドで直接クリーンアップスクリプトを実行することも可能です：
```bash
python scripts/clean.py
```

## 使用方法とコマンド

### 1. 対話型チャット
単に `llm` と入力してセッションを開始します。
```bash
llm
```

### 2. ワンショット実行とパイプ
```bash
# 直接実行
llm "フランスの首都は？"

# パイプ入力
cat main.py | llm "解説して"

# ローカルファイルまたはURL解析
llm "内容を要約して" https://arxiv.org/pdf/1706.03762.pdf
```

### 3. テンプレート管理
`~/.config/llm_cli/config.toml` に定義したテンプレートを `/t` で呼び出せます。
```toml
[templates]
proofread = "以下のテキストの文法と明瞭さを校正してください:"
```
チャット内で使用：`> /t proofread`。

### 4. コマンドラインオプション
- `-p, --provider <provider>`: プロバイダ指定 (`google`, `openai`, `anthropic`, `xai`, `ollama`)。
- `-m, --model <alias>`: モデル指定 (例: `pro`, `flash`, `mini`, `opus`)。
- `-s, --stdout`: 結果を標準出力に表示して終了。
- `--raw`: 出力のMarkdownレンダリングを無効化。
- `--mcp`: MCP統合を有効化。
- `--mcp-server`: MCPサーバーとして実行。
- `--session <path>`: 保存されたセッションJSONを読み込み。

### 5. チャット内コマンド
- `/p`, `/m`: プロバイダ/モデル切り替え。
- `/t <template>`: テンプレート挿入。
- `/i`: セッション情報と推論異常スコアの表示。
- `/cp`: チェックポイント（履歴要約とクリア）。
- `/attach <path>`: ファイルまたはURLの添付。
- `/save` / `/load`: 会話履歴の保存と読み込み。
- `/tools on|off`: ツールの有効/無効切り替え。
- `/debug`: デバッグモードの切り替え。
- `/reload`: 設定ファイルの再読み込み。
- `/clear`: 会話履歴のクリア。
- `/q` / `/quit`: 終了。 (または **Ctrl+C** / **Ctrl+D**)。

## 組み込みツール一覧

| ツール | 説明 |
| :--- | :--- |
| `list_files_in_directory` | ディレクトリ内のファイル一覧を表示。 |
| `search_files` | 正規表現でファイルを検索。 |
| `read_file_content` | テキストファイルを読み込み。 |
| `execute_python` | Pythonコードによるシステム操作。 |
| `edit_file` | Diff表示付きのファイル編集。 |
| `create_or_overwrite_file` | ファイルの新規作成。 |
| `search_web` | Brave SearchによるWeb検索。 |
| `read_url_content` | URL (HTMLまたはPDF) をMarkdownまたはテキストとして取得。 |


## セキュリティ

`llm-cli` は、安全な運用のためのガードレールを実装しています：

### 🛡️ 構造的なインジェクション防止 (No-Shell)
シェル環境を直接提供せず、すべてのシステム操作を **Pythonコードの実行** (`shell=False`) を介して行うことで、シェルインジェクションのリスクを低減しています。

### 🛡️ 検証済みツール実行
- **非対称アイデンティティ**: RS256署名による実行主体の確認。
- **耐量子暗号 (PQC)**: 
    - **デジタル署名 (ML-DSA)**: RSA + ML-DSA のハイブリッド署名により、長期的な検証可能性を確保。
    - **暗号化 (ML-KEM)**: ML-KEM + AES-256-GCM のハイブリッド暗号により、通信路および監査ログの保護を強化。
- **クライアント整合性検証**: 自身のソースコード整合性をSHA-256で検証し、PQC署名付きトークンを生成。これを **Hybrid Identity Token (JWT)** に含めることで、リモートサーバーに対してクライアントの状態を証明します。
- **動的セキュリティスケーリング**: ツールのリスクに基づいて、セキュリティレベルを動的に調整します。
- **監査ログ**: ハッシュ連鎖による改ざん検知に加え、機密性の高い引数を **ML-KEM で暗号化**可能。

### 🛡️ 推論異常モニタ (SSM-based)
**NumPyで実装された Mamba (State Space Model)** を用い、LLMの推論プロセスをリアルタイムで監視します。
- **統計的監視**: Mambaの内部状態を活用し、生成中の統計的な異常やパターンの乖離を検知します。
- **推論の整合性**: AIの出力が期待される統計的な範囲から外れた場合に警告を発します。
- **動的介入**: 重大な異常を検知した場合、自動的に**手動承認モード**へ移行し、ユーザーの確認を求めます。

### 🧠 Intent Analyzer: 意味論的な検証
メインエージェントの行動を別の軽量LLM（検証器）が事前に監査します。生成されたコードがユーザーの意図に沿っているかを確認し、予期せぬ操作を防ぎます。

### 🛡️ 機密情報漏洩の防止
APIキーなどが外部へ送信されたり、回答に含まれたりするのを防ぐ補助機能です。
- **検知**: **エントロピー解析**とモデルベースのスコアリングを組み合わせ、機密情報の可能性が高い文字列を特定します。
- **確認**: 送信前や表示前にユーザーに警告し、明示的な許可を求めることで、データの制御権をユーザーが維持します。

### 🛡️ リソース制限とガードレール
- **静的解析**: 実行前にPythonコードをスキャンし、不審なパターン（特定のインポートなど）を検知します。
- **Linuxサンドボックス (Bubblewrap)**: Linux環境では `bubblewrap` を用いたプロセスの隔離が可能です。
- **リソース制限**: タイムアウト、メモリ制限、およびCPU時間の制限を適用します。
- **パス制限**: `allowed_paths` 内の操作に制限します。
- **Human-in-the-Loop**: 原則として、コード実行やファイル操作には**人間の承認が必要**です。
- **出力制限**: 大量出力を切り詰め、リソース枯渇を防止します。

### 🔑 ロールベースのアクセス制御
- **ロール**: ツールごとに実行に必要なロール（`admin`, `user`など）を設定可能です。
- **管理**: `llm-cli-config` を通じて、セッションで使用可能なツールを制限できます。

## アドバンスド機能

### 🔌 プラグイン: ツールの追加
デコレータベースのシステムにより、新しいツールを簡単に追加できます。
```python
@tool(name="get_weather", description="天気情報を取得", parameters={...})
def get_weather(city: str) -> dict:
    return {"weather": "sunny"}
```

### 🌐 MCP (Model Context Protocol)
SSH経由のリモート開発や、外部サービスとの連携をサポートしています。

### 🧠 推論モニタの更新
組み込みの推論モニタは、検証されたパターンから学習を継続し、精度を高めることが可能です。

### 💡 パワーユーザー向け
- **バックグラウンド実行 (`Ctrl+Z`)**: 一時停止してシェルに戻り、`fg` で復帰。
- **外部エディタ (`Ctrl+X, Ctrl+E`)**: `vim` 等でプロンプトを編集。

### 🔑 セキュリティキーの管理
RSAおよびPQCアイデンティティキーを管理するためのコマンドが用意されています。
```bash
# 鍵の生成
llm-cli-security keygen

# 整合性マニフェストの更新
llm-cli-security manifest

# 暗号化された監査ログの復号
llm-cli-security decrypt-log ~/.llm_cli/audit.jsonl -o decrypted.jsonl
```

## ライセンス
[Apache License 2.0](LICENSE) に基づき公開されています。
