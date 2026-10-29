install:
	uv sync --locked

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

test:
	uv run pytest tests/unit

test-verbose:
	uv run --locked pytest tests/unit -vv --capture=tee-sys --tb=long

test-integration:
	uv run --locked pytest tests/integration -m integration -ra

format-check:
	uv run --locked ruff format --check .

check: lint format-check typecheck test

