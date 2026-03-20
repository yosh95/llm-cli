# llm-cli: A Unified Terminal Interface for Multiple LLMs

![CI](https://github.com/yosh95/llm-cli/actions/workflows/ci.yml/badge.svg?branch=main)

`llm-cli` is a high-assurance command-line tool designed for interacting with Large Language Models (LLMs). It provides a unified, stable interface for Gemini, OpenAI, Claude, xAI, and local models via Ollama, prioritizing cognitive focus, secure execution, and extensible automation.

[English] | [日本語](#japanese-description)

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/architecture_diagram_en.png" width="800" alt="llm-cli Architecture & Security Guardrails" />
</p>

---

## 🚀 Quick Start

1.  **Install**:
    ```bash
    # Recommended: Install from PyPI
    pip install llm-secure-cli

    # Alternatively, install from source
    git clone https://github.com/yosh95/llm-cli.git
    cd llm-cli
    pip install .
    ```
2.  **Set API Keys**: Set your API keys as environment variables (Recommended).
    ```bash
    export GEMINI_API_KEY="your-api-key"
    # or OPENAI_API_KEY, ANTHROPIC_API_KEY, XAI_API_KEY, OLLAMA_API_KEY
    ```
3.  **Configure (Optional)**: Run `llm-cli --init-config` to generate a customizable `config.toml`.
    ```bash
    llm-cli --init-config
    # Edit ~/.llm_cli/config.toml to add MCP servers or customize behavior.
    ```
4.  **Chat**: Type `llm-cli` to start an interactive session.
5.  **Help**: Type `/help` inside the chat to see all commands.

### One-Shot Examples
```bash
# Ask a question using the default provider (e.g., Gemini)
llm-cli "What is the capital of France?"

# Use a local model via Ollama
llm-cli -p ollama -m llama3 "Explain quantum computing"

# Analyze a local file or a URL
llm-cli "Summarize this PDF" ./document.pdf
llm-cli "Analyze this website" https://example.com
```

## ✨ Core Features (Product Ready)

- **Unified Provider Access**: Seamlessly switch between Google (Gemini), OpenAI, Anthropic (Claude), xAI (Grok), and **Local LLMs (Ollama)**.
- **Autonomous Agent**: Let the AI manage files, execute Python code (replacing risky shell commands), and search the web.
- **MCP (Model Context Protocol) Support**: Connect to remote resources or services. Manage files on remote servers via SSH or integrate with third-party tools via Docker.
- **Multimodal capabilities**: Support for Images, PDFs, Audio, and Video.
- **Operational Stability**: A clean, flicker-free UI designed for long-term "Deep Work" sessions and SSH-based environments.
- **Human-in-the-Loop**: All critical actions (file edits, code execution) require explicit human approval by default.

### 🤖 Autonomous Agent & Tool Use
The AI agent autonomously uses tools to perform complex tasks, such as file management, web search, and Python execution.

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/screenshot-tool-calling.png" width="800" alt="Autonomous Agent and Tool Use" />
</p>

---

## 🛡️ Security & Governance (High-Assurance Framework)

As a tool designed with **CISSP/CISA/CCSP** principles and **EU AI Act** compliance in mind, `llm-cli` implements a multi-layered security architecture to mitigate the risks associated with autonomous AI agents.

### 1. Zero Trust & Access Control (ABAC)
`llm-cli` implements **Attribute-Based Access Control (ABAC)** instead of traditional RBAC.
- **Risk-based Scaling**: Security requirements automatically scale based on the tool's risk level (HIGH/MEDIUM/LOW).
- **Identity Proof**: High-risk actions (e.g., Python execution) require a valid **PQC-signed identity**.
- **Path Guardrails**: Tools are restricted by path attributes (defaulting to the current directory).
- **Explanation Enforcement**: Every tool mandates an `explanation` parameter, forcing the LLM to justify its intent.

### 2. Identity & Non-Repudiation (Post-Quantum Ready)
- **Hybrid Identity Tokens**: Uses **RS256** combined with **Post-Quantum Cryptography (ML-DSA)** to sign tool execution requests, ensuring long-term non-repudiation.
- **Client Integrity Attestation**: The client generates a signed manifest of its own source code state to prove the integrity of the execution environment.
- **Bi-directional Verification**: Tool results are signed by the client, allowing the LLM to verify that the observations it receives are authentic and untampered.

### 3. Observability & Anomaly Detection
- **Reasoning Sentinel (SSM-based)**: A built-in **Mamba (State Space Model)** implementation monitors the LLM's reasoning tokens in real-time. It detects statistical anomalies that may indicate prompt injection or "model hallucination" leading to risky behavior.
- **Tamper-Evident Audit Logs**: Audit trails are protected using **Chained Hashing** and optionally encrypted with **ML-KEM (Kyber)** for confidentiality.
- **Merkle Tree Anchoring**: Log batches are anchored via Merkle Roots to prevent historical revisionism.

### 4. Regulatory Alignment (EU AI Act)
`llm-cli` provides technical controls aligned with the obligations of a **GPAI (General Purpose AI) Deployer**:
- **Transparency**: Clear explanation of AI-driven actions and reasoning integrity scores.
- **Robustness**: Real-time monitoring and anomaly detection.
- **Accountability**: Cryptographically signed audit trails for forensic analysis.

---

## 📖 Advanced Commands & Power User Tips

Inside the `llm-cli` interactive session:
- `/help`: Display all available commands.
- `/p <provider>` / `/m <model>`: Switch the AI engine on the fly.
- `/attach <path/URL>`: Add a file or website content to the context.
- `/tools on|off`: Enable/disable autonomous tool use.
- `/i`: Show session integrity and Reasoning Sentinel (anomaly) scores.
- `/save` / `/load`: Manage conversation history.
- `/cp`: Checkpoint (Summarize and clear history).
- `/mcp`: Toggle or manage MCP server integrations.

### 💡 Power User Tips
- **Backgrounding (`Ctrl+Z`)**: Suspend the session to perform shell operations, then use `fg` to return.
- **External Editor (`Ctrl+X, Ctrl+E`)**: Open the current prompt in your default editor (`vim`, `nano`, etc.) for complex editing.
- **Templates**: Define reusable prompts in `~/.config/llm_cli/config.toml` and call them with `/t <name>`.

## 🔑 Security Management
Use the `llm-cli-security` tool to manage your cryptographic identity:
```bash
llm-cli-security keygen     # Generate RSA and PQC (ML-DSA/ML-KEM) keys
llm-cli-security manifest   # Rebuild integrity manifest for remote attestation
llm-cli-security decrypt-log ~/.llm_cli/audit.jsonl -o decrypted.jsonl
```

## 📜 License
Licensed under [Apache License 2.0](LICENSE). 

For detailed architectural insights and the academic background of our security framework, please refer to the **[Technical Report (Pre-print)](paper/comprehensive_framework/paper.pdf)**.

---

<a id="japanese-description"></a>

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

`llm-cli` は、Gemini, OpenAI, Claude, Grok、および Ollama を介したローカルLLMを一元的に操作できる、高い安全性を備えたCLIツールです。開発者の「深い集中（Deep Work）」を妨げない安定した対話環境と、プロフェッショナルな要求に応える高度なセキュリティ機能を両立しています。

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/architecture_diagram_ja.png" width="800" alt="llm-cli アーキテクチャと多層防御" />
</p>

## 🚀 クイックスタート

1.  **インストール**:
    ```bash
    # 推奨: PyPIからインストール
    pip install llm-secure-cli

    # あるいはソースからインストール
    git clone https://github.com/yosh95/llm-cli.git
    cd llm-cli
    pip install .
    ```
2.  **初期設定**: `llm-cli-config` を実行し、GeminiなどのAPIキーやOllamaのURLを設定。
3.  **対話開始**: `llm-cli` コマンドでスタート。
4.  **ヘルプ**: チャット内で `/help` と入力するとコマンド一覧が表示されます。

## ✨ 主な機能 (実用ツールとして)

- **統合インターフェース**: `llm-cli` コマンド一つで主要なクラウドLLMと **Ollama (Local)** にアクセス。
- **自律型エージェント**: ファイル操作、Python実行、Web検索、URL解析をAIが自律的に実行。
- **MCP (Model Context Protocol) 対応**: リモートサーバーや外部サービスとの連携をサポート。
- **マルチモーダル対応**: 画像、PDF、音声、動画の入力をサポート。画像・動画の生成も可能。
- **集中力を削がないUI**: 画面のちらつきを抑え、SSH越しでも安定して動作するクリーンなターミナル出力。

### 🤖 自律型エージェントのツール実行
AIがファイル操作、Web検索、Python実行などのツールを自律的に使用し、複雑なタスクを遂行します。

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/screenshot-tool-calling.png" width="800" alt="自律型エージェントのツール実行" />
</p>

## 🛡️ セキュリティとガバナンス (プロフェッショナル向け)

本ツールは **CISSP/CISA/CCSP** の各ドメインにおける管理策、および **EU AI Act（欧州AI法）** の技術的要件を意識して設計されています。

### 1. 実行環境の安全性と隔離
- **No-Shell アーキテクチャ**: システム操作は `shell=False` のPython実行に限定。シェルインジェクションを構造的に防止。
- **Human-in-the-Loop**: 全てのツール実行に AI による意図の説明を強制し、人間の承認を介するワークフローを提供。

### 2. アイデンティティと非否認性 (耐量子暗号)
- **ハイブリッド署名**: **RS256** と **耐量子暗号 (ML-DSA)** を組み合わせ、ツール実行リクエストの正当性を長期的に保証（非否認性）。
- **完全性検証**: クライアント自身のソースコードの状態を署名付きマニフェストで証明し、実行環境の健全性を担保。

### 3. 観測可能性と異常検知
- **推論異常モニタ (Reasoning Sentinel)**: **Mamba (SSM)** の実装により、LLMの推論プロセスをリアルタイム監視。プロンプトインジェクション等による統計的異常を検知。
- **改ざん防止監査ログ**: ハッシュ連鎖（Chained Hashing）によるログ保護と、**ML-KEM (Kyber)** による機密性保護。

### 💡 パワーユーザー向け機能
- **一時中断 (`Ctrl+Z`)**: セッションをバックグラウンドに送り、シェルに戻る。`fg` で復帰可能。
- **外部エディタ編集 (`Ctrl+X, Ctrl+E`)**: プロンプト入力を `vim` や `nano` で編集。
- **テンプレート**: 頻繁に使うプロンプトを設定ファイルに定義し、`/t <名前>` で呼び出し。

---

## 📜 ライセンス
[Apache License 2.0](LICENSE) に基づき公開されています。技術的な詳細については [テクニカルレポート](paper/comprehensive_framework/paper.pdf) を参照してください。
