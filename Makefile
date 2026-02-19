.PHONY: help install format lint type-check test all

# Default target
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  install      Install dependencies"
	@echo "  format       Run code formatters (ruff)"
	@echo "  lint         Run linters (ruff)"
	@echo "  type-check   Run type checker (mypy)"
	@echo "  test         Run tests (pytest)"
	@echo "  all          Run format, lint, type-check, and test"

install:
	pip install -e ".[dev]"
	pre-commit install

format:
	ruff format .

lint:
	ruff check . --fix

type-check:
	mypy .

test:
	pytest

# Run everything in the correct order
all: format lint type-check test
