SHELL := /bin/bash

UV ?= uv
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help venv install install-dev test lint format check clean build

help:
	@echo "Setup:"
	@echo "  venv         Create virtualenv with uv in $(VENV)"
	@echo "  install      Install package (production) into venv"
	@echo "  install-dev  Install package + dev dependencies into venv"
	@echo ""
	@echo "Development:"
	@echo "  test                    Run entire test suite with coverage"
	@echo "  lint                    Lint code with ruff"
	@echo "  format                  Format code with ruff"
	@echo "  check                   Run lint and test"
	@echo ""
	@echo "Maintenance:"
	@echo "  build        Build source and wheel distributions"
	@echo "  clean        Remove build artifacts and venv"

venv:
	$(UV) venv $(VENV)

install: venv
	$(UV) pip install -e .

install-dev: venv
	$(UV) pip install -e ".[dev]"

test:
	$(UV) run --extra dev pytest --cov=jsonflux

lint:
	$(UV) run --extra dev ruff check src/ tests/

format:
	$(UV) run --extra dev ruff format src/ tests/

check: lint test

build:
	$(UV) build

clean:
	rm -rf $(VENV) build dist *.egg-info .pytest_cache .coverage coverage.xml htmlcov .ruff_cache
