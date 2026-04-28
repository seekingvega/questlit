# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

QuestLit is intended to be a Streamlit web app for sharing a portfolio and visualizing trades and the equity curve (per `README.md`). The repo is currently a stub: `main.py` is a `print("Hello from questlit!")` placeholder, `pyproject.toml` declares no dependencies, and there is no Streamlit code, tests, or app structure yet. When asked to add functionality, expect to be scaffolding from scratch rather than fitting into an existing architecture.

## Tooling

- Python `>=3.10` (pinned to `3.10` via `.python-version`).
- The combination of `pyproject.toml` + `.python-version` + ignored `.venv` is the [`uv`](https://docs.astral.sh/uv/) layout. Prefer `uv` for dependency and environment management:
  - `uv sync` — create/update the venv from `pyproject.toml`.
  - `uv add <pkg>` — add a runtime dependency (e.g. `uv add streamlit`).
  - `uv run <cmd>` — run a command inside the project venv (e.g. `uv run python main.py`, or once Streamlit is added, `uv run streamlit run main.py`).
- There is no test runner, linter, or build configured yet. If you add one, record the invocation here.

## Guidelines

- Create tests in `tests/` and update CLAUDE.md for each new feature
- use Google-style docstring for new functions and add a doctest compatible unit test if possible
- keep code modular to ensure ease in future refactoring
- Prefer native Streamlit features over custom CSS
- Keep custom CSS minimal
