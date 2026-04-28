"""QuestLit CLI: view current positions and inspect cached token state."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pandas as pd
import typer
from dotenv import load_dotenv
from loguru import logger

from questlit.questrade import QuestradeClient

load_dotenv()

logger.remove()
logger.add(sys.stderr, format="<level>{message}</level>", level="INFO")

app = typer.Typer(
    help="QuestLit CLI — view positions and inspect Questrade token state.",
    no_args_is_help=True,
)


@app.command()
def positions() -> None:
    """Print current positions across all Questrade accounts."""
    rows = QuestradeClient().get_all_positions()
    if not rows:
        logger.info("No open positions.")
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
