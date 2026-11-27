"""Daily job feed: 5 new, non-repeating postings per user per day."""
import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.models.apply import ApplyPosting
from app.services.apply import daily_feed
from app.services.apply.fetcher import SafeFetcher
from app.services.apply.service import Services
from tests.apply_fixtures import PROFILE
from tests.conftest import test_session

BODY = (
    "<p>We build software used by teams around the world and value careful engineering, clear "
    "writing and strong ownership of production systems. You will work with Python, PostgreSQL, "
    "AWS and Docker on services that matter to our customers every day.</p>"
)


def _gh_board(prefix: int, titles: list[tuple[str, str]], start_day: int = 1) -> dict:
    return {
        "jobs": [
            {
                "id": prefix * 1000 + i,
                "title": title,
                "location": {"name": loc},
                "absolute_url": f"https://boards.greenhouse.io/b{prefix}/jobs/{i}",
                "updated_at": f"2026-11-{start_day + i:02d}T10:00:00Z",
                "content": f"{BODY}<p>Role {prefix}-{i}: {title}.</p>",
            }
            for i, (title, loc) in enumerate(titles)
        ]
    }


BOARDS = {
    "alpha": _gh_board(1, [("Backend Engineer", "Remote"), ("Sales Lead", "London"), ("Backend Engineer II", "San Francisco")]),
    "beta": _gh_board(2, [("Senior Backend Engineer", "Remote - US"), ("Designer", "Berlin")]),
    "gamma": _gh_board(3, [("Data Analyst", "Paris"), ("Recruiter", "Austin"), ("Backend Engineer", "Tokyo")]),
}


def _services(boards=BOARDS, fail=()):
    def handler(request):
        token = request.url.path.split("/")[3]
        if token in fail:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(boards[token]).encode())

    async def resolver(host):
        return ["93.184.216.34"]

    return Services(fetcher=SafeFetcher(resolver=resolver, transport=httpx.MockTransport(handler)))


def _use_boards(monkeypatch, tokens=("alpha", "beta", "gamma")):
    monkeypatch.setattr(settings, "DAILY_FEED_BOARDS", ",".join(f"greenhouse:{t}:{t.title()}" for t in tokens))


async def _postings(email_client=None):
    async with test_session() as db:
        return list((await db.execute(select(ApplyPosting).order_by(ApplyPosting.id))).scalars().all())


async def test_adds_five_new_postings_once_per_day(auth_client, monkeypatch):
    _use_boards(monkeypatch)
    summary = await daily_feed.run_daily_feed(test_session, _services())
    assert summary["users"] == 1 and summary["postings_added"] == 5 and summary["board_errors"] == {}
    rows = await _postings()
    assert len(rows) == 5
    assert all(r.discovery_source_id is None and r.source_type == "greenhouse" for r in rows)
    assert len({r.company for r in rows}) == 3  # spread across companies

    again = await daily_feed.run_daily_feed(test_session, _services())
    assert again["postings_added"] == 0 and len(await _postings()) == 5

    # They show up in the normal Postings API, unchanged shape.
    api = (await auth_client.get("/api/apply/postings")).json()["data"]
    assert len(api) == 5 and {"title", "company", "fit_score", "listing_url"} <= set(api[0])


async def test_next_day_adds_different_postings(auth_client, monkeypatch):
    _use_boards(monkeypatch)
    services = _services()
    candidates, _ = await daily_feed.collect_candidates(services, daily_feed.configured_boards())
    async with test_session() as db:
        from app.models import User

        user = (await db.execute(select(User))).scalar_one()
        day1 = datetime(2026, 11, 27, 9, tzinfo=timezone.utc)
        first = await daily_feed.add_daily_postings(db, user, candidates, services, now=day1)
        await db.commit()
        second = await daily_feed.add_daily_postings(db, user, candidates, services, now=day1 + timedelta(days=1))
        await db.commit()
    assert len(first) == 5 and len(second) == 3  # only 8 openings exist; nothing repeats
    rows = await _postings()
    assert len({(r.source_type, r.source_job_id) for r in rows}) == 8


async def test_profile_roles_and_locations_come_first(auth_client, monkeypatch):
    _use_boards(monkeypatch)
    await auth_client.put("/api/apply/profile", json={**PROFILE, "target_roles": ["Backend Engineer"]})
    await daily_feed.run_daily_feed(test_session, _services())
    titles = [r.title for r in await _postings()]
    # 4 Backend roles exist: 3 match San Francisco/remote, then Tokyo matches the role only.
    assert sum("Backend" in t for t in titles) == 4


async def test_broken_boards_are_skipped(auth_client, monkeypatch):
    _use_boards(monkeypatch)
    summary = await daily_feed.run_daily_feed(test_session, _services(fail=("beta",)))
    assert list(summary["board_errors"]) == ["greenhouse:beta"]
    assert summary["postings_added"] == 5


async def test_every_user_gets_their_own_feed(make_client, monkeypatch):
    _use_boards(monkeypatch)
    await make_client("a@example.com")
    await make_client("b@example.com")
    summary = await daily_feed.run_daily_feed(test_session, _services())
    assert summary["users"] == 2 and summary["postings_added"] == 10


async def test_respects_disable_switch_count_and_cap(auth_client, monkeypatch):
    _use_boards(monkeypatch)
    monkeypatch.setattr(settings, "DAILY_FEED_ENABLED", False)
    assert (await daily_feed.run_daily_feed(test_session, _services()))["postings_added"] == 0
    monkeypatch.setattr(settings, "DAILY_FEED_ENABLED", True)
    monkeypatch.setattr(settings, "APPLY_MAX_POSTINGS_PER_USER", 2)
    assert (await daily_feed.run_daily_feed(test_session, _services()))["postings_added"] == 2


async def test_board_setting_parsing(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_FEED_BOARDS", "greenhouse:figma:Figma, bogus, workday:x:X,lever:plaid:Plaid")
    boards = daily_feed.configured_boards()
    assert [(b.provider.value, b.token, b.company) for b in boards] == [
        ("greenhouse", "figma", "Figma"), ("lever", "plaid", "Plaid"),
    ]
    monkeypatch.setattr(settings, "DAILY_FEED_BOARDS", "")
    assert len(daily_feed.configured_boards()) == len(daily_feed.DEFAULT_BOARDS)
