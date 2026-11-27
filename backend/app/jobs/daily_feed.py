"""
Daily job feed — command-line entry point.

    cd backend && python -m app.jobs.daily_feed

Adds up to DAILY_FEED_PER_USER (default 5) new postings to every user's
Postings list. Safe to run more than once a day: a second run the same UTC
day adds nothing. Scheduled by .github/workflows/daily-jobs.yml.
"""
import asyncio
import json
import logging
import sys

from app.database import init_db
from app.database.connection import async_session, engine
from app.services.apply.daily_feed import run_daily_feed


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    await init_db()  # same as app startup: creates any missing tables
    try:
        summary = await run_daily_feed(async_session)
    finally:
        await engine.dispose()
    print(json.dumps(summary, indent=2))
    # Fail the run (so it shows red in GitHub) only if no board could be read at all.
    return 1 if summary.get("candidates", 0) == 0 and not summary.get("skipped") else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
