# llm-cli: A Unified Terminal Interface for Multiple LLMs

![CI](https://github.com/yosh95/llm-cli/actions/workflows/ci.yml/badge.svg?branch=main)

`llm-cli` is a high-assurance command-line tool designed for interacting with Large Language Models (LLMs). It provides a unified, stable interface for Gemini, OpenAI, Claude, and local models via Ollama, prioritizing cognitive focus, secure execution, and extensible automation.

[English] | [日本語](#japanese-description)

---

###  Purpose & Positioning

Enterprise adoption of autonomous AI agents faces a fundamental, unsolved challenge: **how do you grant an AI meaningful agency while maintaining the security and governance standards that organizations require?** This project is one engineer's attempt to answer that question in working code.

`llm-cli` was built primarily as a **personal daily-use tool** and as a **portfolio artifact** — a concrete demonstration of how CISSP/CISA/CCSP-level security principles (Zero Trust, ABAC, non-repudiation, PQC resilience) can be applied to the novel threat surface introduced by autonomous LLM agents.

**This tool is not certified or validated for enterprise production use.** No formal third-party security audit has been conducted, and the PQC primitives rely on pure-Python reference implementations that have not undergone independent cryptographic review. Deploying this in a regulated or mission-critical environment without additional validation would be inappropriate.

Instead, its recommended uses are:

-  **As a reference architecture** — for security engineers and architects exploring what a high-assurance agentic system *could* look like.
-  **As an evaluation platform** — for studying the practical trade-offs between AI agent autonomy and hybrid high-assurance security controls.
-  **As a design provocation** — a starting point for organizational discussions on agentic AI governance, not a finished answer.

The accompanying [Technical Report](paper/comprehensive_framework/paper.pdf) details the threat model and architectural decisions behind this framework.

---

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/architecture_diagram_en.png" width="800" alt="llm-cli Architecture & Security Guardrails" />
</p>

<p align="center">
  <img src="images/architecture_diagram_simple.png" width="800" alt="llm-cli Simplified Architecture Flow" />
  <br>
  <em>Simplified Architecture Flow (TikZ version)</em>
</p>

---

##  Quick Start

1.  **Install**:
    ```bash
    # Recommended: Install from PyPI
    pip install llm-secure-cli

    # Alternatively, install from source
    git clone https://github.com/yosh95/llm-cli.git
    cd llm-cli
    pip install .
    ```
2.  **Set API Keys**: `llm-cli` requires API keys to be set as environment variables.
    ```bash
    export GEMINI_API_KEY="your-api-key"
    # Supported: GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, OLLAMA_API_KEY
    ```
3.  **Chat**: Type `llm-cli` to start an interactive session.
    *   **Automatic Initialization**: On the first run, `~/.llm_cli/config.toml` is automatically created.
    *   **Native Web Search**: Gemini, OpenAI, and Claude support built-in web search automatically using your provider API key.
    *   **Brave Search**: Support for the Brave Search API is also available for comprehensive searching across all providers (requires `BRAVE_API_KEY`).
4.  **Configure (Optional)**: To customize behavior or add MCP servers, edit the configuration file:
    ```bash
    # Edit ~/.llm_cli/config.toml to modify settings.
    ```
5.  **Help**: Type `/help` inside the chat to see all commands.

### One-Shot Examples
```bash
# Ask a question using the default provider (Gemini)
llm-cli "What is the capital of France?"

# Use a specific provider and model
llm-cli -p anthropic -m sonnet "Explain quantum computing"

# Analyze a local file or a URL
llm-cli "Summarize this PDF" ./document.pdf
llm-cli "Analyze this website" https://example.com
```

## Core Features

- **Unified Provider Access**: Seamlessly switch between Google (Gemini), OpenAI, Anthropic (Claude), and **Local LLMs (Ollama)**.
- **Autonomous Agent**: Let the AI manage files, execute Python code (replacing risky shell commands), and search the web using **Provider-Native Search** (Gemini Grounding, OpenAI/Claude Web Search) or **Brave Search**.
- **Config-free Execution**: Start using immediately by just providing an environment variable.
- **MCP (Model Context Protocol) Support**: Connect to remote resources or services via custom servers.
- **Multimodal capabilities**: Support for Images, PDFs, Audio, and Video.
- **Operational Stability**: A clean, flicker-free UI designed for long-term "Deep Work" sessions and SSH-based environments.
- **Human-in-the-Loop**: All critical actions (file edits, code execution) require explicit human approval by default.

### Autonomous Agent & Tool Use
The AI agent autonomously uses tools to perform complex tasks, such as file management, web search, and Python execution. Web search is powered by the LLM provider's native capabilities (Gemini Grounding, OpenAI/Claude Web Search) or the Brave Search API, ensuring high-quality real-time information with citations.

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/screenshot-tool-calling.png" width="800" alt="Autonomous Agent and Tool Use" />
</p>

---

## Security & Governance (High-Assurance Framework)

As a tool designed with **CISSP/CISA/CCSP** principles and **EU AI Act** compliance in mind, `llm-cli` implements a multi-layered security architecture to mitigate the risks associated with autonomous AI agents.

### 1. Access Control (ABAC)
`llm-cli` implements **Attribute-Based Access Control (ABAC)**, providing granular security based on execution context and resource attributes.
- **Risk-based Scaling**: Security requirements automatically scale based on the tool's risk level (HIGH/MEDIUM/LOW).
- **Intent Verification (Dual LLM)**: High-risk actions are cross-verified by a separate, lightweight "Verifier" LLM (e.g., Gemini Flash Lite) to ensure the proposed tool call aligns with the user's original intent, mitigating sophisticated prompt injection. 
  - **Asynchronous Execution**: To minimize latency, verification runs in the background while the user reviews the tool's explanation. The result is synchronized at the moment of approval, providing a seamless high-assurance experience.
  - In `high` security mode, a functional Dual LLM provider is **required**.
  - If the secondary LLM is misconfigured or unreachable (Soft Failure), the system will fallback to explicit manual user approval rather than failing open.
  - If the intent check actively rejects the call (Hard Block), the execution is strictly denied.
- **Identity Proof**: High-risk actions (e.g., Python execution) require a valid **PQC-signed identity token**. In `high` mode, execution is blocked if keys are missing.
- **Compatibility Mode**: Use `LLM_CLI_SECURITY_LEVEL=standard` or set `security_level = "standard"` in `config.toml` to enable interoperability with non-llm-cli clients or legacy MCP servers, downgrading PQC enforcement and integrity checks to warnings.
  ```toml
  [security]
  security_level = "standard"
  ```
- **AST-based Static Analysis**: Every Python script is inspected before execution to block dangerous modules (`os.system`, `base64`, `socket`, etc.), reflection attacks, and **obfuscated keyword construction** (e.g., `"ex" + "ec"`).
- **Path Guardrails**: Tools are restricted by path attributes (defaulting to the current directory). The policy engine now inspects multiple argument names (`path`, `directory`, `file`, `src`, `dest`, etc.) to prevent bypass.
- **Explanation Enforcement**: Every tool mandates an `explanation` parameter, forcing the LLM to justify its intent.

### 2. Identity & Non-Repudiation (Experimental Reference)
- **Distributed Trust Model**: Implements a decentralized identity model where clients and servers only exchange public keys. This is designed to explore how to prevent lateral movement if a single component is compromised; however, it requires thorough evaluation before use in production environments.
- **Hybrid Identity Tokens**: Uses **COSE (RFC 9052)** binary structures combining **RS256** with **Post-Quantum Cryptography (ML-DSA)**. This serves as a reference for how long-term non-repudiation might be handled in autonomous agent systems.
- **Client Integrity Attestation**: The client generates a signed manifest of its own source code state to demonstrate the integrity of the execution environment.
- **Bi-directional Verification**: Tool results can be signed by the responder, allowing the requester to verify that the observations are authentic and untampered within the protocol's scope.

### 3. Observability & Audit Compliance (Tier 3 Reference Implementation)
- **Tamper-Evident Audit Logs**: Audit trails are protected using **Chained Hashing** and optionally encrypted with **ML-KEM (Kyber)** for confidentiality.
- **Merkle Tree Anchoring**: The Tier 3 implementation uses Merkle Trees to anchor log batches, demonstrating an architecture to prevent historical revisionism and provide compact proofs of session integrity.

---

##  Advanced Commands & Power User Tips

Inside the `llm-cli` interactive session:
- `/help`: Display all available commands.
- `/p <provider>` / `/m <model>`: Switch the AI engine on the fly.
- `/attach <path/URL>`: Add a file or website content to the context.
- `/tools on|off`: Enable/disable autonomous tool use.
- `/i`: Show session integrity and security status.
- `/save` / `/load`: Manage conversation history.
- `/cp`: Checkpoint (Summarize and clear history).
- `/mcp`: Toggle or manage MCP server integrations.

###  Logging & Troubleshooting
By default, `llm-cli` and its related tools suppress all informational logs and only show `WARNING` or `ERROR` messages. If you encounter issues:
- **Enable Debug Mode**: Add the `--debug` flag to any tool to see detailed execution logs:
  ```bash
  llm-cli --debug "query"
  llm-cli-security --debug verify
  ```
- **MCP Debugging**: To troubleshoot the MCP server (which is often spawned by a third-party client), use the `MCP_DEBUG` environment variable:
  ```bash
  export MCP_DEBUG=1
  # Then start your MCP client (e.g., Claude Desktop)
  ```
- **Log Location**: Security and audit logs are stored in `~/.llm_cli/audit.jsonl`.

### Power User Tips
- **Backgrounding (`Ctrl+Z`)**: Suspend the session to perform shell operations, then use `fg` to return.
- **External Editor (`Ctrl+X, Ctrl+E`)**: Open the current prompt in your default editor (`vim`, `nano`, etc.) for complex editing.
- **Templates**: Define reusable prompts in `~/.llm_cli/config.toml` and call them with `/t <name>`.
- **Model-specific Tool Disabling**: For models that do not support tool use (e.g., image generation models), you can pre-configure them to disable tools automatically in `config.toml`:
  ```toml
  [google.models]
  image = { model = "gemini-1.5-flash-image-preview", tools = false }
  ```
- **Disabling Tools Manually**: Use `/tools off` to prevent errors when using a model that doesn't support function calling.

## Security Management
Use the `llm-cli-security` tool to manage your cryptographic identity:
```bash
llm-cli-security keygen     # Generate RSA and PQC (ML-DSA/ML-KEM) keys
llm-cli-security manifest   # Rebuild integrity manifest for remote attestation
llm-cli-security decrypt-log ~/.llm_cli/audit.jsonl -o decrypted.jsonl
```

##  License
Licensed under [Apache License 2.0](LICENSE). 

For detailed architectural insights and the academic background of our security framework, please refer to the **[Technical Report (Pre-print)](paper/comprehensive_framework/paper.pdf)**.

---

<a id="japanese-description"></a>

# llm-cli: 複数LLM対応 統合コマンドラインインターフェース

`llm-cli` は、Gemini, OpenAI, Claude、および Ollama を介したローカルLLMを一元的に操作できる、高い安全性を備えたCLIツールです。開発者の「深い集中（Deep Work）」を妨げない安定した対話環境と、プロフェッショナルな要求に応える高度なセキュリティ機能を両立しています。

---

###  位置づけと目的

企業における自律型 AI エージェントの活用には、根本的かつ未解決の課題があります。**「AIに十分な自律性を与えながら、組織が求めるセキュリティ標準とガバナンスをどう両立させるか」**――本プロジェクトは、その問いに対してエンジニアが動くコードで答えを試みたものです。

`llm-cli` は主に**個人の日常利用ツール**として、また**ポートフォリオ**として開発されました。Zero Trust・ABAC・非否認性・耐量子暗号といった CISSP/CISA/CCSP レベルのセキュリティ原則を、自律型 LLM エージェントがもたらす新しい脅威対象に適用すると、実装としてどのような形になるかを具体的に示すことを目的としています。

**本ツールは、エンタープライズ本番環境への適用を保証・認定するものではありません。** 第三者による正式なセキュリティ監査は実施されておらず、PQC プリミティブは独立した暗号学的レビューを受けていない純粋 Python 参照実装に依存しています。規制対象業務やミッションクリティカルな環境への追加検証なしでの展開は推奨しません。

本プロジェクトの推奨される活用方法は以下のとおりです。

-  **参照アーキテクチャとして** ― 高保証なエージェントシステムが「どのような設計になりえるか」を探求するセキュリティエンジニア・アーキテクト向け。
-  **評価プラットフォームとして** ― AI エージェントの自律性とハイブリッドな高保証セキュリティ制御の間にある実践的なトレードオフを検討するための実験基盤として。
-  **設計上の問いかけとして** ― 組織内における AI エージェントのガバナンス議論の起点として。完成した答えではなく、問いを深めるための素材として。

設計の背景にある脅威モデルとアーキテクチャ上の意思決定については、[テクニカルレポート](paper/comprehensive_framework/paper.pdf)で詳述しています。

---

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/architecture_diagram_ja.png" width="800" alt="llm-cli アーキテクチャと多層防御" />
</p>

<p align="center">
  <img src="images/architecture_diagram_simple.png" width="800" alt="llm-cli 簡易アーキテクチャフロー" />
  <br>
  <em>簡易アーキテクチャフロー (TikZ版)</em>
</p>

---

##  クイックスタート

1.  **インストール**:
    ```bash
    # 推奨: PyPIからインストール
    pip install llm-secure-cli

    # あるいはソースからインストール
    git clone https://github.com/yosh95/llm-cli.git
    cd llm-cli
    pip install .
    ```
2.  **APIキーの設定**: APIキーを環境変数として設定します。
    ```bash
    export GEMINI_API_KEY="your-api-key"
    # 対応: GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, OLLAMA_API_KEY
    ```
3.  **対話開始**: `llm-cli` コマンドでスタート。
    *   **設定の自動生成**: 初回起動時に `~/.llm_cli/config.toml` が自動的に作成されます。
    *   **ネイティブWeb検索**: Gemini, OpenAI, Claude はプロバイダーのAPIキーのみで、組み込みのWeb検索（Grounding等）を自動的に利用可能です。別途検索APIキーを用意する必要はありません。
    *   **Brave Search**: すべてのプロバイダーで利用可能な共通のWeb検索ツールとして Brave Search API をサポートしています（`BRAVE_API_KEY` が必要）。
4.  **詳細設定 (任意)**: MCPサーバーの追加や動作のカスタマイズを行いたい場合は、生成された設定ファイルを編集します。
    ```bash
    # ~/.llm_cli/config.toml を編集して設定を調整してください。
    ```
5.  **ヘルプ**: チャット内で `/help` と入力するとコマンド一覧が表示されます。

## 主な機能 (実用ツールとして)

- **統合インターフェース**: `llm-cli` コマンド一つで主要なクラウドLLMと **Ollama (Local)** にアクセス。
- **自律型エージェント**: ファイル操作、Python実行、Web検索、URL解析をAIが自律的に実行。Web検索はプロバイダー提供の**ネイティブ検索機能**（Gemini Grounding, OpenAI/Claude Web Search等）または **Brave Search** を使用します。
- **設定不要の即時利用**: 環境変数を設定するだけで、セットアップの手間なく利用可能。
- **MCP (Model Context Protocol) 対応**: リモートサーバーや外部サービスとの連携をサポート。
- **マルチモーダル対応**: 画像、PDF、音声、動画の入力をサポート。画像生成も可能。
- **集中力を削がないUI**: 画面のちらつきを抑え、SSH越しでも安定して動作するクリーンなターミナル出力。

### 自律型エージェントのツール実行
AIがファイル操作、Web検索、Python実行などのツールを自律的に使用し、複雑なタスクを遂行します。Web検索はLLMプロバイダーの機能（Gemini Grounding, OpenAI/Claude Web Search）または Brave Search API を直接利用するため、精度の高い情報と出典（引用）の確認が可能です。

<p align="center">
  <img src="https://raw.githubusercontent.com/yosh95/llm-cli/main/images/screenshot-tool-calling.png" width="800" alt="自律型エージェントのツール実行" />
</p>

## セキュリティとガバナンス (プロフェッショナル向け)

本ツールは **CISSP/CISA/CCSP** の各ドメインにおける管理策、および **EU AI Act（欧州AI法）** の技術的要件を意識して設計されています。

### 1. 属性ベースアクセス制御 (ABAC)
`llm-cli` は、実行コンテキストとリソース属性に基づいた **属性ベースアクセス制御 (ABAC)** を採用し、高度に粒度の細かいセキュリティを実現しています。
- **リスクベース・スケーリング**: ツールのリスクレベル（HIGH/MEDIUM/LOW）に応じて、要求されるセキュリティ強度が自動的に変化します。
- **意図の検証 (Dual LLM)**: 高リスクな操作は、軽量な「検証用LLM」（例：Gemini Flash Lite）によって元のプロンプトと照合されます。これにより、高度なプロンプトインジェクションによる意図しない操作を動的に防止します。
- **バックグラウンド実行**: 検証はユーザーが説明文を確認して承認（HITL）を行う裏で非同期に実行されます。これにより、高度な検証に伴う待機時間を最小化し、ストレスのない操作感を実現しています。
- **アイデンティティ証明**: 高リスクな操作（Python実行など）には、**耐量子暗号 (PQC)** による署名付き証明が必要です。
- **互換モード**: `LLM_CLI_SECURITY_LEVEL=standard` を環境変数で設定するか、`config.toml` 内で `security_level = "standard"` を設定することで、PQC非対応のクライアントやサーバーとの相互運用を許可し、整合性チェックのエラーを警告表示のみにダウングレードします。
  ```toml
  [security]
  security_level = "standard"
  ```
- **AST静的解析**: 全てのPythonスクリプトは実行前に解析され、危険なモジュール（`os.system`, `base64`, `socket`等）やリフレクション攻撃、さらに**難読化されたキーワード構築**（例：`"ex" + "ec"`）を遮断します。
- **パス・ガードレール**: 操作可能な範囲を属性（ディレクトリ・パスなど）で制限します。

### 2. アイデンティティと非否認性 (実験的参照実装)
- **分散型トラストモデル**: クライアントとサーバーが公開鍵のみを交換する分散型アイデンティティモデルを実装。特定のコンポーネントが侵害された際の横展開を防止する手法を探求していますが、エンタープライズ領域での利用には十分な評価が必要です。
- **ハイブリッド署名**: **COSE (RFC 9052)** を採用し、**RS256** と **耐量子暗号 (ML-DSA)** を組み合わせた署名を実装。将来的な非否認性の確保に向けた参照実装としての位置づけです。
- **完全性検証**: クライアント自身のソースコードの状態を署名付きマニフェストで証明し、実行環境の健全性を担保します。
- **双方向検証**: ツールの実行結果に署名を付与し、受信側がデータの正当性をプロトコルの範囲内で検証可能です。

### 3. 観測可能性と監査ログ (Tier 3 参照実装)
- **改ざん防止監査ログ**: ハッシュ連鎖（Chained Hashing）によるログ保護と、**ML-KEM (Kyber)** による機密性保護を実装しています。
- **Merkle Tree アンカリング**: Tier 3 実装として Merkle Tree によるログバッチの固定を導入。履歴の改ざんを防止し、セッションの整合性を証明するアーキテクチャのプロトタイプです。

###  高度なコマンドとパワーユーザー向け機能

インタラクティブセッション内で利用可能なコマンド:
- `/help`: 利用可能なすべてのコマンドを表示。
- `/p <provider>` / `/m <model>`: プロバイダーやモデルを動的に切り替え。
- `/attach <path/URL>`: ファイルやウェブサイトのコンテンツをコンテキストに追加。
- `/tools on|off`: ツールの自律実行を有効化/無効化。
- `/i`: セッションの整合性とセキュリティステータスを表示。
- `/save` / `/load`: 会話履歴を保存・読み込み。
- `/cp`: チェックポイント (会話の要約と履歴のクリア)。
- `/mcp`: MCP サーバー連携の切り替えと管理。

###  ログとトラブルシューティング
デフォルトでは、`llm-cli` およびその関連ツールは、`WARNING` または `ERROR` メッセージのみを表示し、情報のログは表示されません。
- **デバッグモードの有効化**: ツールの実行時に `--debug` フラグを追加して、詳細なログを表示します。
  ```bash
  llm-cli --debug "query"
  llm-cli-security --debug verify
  ```
- **MCP のデバッグ**: 3rdパーティのクライアント（Claude Desktop 等）から起動される MCP サーバーのトラブルシューティングには、`MCP_DEBUG` 環境変数を使用します。
  ```bash
  export MCP_DEBUG=1
  # その後、お使いの MCP クライアントを起動してください。
  ```
- **ログの場所**: セキュリティおよび監査ログは `~/.llm_cli/audit.jsonl` に保存されています。

### パワーユーザー向け機能
- **一時中断 (`Ctrl+Z`)**: セッションをバックグラウンドに送り、シェルに戻る。`fg` で復帰可能。
- **外部エディタ編集 (`Ctrl+X, Ctrl+E`)**: プロンプト入力を `vim` や `nano` で編集。
- **テンプレート**: 頻繁に使うプロンプトを `~/.llm_cli/config.toml` に定義し、`/t <名前>` で呼び出し。
- **モデルごとのツール自動無効化**: 画像生成モデルなど、ツール利用に対応していないモデルに対して、`config.toml` で自動的にツール機能をオフに設定できます。
  ```toml
  [google.models]
  image = { model = "gemini-1.5-flash-image-preview", tools = false }
  ```
- **ツール機能の手動無効化**: `/tools off` コマンドでツール送信を一時的に無効化できます。

---

##  ライセンス
[Apache License 2.0](LICENSE) に基づき公開されています。技術的な詳細については [テクニカルレポート](paper/comprehensive_framework/paper.pdf) を参照してください。
