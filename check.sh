#!/bin/bash

# ==============================================================================
# Project Integrity & Quality Check Script
# ==============================================================================
#
# WHY NOT USE MAKEFILE?
# --------------------
# While a Makefile exists for traditional development, this script is preferred
# for automated checks and AI-assisted development for the following reasons:
#
# 1. SECURITY (AI Agent Safety): 
#    'make' is a powerful macro language that allows variable overrides and
#    hidden shell executions (e.g., `make VAR='$(shell command)'`). This creates
#    a large attack surface for command injection that is difficult to validate
#    strictly in a shell command whitelist.
#
# 2. TRANSPARENCY:
#    This script performs explicit, sequential steps that are easy for both
#    humans and AI security validators to parse and verify.
#
# 3. PREDICTABILITY:
#    Ensures that formatting, linting, type-checking, and testing always run in 
#    the exact same order with the exact same flags, without being affected by
#    environment variables or Makefile overrides.
#
# ==============================================================================

set -e  # Exit immediately if a command exits with a non-zero status.

echo "🎨 Running code formatters (ruff)..."
ruff format .

echo "🔍 Running linters (ruff)..."
ruff check . --fix

echo "🛡️  Running type checker (mypy)..."
mypy .

echo "🧪 Running tests (pytest)..."
pytest

echo "✅ All checks passed successfully!"
