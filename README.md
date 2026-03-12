# llm-cli: A Unified Command-Line Interface for Multiple LLMs

![CI](https://github.com/yosh95/llm-cli/actions/workflows/ci.yml/badge.svg?branch=main)

## 📄 Technical Reports (Pre-prints)
Detailed architectural insights and security analysis are available in the following reports:
- **[Post-Quantum AI Governance: Context-Adaptive Security Scaling and Bi-directional Verification for AI Agents](paper/pqc/pqc_in_ai_agents.pdf)**
- **[Zero-Trust Tool Orchestration: Securing Autonomous Agents via Asymmetric Identity and Dual-LLM Intent Analysis](paper/zero-trust/llm_cli_zero_trust.pdf)**
- **[Autonomous Guardrails: Multi-Layered Security for LLM Command-Line Interfaces](paper/guardrail/llm_cli_tech_report.pdf)**

[English] | [日本語](#japanese-description)

---

`llm-cli` is a powerful and versatile command-line tool that provides a unified interface for interacting with various Large Language Models (LLMs). It supports services from Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), and **Local LLMs via Ollama**, allowing you to seamlessly switch between providers and leverage their unique capabilities right from your terminal using a single command: `llm`.

<p align="center">
  <img src="images/architecture_diagram_en.png" width="800" alt="llm-cli Architecture & Security Guardrails" />
</p>

## TL;DR (Quick Start)
- **Install**: `pip install .`
- **Configure**: `llm-cli-config` (Set API keys & Ollama URL).
- **Chat**: `llm` (Agent mode + Reasoning Sentinel ON).
- **One-shot**: `llm "Summarize this" file.pdf`.
- **Switch**: `/p gemini` or `/m image`.
- **Safe**: Diff preview + Human-in-the-loop approval + Reasoning Anomaly Detection.

## Key Features

-   **Unified Interface**: Access Gemini, OpenAI, Claude, Grok, and **Ollama (Local)** through a single `llm` command.
-   **Quantum-Resistant Reasoning Sentinel**: A lightweight, **pure NumPy SSM** that monitors AI reasoning processes for anomalies (e.g., intent shifts or prompt injection) in real-time without heavy ML dependencies like Torch.
-   **Local LLM Support**: Use models locally via **Ollama** for maximum privacy and zero latency.
-   **Autonomous Agent**: The AI can manage files, **interact with the system via Python**, search the web, and **dynamically attach media files**.
-   **Multimodal Input & Output**:
    -   **Input**: Manual (`/attach`) attachment of Images, PDFs, Audio, and Video.
    -   **Output**: Generate images (DALL-E 3, Grok-Imagine, Gemini) and videos (Veo, Sora) mid-conversation.
-   **Distributed Agent via MCP**: Support for **Model Context Protocol**. Connect to remote instances via SSH to manage files or run tests as if they were local.
-   **URL Support**: Directly pass website URLs to analyze content with automatic scraping.
-   **Safe Execution**: **No-Shell Architecture** (structural injection prevention), **Diff Preview** for file changes, and **Human-in-the-Loop** confirmation.
-   **Advanced Security**: Hybrid PQC (Post-Quantum Cryptography) signatures, Zero-Trust orchestration, and **Reasoning Integrity** tracking.

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
| `read_html_from_url` | Fetch a URL and convert it to Markdown. |


## Security & Guardrails

`llm-cli` implements strict security guardrails to protect against unauthorized operations:

### 🛡️ No-Shell Architecture (Zero-Injection)
Unlike other AI agents, `llm-cli` does not provide a direct shell environment. Instead, all system interactions are performed via **Python code execution** (`shell=False`). This structurally eliminates shell-injection vulnerabilities.

### 🛡️ Secure MCP Orchestration (Zero Trust)
- **Asymmetric Identity**: Uses **RS256** signatures for tool execution. No shared secrets.
- **Post-Quantum Cryptography (PQC)**: Hybrid signatures (RSA + ML-DSA) ensure security against future quantum threats.
- **Context-Adaptive Security Scaling (CASS)**: Dynamically scales security levels based on tool risk.
- **Audit Logging**: Tamper-evident logs with chained hashing and Merkle Root protection.

### 🛡️ Mamba Sentinel: Real-time Intent Deviation Detection
Using a **pure NumPy implementation of Mamba (State Space Model)**, this system monitors the LLM's reasoning process at a byte level.
- **State-Based Monitoring**: Leverages Mamba's "internal state" to detect subtle logic drifts or injection attempts during generation.
- **Dynamic Intervention**: Automatically escalates to **Forced Human-in-the-Loop** mode if high-confidence anomalies (RED status) are detected, ensuring the agent cannot proceed without explicit user approval.

### 🧠 Intent Analyzer (Dual-LLM)
Uses a secondary, lightweight LLM (Verifier) to audit the actions of the main agent (including generated Python code) in real-time. If the agent's action doesn't match the user's intent (e.g., user asks to "read" but agent tries to "delete"), the execution is blocked.

### 🛡️ Resource Limits & Sandboxing
- **Resource Limits**: Default 300s timeout, 1GB memory limit (RLIMIT_AS), and CPU time limits.
- **Path Guardrails**: Restricts operations to `allowed_paths` defined in your config.
- **Human-in-the-Loop**: All code execution and file modifications **must be approved by a human**.
- **Output Truncation**: Prevents resource exhaustion by truncating large tool outputs.

### 🔑 Role-Based Access Control (RBAC)
- **Roles**: Tools can be restricted based on assigned roles (e.g., `admin`, `user`).
- **Configuration**: You can define default roles via `llm-cli-config`.
- **Note**: If `admin` is not included in the default roles, some powerful tools (like `create_or_overwrite_file`) may be restricted.

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

## License
Licensed under [Apache License 2.0](LICENSE).

---

<a name="japanese-description"></a>
# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

## 📄 技術レポート (Pre-prints)
詳細な解説については、以下のレポート（英語）を参照してください。
- **[Post-Quantum AI Governance: AIエージェントのための動的セキュリティスケーリング](paper/pqc/pqc_in_ai_agents.pdf)**
- **[Zero-Trust Tool Orchestration: 非対称アイデンティティとDual-LLM意図解析](paper/zero-trust/llm_cli_zero_trust.pdf)**
- **[Autonomous Guardrails: LLM-CLIのための多層防御セキュリティ](paper/guardrail/llm_cli_tech_report.pdf)**

`llm-cli` は、Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), および **Ollama を介したローカルLLM** を一元的に操作できるコマンドラインツールです。

<p align="center">
  <img src="images/architecture_diagram_ja.png" width="800" alt="llm-cli アーキテクチャと多層防御" />
</p>

## クイックスタート
- **インストール**: `pip install .`
- **初期設定**: `llm-cli-config` (APIキーとOllamaの設定)
- **チャット**: `llm` (自律エージェント + Reasoning Sentinel有効)
- **ワンショット**: `llm "要約して" file.pdf`
- **切り替え**: `/p gemini` または `/m image`
- **安全**: Diffプレビュー、人間による承認、および推論異常検知。

## 主な機能
- **統合インターフェース**: `llm` コマンド一つで主要なクラウドLLMと **Ollama (Local)** にアクセス。
- **Quantum-Resistant Reasoning Sentinel**: **NumPyのみで実装された軽量SSM**が、AIの推論プロセス（思考プロセス）をリアルタイムで監視。Torchなどの重い依存関係なしに、意図の乖離やインジェクションを検知。
- **ローカルLLM対応**: **Ollama** を利用し、プライバシーを確保しながらオフラインでもモデルを実行。
- **自律型エージェント**: ファイル操作、**Python実行**、Web検索、メディア添付を自律的に実行。
- **マルチモーダル入出力**: 画像、PDF、音声、動画の入力をサポート。画像・動画生成も可能。
- **Distributed Agent via MCP**: Model Context Protocol により、リモートサーバーの操作もローカル同様に可能。
- **URL解析**: WebサイトのURLを渡すだけで、内容をスクレイピングして解析。
- **堅牢なセキュリティ**: PQC（耐量子暗号）署名、Zero-Trust、および **Reasoning Integrity** トラッキング。

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
export GOOGLE_API_KEY="AIza..."
```

## 開発用コマンド

開発時に便利な `Makefile` を用意しています。
- `make install`: 開発・テスト用依存関係を含めてインストール。
- `make lint`: `ruff` と `mypy` による静的解析を実行。
- `make format`: `ruff` によるコードフォーマット。
- `make test`: カバレッジレポート付きでテストを実行。
- `make clean`: 一時ファイル、キャッシュ（`.ruff_cache`, `__pycache__` など）、ビルド生成物を削除。

また、以下のコマンドで直接クリーンアップスクリプトを実行することも可能です：
```bash
python scripts/clean.py
```

## 使用方法とコマンド

### 1. 対話型チャット
```bash
llm
```

### 2. ワンショット実行とパイプ
```bash
# 直接実行
llm "フランスの首都は？"
# パイプ入力
cat main.py | llm "解説して"
# URL解析
llm "内容を要約して" https://arxiv.org/pdf/1706.03762.pdf
```

### 3. テンプレート管理
`config.toml` に定義したテンプレートを `/t` で呼び出せます。

### 4. コマンドラインオプション
- `-p, --provider`: プロバイダ指定 (`google`, `openai`, `anthropic`, `xai`, `ollama`)。
- `-m, --model`: モデル指定。
- `-s, --stdout`: 結果を標準出力に表示して終了。
- `--raw`: 出力のMarkdownレンダリングを無効化。
- `--mcp`: MCP統合を有効化。
- `--mcp-server`: MCPサーバーとして実行。
- `--session <path>`: 保存されたセッションJSONを読み込み。

### 5. チャット内コマンド
- `/p`, `/m`: プロバイダ/モデル切り替え。
- `/t <template>`: テンプレート挿入。
- `/i`: セッション情報と Reasoning Integrity（推論整合性）スコアの表示。
- `/cp`: チェックポイント（履歴要約とクリア）。
- `/attach <path>`: ファイルまたはURLの添付。
- `/save` / `/load`: 会話履歴の保存と読み込み。
- `/tools on|off`: ツールの有効/無効切り替え。
- `/debug`: デバッグモードの切り替え。
- `/reload`: 設定ファイルの再読み込み。
- `/clear`: 会話履歴のクリア。
- `/q` / `/quit`: 終了（**Ctrl+C** / **Ctrl+D** も可）。

## 組み込みツール一覧
| ツール | 説明 |
| :--- | :--- |
| `list_files_in_directory` | ファイル一覧を表示。 |
| `search_files` | 正規表現でファイルを検索。 |
| `read_file_content` | テキストファイルを読み込み。 |
| `execute_python` | Pythonコードによるシステム操作 (シェルの代替)。 |
| `edit_file` | Diff表示付きのファイル編集。 |
| `create_or_overwrite_file` | ファイルの新規作成。 |
| `search_web` | Brave SearchによるWeb検索。 |
| `read_html_from_url` | URLをMarkdownとして取得。 |

## セキュリティ

### 🛡️ No-Shell アーキテクチャ (インジェクションの構造的排除)
他のエージェントツールとは異なり、`llm-cli` はシェル環境を直接提供しません。すべてのシステム操作は **Pythonコードの実行** (`shell=False`) を介して行われるため、シェルインジェクション脆弱性を構造的に排除しています。

### 🛡️ 安全なMCPオーケストレーション（Zero Trust）
- **非対称鍵認証**: RS256署名による実行主体確認。
- **耐量子暗号 (PQC)**: RS256 + ML-DSA のハイブリッド署名。
- **監査ログ**: ハッシュ連鎖とMerkle Rootによる改ざん検知。

### 🛡️ Mamba Sentinel: リアルタイム意図逸脱検知
**NumPyのみで実装された Mamba (State Space Model)** を用い、LLMの推論プロセスをバイトレベルでリアルタイム監視します。
- **状態ベースの監視**: Mambaの内部状態（State）を活用し、生成中の微細なロジックの乖離やインジェクション試行を検知。
- **動的介入**: 重大な異常（REDステータス）を検知した場合、自動的に**強制手動承認モード**へ移行。ユーザーの明示的な許可なしにはエージェントが次のステップに進むことを防ぎます。

### 🧠 Intent Analyzer (Dual-LLM)
メインエージェントの行動（生成されたPythonコードを含む）を別の軽量LLMがリアルタイムで監査。ユーザーの意図に反する破壊的行為を未然に防ぎます。

### 🛡️ リソース制限とガードレール
- **リソース制限**: メモリ1GB、タイムアウト300秒の制限に加え、CPU時間のハード制限を適用。
- **Human-in-the-Loop**: すべてのコード実行およびファイル操作は**人間の承認が必要**。
- **出力制限**: 大量出力を制限し、リソース枯渇を防止。

### 🔑 ロールベースアクセス制御 (RBAC)
- **ロール**: 各ツールは割り当てられたロール（`admin`, `user`など）に基づいて制限されます。
- **設定**: `llm-cli-config` を通じて、デフォルトロールを設定可能です。
- **注意**: デフォルトロールに `admin` が含まれていない場合、一部の強力なツール（`create_or_overwrite_file` など）が制限されることがあります。

## アドバンスド機能

### 🔌 プラグイン: ツールの追加
デコレータを使用して簡単に新しいツールを追加可能。AIへの「説明（explanation）」提供が必須となっています。

### 🌐 MCP (Model Context Protocol)
SSH経由のリモート開発や、Docker経由のGitHub連携などをサポート。

### 🧠 Reasoning Integrity と Sentinel の学習
組み込みの Reasoning Sentinel (SSM) は、検証された推論パターンから継続的に学習します。外部依存なしで、意味の乖離やプロンプト注入に対するリアルタイムの保護を提供します。

### 💡 パワーユーザー向け
- **バックグラウンド実行 (`Ctrl+Z`)**: 一時停止してシェルに戻り、`fg` で復帰。
- **外部エディタ (`Ctrl+X, Ctrl+E`)**: `vim` 等でプロンプトを編集。

## ライセンス
[Apache License 2.0](LICENSE) に基づき公開されています。
