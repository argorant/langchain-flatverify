.PHONY: test integration_tests lint format type build check publish

test:
	uv run --group test pytest --disable-socket --allow-unix-socket tests/unit_tests/

integration_tests:
	uv run --group test pytest --disable-socket --allow-unix-socket tests/integration_tests/

lint:
	uv run --group lint ruff check .
	uv run --group lint ruff format --diff .

format:
	uv run --group lint ruff format .
	uv run --group lint ruff check --fix .

type:
	uv run --group typing --group test mypy langchain_flatverify tests

build:
	rm -rf dist && uv build

check: build
	uvx twine check --strict dist/*

publish:
	uv run --with twine twine upload dist/*
