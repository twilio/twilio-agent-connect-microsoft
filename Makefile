.PHONY: help sync dev-setup format lint type-check test check clean docs docs-serve docs-versions

# Include local customizations (optional)
-include Makefile.local

help:
	@echo "TAC Microsoft Development Commands:"
	@echo "  make sync        - Install dependencies (uses uv)"
	@echo "  make dev-setup   - Complete dev environment setup"
	@echo "  make format      - Format code with ruff"
	@echo "  make lint        - Run linting checks only"
	@echo "  make type-check  - Run mypy type checking"
	@echo "  make test        - Run pytest"
	@echo "  make check       - Run all checks (lint + type-check + test)"
	@echo "  make docs        - Build the API documentation into site/"
	@echo "  make docs-serve  - Serve the docs locally with live reload"
	@echo "  make clean       - Clean build artifacts"

sync:
	uv sync --all-extras

dev-setup: sync
	@echo "Development environment ready!"

format:
	@echo "Formatting code with ruff..."
	uv run ruff format src getting_started tests deploy
	uv run ruff check --fix src getting_started tests deploy

lint:
	@echo "Running lint checks..."
	uv run ruff check src getting_started tests deploy
	uv run ruff format --check src getting_started tests deploy

type-check:
	@echo "Running mypy type checking..."
	MYPYPATH=src uv run mypy --explicit-package-bases src/tac_microsoft getting_started deploy

test:
	@echo "Running tests..."
	uv run pytest

check: lint type-check test
	@echo "All checks passed!"

docs:
	@echo "Building documentation into site/ (--strict: warnings fail the build)..."
	uv run --group docs mkdocs build --strict

docs-serve:
	@echo "Serving docs at http://127.0.0.1:8000 (live reload)..."
	uv run --group docs mkdocs serve

docs-versions:
	uv run --group docs mike list

clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "Clean complete!"
