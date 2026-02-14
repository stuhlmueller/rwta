.PHONY: lint format typecheck test check

lint:
	uv run ruff check --fix src tests

format:
	uv run ruff format src tests

typecheck:
	uv run pyright

test:
	uv run python -m pytest

check: lint format typecheck test
