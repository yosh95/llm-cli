# TechRxiv Submission: Zero-Trust Architecture for MCP-Based AI Agents

This directory contains the final artifacts for the paper submission.

## Files

- `llm_cli_zero_trust.pdf`: The compiled PDF of the paper.
- `llm_cli_zero_trust.tex`: The LaTeX source code.
- `architecture_zt.tex`: TikZ code for the architecture diagram (included by the main file).

## Compilation Instructions

To compile the paper from source, ensure you have a standard LaTeX distribution (like TeX Live) installed.

Run the following command in this directory:

```bash
pdflatex llm_cli_zero_trust.tex
```

(Run it twice to resolve cross-references).

## Dependencies

- `IEEEtran.cls`: The IEEE Transactions class file (standard in most TeX distributions).
- `tikz`: For diagrams.
- `listings`: For code snippets.

## Abstract

This paper introduces a Zero Trust architecture for AI agents using the Model Context Protocol (MCP). We present a unified CLI (`llm-cli`) that enforces intent verification before tool execution. Our evaluation compares cloud-based verifiers (OpenAI, Anthropic, Google, xAI) against local models, highlighting the "Alignment Paradox" where some models prioritize user instruction over safety policies.
