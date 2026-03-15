default:
    @just --list

install:
    uv sync --all-extras

test *args:
    uv run pytest {{args}}

run:
    uv run python main.py

lint:
    uv run ruff check src/ tests/

format:
    uv run ruff format src/ tests/

fmt: format lint

typecheck:
    uv run ty check
