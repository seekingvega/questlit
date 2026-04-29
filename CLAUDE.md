# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

QuestLit is a Streamlit web app for sharing a portfolio and visualizing trades and the equity curve (per `README.md`). Current state:
- `streamlit_app.py` — slim entrypoint: runs the auth gate then dispatches to pages via `st.navigation`.
- `pages/dashboard.py` — single page hosting the existing tabs (Positions / Orders / Activities / Balance). New feature pages (PnL, equity curve, etc.) get added here as additional `st.Page(...)` entries in `streamlit_app.py`.
- `questlit/ui/` — Streamlit-only helpers: `auth.py` (seed-token gate), `data.py` (cached loaders), `formatting.py` (dataframe column-config helpers).
- `main.py` — Typer CLI with `positions`, `accounts`, `orders`, `activities`, and `token` subcommands, backed by the same `questlit/questrade.py` client.
- No equity-curve / trade-visualization code yet — still to be scaffolded.

## Tooling

- Python `>=3.10` (pinned to `3.10` via `.python-version`).
- The combination of `pyproject.toml` + `.python-version` + ignored `.venv` is the [`uv`](https://docs.astral.sh/uv/) layout. Prefer `uv` for dependency and environment management:
  - `uv sync` — create/update the venv from `pyproject.toml`.
  - `uv add <pkg>` — add a runtime dependency (e.g. `uv add streamlit`).
  - `uv run <cmd>` — run a command inside the project venv. Common ones:
    - `uv run streamlit run streamlit_app.py` — start the Streamlit app.
    - `uv run python main.py --help` — discover CLI subcommands.
    - `uv run python main.py positions` — print current positions to terminal.
    - `uv run python main.py accounts` — print the list of Questrade accounts (handy for grabbing an account number for `orders` / `activities`).
    - `uv run python main.py orders <ACCOUNT> [--start YYYY-MM-DD --end YYYY-MM-DD --state All|Open|Closed]` — print orders for one account; `--start` is 00:00:00 local, `--end` is 23:59:59 local.
    - `uv run python main.py activities <ACCOUNT> [--start YYYY-MM-DD --end YYYY-MM-DD]` — print activities; defaults to last 30 days (start at 00:00:00 local, end at 23:59:59 local). Auto-chunks >30-day windows.
    - `uv run python main.py token` — show cached access token expiry (no refresh).
    - `uv run pytest` — run the test suite (configured via `[tool.pytest.ini_options]` in `pyproject.toml`).

## Modules

- `questlit/questrade.py` — `QuestradeClient` for the Questrade REST API. Handles the OAuth refresh-token rotation (Questrade tokens are single-use) by persisting the rotated token to `~/.questlit/token.json`. First-time setup: run `uv run python main.py positions` — when no token is cached you'll be prompted to paste a refresh token from the Questrade portal (My Apps → Personal Apps). The same prompt fires automatically if the cached refresh token has expired (~7 days idle, Questrade returns 400 `invalid_grant`).
  - Public surface: `get_accounts()`, `get_positions(account_id)`, `get_all_positions()` (latter tags each row with `accountNumber` / `accountType`), `get_balances(account_id)` (returns the full Questrade payload — four sibling lists: `perCurrencyBalances`, `combinedBalances`, plus their start-of-day counterparts), `get_all_balances()` (flattens `perCurrencyBalances` across accounts and tags each row with `accountNumber` / `accountType`), `get_orders(account_id, start_time=None, end_time=None, state_filter=None)` (unopinionated pass-through; no params → Questrade default of active orders), `get_activities(account_id, start_time=None, end_time=None)` (defaults to last 30 days; auto-chunks longer windows into ≤30-day calls under the hood since Questrade rejects >31-day ranges), `token_info()` (read-only: returns the persisted token dict without triggering a refresh — used by the CLI's `token` subcommand).
  - Constructor accepts `prompt_callback: Callable[[], str] | None` for the interactive seed path and `seed_refresh_token: str | None` for programmatic use. The CLI wires `prompt_callback` to `typer.prompt(..., hide_input=True)`. `questlit/ui/auth.py` catches `QuestradeAuthError` / `HTTPError 400` and renders an inline `st.text_input(type="password")` form, stashing the entered seed in `st.session_state["pending_seed"]` for one rerun before passing it to `QuestradeClient(seed_refresh_token=...)`.
- `questlit/ui/auth.py` — `ensure_authenticated()` returns the validated accounts list and stashes it in `st.session_state["accounts"]`; pages read from there instead of refetching. Renders the seed form + `st.stop()` on auth failure.
- `questlit/ui/data.py` — `@st.cache_data` loaders (`load_accounts`, `load_positions`, `load_balances`, `load_orders`, `load_activities`). TTL is 1 day for accounts, 60s for the rest. Pages must import from this module so caches are shared app-wide.
- `questlit/ui/formatting.py` — `currency_column_config(df)` builds a `st.column_config.NumberColumn(format="$%.2f")` mapping for every numeric column in `df`. Reuse for any dollar-denominated table.
- The CLI (`main.py`) uses **Typer** for command parsing and **Loguru** for output — `logger.remove()` + a minimal `<level>{message}</level>` format keep CLI output print-like while preserving level coloring. Prefer `logger.info` / `logger.warning` over `print` / `typer.echo` in CLI code.
- `questlit/` is an implicit namespace package — no `__init__.py`. Same for `questlit/ui/`, `pages/`, and `tests/`.

## Guidelines

- Create tests in `tests/` and update CLAUDE.md for each new feature
- use Google-style docstring for new functions and add a doctest compatible unit test if possible
- keep code modular to ensure ease in future refactoring
- Prefer native Streamlit features over custom CSS
- Keep custom CSS minimal
