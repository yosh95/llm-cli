.PHONY: help install lint format test clean

# Default target
help:
	@echo "Available commands:"
	@echo "  make install  - Install dependencies"
	@echo "  make lint     - Run linter (ruff, mypy)"
	@echo "  make format   - Run formatter (ruff)"
	@echo "  make test     - Run tests with coverage"
	@echo "  make clean    - Remove temporary files and caches"

install:
	pip install -e ".[dev,test]"

lint:
	ruff check .
	mypy .

format:
	ruff format .

test:
	pytest --cov=llm_cli tests/

clean:
	@echo "Cleaning up..."
	rm -rf .ruff_cache/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[co]" -delete
	find . -type f -name "*$py.class" -delete
	@echo "Clean completed."
