"""QuestLit CLI: view current positions and inspect cached token state."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import typer
from loguru import logger

from questlit.questrade import QuestradeClient

logger.remove()
logger.add(sys.stderr, format="<level>{message}</level>", level="INFO")

app = typer.Typer(
    help="QuestLit CLI — view positions and inspect Questrade token state.",
    no_args_is_help=True,
)


def _prompt_for_refresh_token() -> str:
    return typer.prompt(
        "Paste a fresh Questrade refresh token "
        "(generate at My Apps → Personal Apps: "
        "https://apphub.questrade.com/UI/UserApps.aspx)",
        hide_input=True,
    )


@app.command()
def positions() -> None:
    """Print current positions across all Questrade accounts."""
    client = QuestradeClient(prompt_callback=_prompt_for_refresh_token)
    rows = client.get_all_positions()
    if not rows:
        logger.info("No open positions.")
        return
    df = pd.DataFrame(rows)
    logger.info("\n" + df.to_string(index=False))


def _parse_start_date(value: str | None) -> datetime | None:
    """Parse a YYYY-MM-DD string as 00:00:00 local time."""
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").astimezone()


def _parse_end_date(value: str | None) -> datetime | None:
    """Parse a YYYY-MM-DD string as 23:59:59 local time."""
    if value is None:
        return None
    return (
        datetime.strptime(value, "%Y-%m-%d")
        .replace(hour=23, minute=59, second=59)
        .astimezone()
    )


@app.command()
def orders(
    account: str = typer.Argument(..., help="Questrade account number."),
    start: str | None = typer.Option(
        None, "--start", help="Start date YYYY-MM-DD (00:00:00 local time)."
    ),
    end: str | None = typer.Option(
        None, "--end", help="End date YYYY-MM-DD (23:59:59 local time)."
    ),
    state: str | None = typer.Option(
        None, "--state", help="State filter: All, Open, or Closed."
    ),
) -> None:
    """Print orders for a Questrade account (defaults to active orders)."""
    client = QuestradeClient(prompt_callback=_prompt_for_refresh_token)
    rows = client.get_orders(
        account,
        start_time=_parse_start_date(start),
        end_time=_parse_end_date(end),
        state_filter=state,
    )
    if not rows:
        logger.info("No orders.")
        return
    df = pd.DataFrame(rows)
    logger.info("\n" + df.to_string(index=False))


@app.command()
def activities(
    account: str = typer.Argument(..., help="Questrade account number."),
    start: str | None = typer.Option(
        None,
        "--start",
        help="Start date YYYY-MM-DD (00:00:00 local). Defaults to 30 days ago.",
    ),
    end: str | None = typer.Option(
        None,
        "--end",
        help="End date YYYY-MM-DD (23:59:59 local). Defaults to today.",
    ),
) -> None:
    """Print account activities, auto-chunked across windows >30 days."""
    today = date.today()
    start = start or (today - timedelta(days=30)).isoformat()
    end = end or today.isoformat()

    client = QuestradeClient(prompt_callback=_prompt_for_refresh_token)
    rows = client.get_activities(
        account,
        start_time=_parse_start_date(start),
        end_time=_parse_end_date(end),
    )
    if not rows:
        logger.info("No activities.")
        return
    df = pd.DataFrame(rows)
    logger.info("\n" + df.to_string(index=False))


@app.command()
def token() -> None:
    """Show when the cached access token expires (does not refresh)."""
    info = QuestradeClient().token_info()
    if not info or not info.get("expires_at"):
        logger.warning(
            "No cached token. Run `uv run python main.py positions` to seed one."
        )
        raise typer.Exit(code=1)

    expires_at_epoch = info["expires_at"]
    now_epoch = datetime.now(tz=timezone.utc).timestamp()
    delta = expires_at_epoch - now_epoch
    expires_at = datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc)

    if delta <= 0:
        logger.warning(
            f"Access token expired {int(-delta)}s ago "
            f"(at {expires_at.isoformat()})."
        )
    else:
        mins, secs = divmod(int(delta), 60)
        logger.info(
            f"Access token expires in {mins}m {secs}s "
            f"(at {expires_at.isoformat()})."
        )
    logger.info(f"API server: {info.get('api_server')}")


if __name__ == "__main__":
    app()
