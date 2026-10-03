"""API tests for /api/apply — scoping, review binding, discovery, AI fallbacks."""
import asyncio
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app.api import apply as apply_api
from app.core.config import settings
from app.main import app
from app.models import Job
from app.models.apply import ApplyAIUsage, ApplyPackageEvent
from app.services.apply.fetcher import SafeFetcher
from app.services.apply.service import Services
from tests.apply_fixtures import GREENHOUSE_BOARD, INJECTED_POSTING, POSTING, PROFILE, RESUME
from tests.conftest import OfflineFetcher


async def _setup_candidate(client):
    r = await client.put("/api/apply/profile", json=PROFILE)
    assert r.status_code == 200, r.text
    r = await client.put("/api/apply/resume", json={"text": RESUME})
    assert r.status_code == 200, r.text


async def _posting(client, text=POSTING, **extra):
    r = await client.post("/api/apply/postings", json={"text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()["posting"]


async def _prepared(client, text=POSTING):
    await _setup_candidate(client)
    posting = await _posting(client, text)
    r = await client.post(f"/api/apply/postings/{posting['id']}/prepare")
    assert r.status_code == 201, r.text
    return posting, r.json()


def _use_services(services: Services):
    app.dependency_overrides[apply_api.get_services] = lambda: services


# ------------------------------------------------------------------ basics --

async def test_requires_login(client):
    for method, path in [("get", "/api/apply/postings"), ("get", "/api/apply/profile"),
                         ("post", "/api/apply/postings"), ("get", "/api/apply/packages")]:
        r = await getattr(client, method)(path)
        assert r.status_code == 401, path


async def test_status_reports_ai_and_never_sends(auth_client):
    r = await auth_client.get("/api/apply/status")
    assert r.status_code == 200
    assert r.json()["ai"]["configured"] is False
    assert r.json()["sends_anything"] is False


async def test_kill_switch(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "APPLY_ENABLED", False)
    r = await auth_client.post("/api/apply/postings", json={"text": POSTING})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "apply_disabled"


# ---------------------------------------------------------- profile/resume --

async def test_profile_validation(auth_client):
    r = await auth_client.put("/api/apply/profile", json={**PROFILE, "linkedin_url": "javascript:alert(1)"})
    assert r.status_code == 422
    r = await auth_client.put("/api/apply/profile", json={**PROFILE, "target_roles": ["x"] * 16})
    assert r.status_code == 422
    r = await auth_client.put("/api/apply/profile", json={**PROFILE, "is_admin": True})
    assert r.status_code == 422
    r = await auth_client.put("/api/apply/profile", json=PROFILE)
    assert r.status_code == 200 and r.json()["target_roles"] == ["Backend Engineer"]


async def test_resume_versions_are_kept(auth_client):
    r1 = (await auth_client.put("/api/apply/resume", json={"text": RESUME})).json()
    r2 = (await auth_client.put("/api/apply/resume", json={"text": RESUME})).json()
    assert r1["current"]["version"] == r2["current"]["version"] == 1  # unchanged text → no new version
    r3 = (await auth_client.put("/api/apply/resume", json={"text": RESUME + "\nLanguages\nEnglish"})).json()
    assert r3["current"]["version"] == 2 and len(r3["versions"]) == 2


async def test_resume_upload(auth_client):
    files = {"file": ("cv.txt", RESUME.encode(), "text/plain")}
    r = await auth_client.post("/api/apply/resume/upload", files=files)
    assert r.status_code == 200, r.text
    assert r.json()["current"]["filename"] == "cv.txt"
    bad = {"file": ("cv.pdf", b"%PDF-1.4 not really", "application/pdf")}
    r = await auth_client.post("/api/apply/resume/upload", files=bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unreadable_file"


# ----------------------------------------------------------------- postings --

async def test_posting_intake_analysis_and_match(auth_client):
    posting = await _posting(auth_client)
    assert posting["title"] == "Senior Backend Engineer" and posting["company"] == "Acme Robotics"
    assert posting["fit_score"] is None  # no resume yet
    assert posting["match"]["recommendation"] == "needs_profile"
    assert posting["analysis"]["contacts"][0]["email"] == "jane.doe@acmerobotics.example"
    facts = posting["research"]["verified_facts"]
    assert all(f["source"] == "job posting" for f in facts)
    assert any(f["label"].startswith("About") for f in facts)

    await _setup_candidate(auth_client)
    r = await auth_client.post(f"/api/apply/postings/{posting['id']}/refresh")
    assert r.status_code == 200
    assert 50 <= r.json()["fit_score"] <= 100
    assert set(r.json()["match"]["missing_required"]) == {"Kafka", "Kubernetes"}


async def test_duplicate_postings_are_merged(auth_client):
    first = await _posting(auth_client)
    r = await auth_client.post("/api/apply/postings", json={"text": "  " + POSTING.replace("\n", "\n\n")})
    assert r.status_code == 201
    assert r.json()["created"] is False and r.json()["posting"]["id"] == first["id"]


async def test_posting_validation(auth_client):
    assert (await auth_client.post("/api/apply/postings", json={})).status_code == 422
    r = await auth_client.post("/api/apply/postings", json={"text": "Engineer wanted"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "too_short"


async def test_intake_by_link_uses_the_safe_fetcher(auth_client):
    def handler(request):
        assert request.extensions.get("sni_hostname") == "careers.acme.io"
        if request.url.path == "/":  # the employer homepage, read for company research
            return httpx.Response(200, headers={"content-type": "text/html"}, content=(
                b"<html><head><title>Acme Robotics</title><meta name='description' "
                b"content='Warehouse automation software for logistics teams.'></head><body></body></html>"))
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=("<html><body><pre>" + POSTING + "</pre></body></html>").encode())

    async def resolver(host):
        return {"careers.acme.io": ["93.184.216.34"]}[host]

    _use_services(Services(fetcher=SafeFetcher(resolver=resolver, transport=httpx.MockTransport(handler))))
    r = await auth_client.post("/api/apply/postings", json={"url": "https://careers.acme.io/jobs/42"})
    assert r.status_code == 201, r.text
    p = r.json()["posting"]
    assert p["listing_url"] == "https://careers.acme.io/jobs/42" and p["source_type"] == "url"
    # Company research read the employer's own homepage — every fact names its source.
    site = [f for f in p["research"]["verified_facts"] if f["source"] == "company website"]
    assert {f["label"] for f in site} == {"Website title", "Website description"}
    assert all(f["source_url"] == "https://careers.acme.io/" for f in site)


async def test_intake_link_failures_are_explained(auth_client):
    r = await auth_client.post("/api/apply/postings", json={"url": "https://careers.acme.io/jobs/1"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "fetch_failed"
    r = await auth_client.post("/api/apply/postings", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert r.status_code == 422
    assert OfflineFetcher.calls == ["https://careers.acme.io/jobs/1", "http://169.254.169.254/latest/meta-data"]


async def test_injection_in_posting_is_flagged(auth_client):
    posting = await _posting(auth_client, INJECTED_POSTING)
    assert posting["flagged"] is True
    kinds = {f["kind"] for f in posting["injection_findings"]}
    assert "instruction_override" in kinds


async def test_track_archive_restore(auth_client, db_session):
    posting = await _posting(auth_client)
    r1 = await auth_client.post(f"/api/apply/postings/{posting['id']}/track")
    r2 = await auth_client.post(f"/api/apply/postings/{posting['id']}/track")
    assert r1.status_code == 200 and r1.json()["tracked_job_id"] == r2.json()["tracked_job_id"]
    job = (await db_session.execute(select(Job).where(Job.id == r1.json()["tracked_job_id"]))).scalar_one()
    assert (job.company, job.position, job.status, job.salary_min) == ("Acme Robotics", "Senior Backend Engineer", "saved", 150000)

    await auth_client.post(f"/api/apply/postings/{posting['id']}/archive")
    active = (await auth_client.get("/api/apply/postings")).json()
    archived = (await auth_client.get("/api/apply/postings", params={"status": "archived"})).json()
    assert active["total"] == 0 and archived["total"] == 1
    await auth_client.post(f"/api/apply/postings/{posting['id']}/restore")
    assert (await auth_client.get("/api/apply/postings")).json()["total"] == 1


# ------------------------------------------------------------------- IDOR --

async def test_users_cannot_touch_each_others_data(make_client):
    alice = await make_client("alice@example.com")
    bob = await make_client("bob@example.com")
    posting, package = await _prepared(alice)
    src = await alice.post("/api/apply/sources", json={"provider": "greenhouse", "board_token": "acme", "company_name": "Acme"})
    sid = src.json()["id"]
    pid, kid, h = posting["id"], package["id"], package["payload_hash"]

    attempts = [
        ("get", f"/api/apply/postings/{pid}", None),
        ("post", f"/api/apply/postings/{pid}/refresh", None),
        ("post", f"/api/apply/postings/{pid}/track", None),
        ("post", f"/api/apply/postings/{pid}/archive", None),
        ("post", f"/api/apply/postings/{pid}/prepare", None),
        ("get", f"/api/apply/packages/{kid}", None),
        ("patch", f"/api/apply/packages/{kid}", {"base_hash": h, "edits": {"cover_letter": "pwned"}}),
        ("post", f"/api/apply/packages/{kid}/approve", {"payload_hash": h}),
        ("post", f"/api/apply/packages/{kid}/reject", {}),
        ("post", f"/api/apply/packages/{kid}/mark-sent", {}),
        ("post", f"/api/apply/sources/{sid}/run", None),
        ("delete", f"/api/apply/sources/{sid}", None),
    ]
    for method, path, body in attempts:
        kwargs = {"json": body} if body is not None else {}
        r = await getattr(bob, method)(path, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)

    assert (await bob.get("/api/apply/postings")).json()["total"] == 0
    assert (await bob.get("/api/apply/packages", params={"status": "all"})).json()["data"] == []
    assert (await bob.get("/api/apply/sources")).json()["data"] == []
    # Alice's package is untouched.
    assert (await alice.get(f"/api/apply/packages/{kid}")).json()["status"] == "ready_for_review"


# ----------------------------------------------------------------- review --

async def test_prepare_requires_a_resume(auth_client):
    posting = await _posting(auth_client)
    r = await auth_client.post(f"/api/apply/postings/{posting['id']}/prepare")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "resume_required"


async def test_prepared_package_contents(auth_client):
    _, package = await _prepared(auth_client)
    payload = package["payload"]
    assert set(payload) == {"what", "who", "account", "data", "attachments", "job"}
    assert "Nothing is sent" in payload["what"]
    assert payload["account"]["type"] == "manual"
    assert payload["who"]["contact"]["email"] == "jane.doe@acmerobotics.example"
    assert payload["data"]["email"]["to"] == "jane.doe@acmerobotics.example"
    assert "Kafka" not in payload["data"]["resume_text"]
    assert all(r["ok"] for r in package["guard"].values())
    assert package["generation"]["cover_letter"]["mode"] == "deterministic"
    assert len(package["payload_hash"]) == 64 and package["status"] == "ready_for_review"


async def test_approval_is_bound_to_the_reviewed_content(auth_client, db_session):
    _, package = await _prepared(auth_client)
    kid, h1 = package["id"], package["payload_hash"]

    r = await auth_client.post(f"/api/apply/packages/{kid}/mark-sent", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_approved"
    r = await auth_client.post(f"/api/apply/packages/{kid}/approve", json={"payload_hash": "0" * 64})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "content_changed"

    r = await auth_client.post(f"/api/apply/packages/{kid}/approve", json={"payload_hash": h1})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["final"]["approved_payload_hash"] == h1
    assert r.json()["final"]["delivery"] == "manual"

    # Editing after approval voids it.
    r = await auth_client.patch(f"/api/apply/packages/{kid}", json={
        "base_hash": h1, "edits": {"cover_letter": package["payload"]["data"]["cover_letter"] + "\nP.S. Thanks!"},
    })
    assert r.status_code == 200
    edited = r.json()
    assert edited["approval_voided"] is True and edited["status"] == "ready_for_review"
    h2 = edited["payload_hash"]
    assert h2 != h1 and edited["payload_version"] == 2 and edited["final"] is None

    # The old hash no longer approves; an edit against it is refused too.
    r = await auth_client.post(f"/api/apply/packages/{kid}/approve", json={"payload_hash": h1})
    assert r.status_code == 409
    r = await auth_client.patch(f"/api/apply/packages/{kid}", json={"base_hash": h1, "edits": {"cover_letter": "x" * 30}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"

    r = await auth_client.post(f"/api/apply/packages/{kid}/approve", json={"payload_hash": h2})
    assert r.status_code == 200
    r = await auth_client.post(f"/api/apply/packages/{kid}/approve", json={"payload_hash": h2})
    assert r.status_code == 409  # already approved

    r = await auth_client.post(f"/api/apply/packages/{kid}/mark-sent", json={"channel": "company_site"})
    assert r.status_code == 200 and r.json()["status"] == "sent"
    job = (await db_session.execute(select(Job).where(Job.id == r.json()["tracked_job_id"]))).scalar_one()
    assert job.status == "applied" and job.applied_date is not None

    detail = (await auth_client.get(f"/api/apply/packages/{kid}")).json()
    assert [e["kind"] for e in detail["events"]] == ["created", "approved", "edited", "approved", "marked_sent"]
    assert detail["events"][2]["detail"]["approval_voided"] is True


async def test_edit_rules(auth_client):
    _, package = await _prepared(auth_client)
    kid, h = package["id"], package["payload_hash"]
    r = await auth_client.patch(f"/api/apply/packages/{kid}", json={"base_hash": h, "edits": {"who": "x"}})
    assert r.status_code == 422
    r = await auth_client.patch(f"/api/apply/packages/{kid}", json={"base_hash": h, "edits": {"cover_letter": "   "}})
    assert r.status_code == 422
    r = await auth_client.patch(f"/api/apply/packages/{kid}", json={
        "base_hash": h, "edits": {"answers": [{"index": 99, "answer": "x"}]}})
    assert r.status_code == 422
    # A user edit that claims something the resume doesn't support is allowed but flagged.
    r = await auth_client.patch(f"/api/apply/packages/{kid}", json={
        "base_hash": h, "edits": {"answers": [{"index": 3, "answer": "I hold a PMP certification."}]}})
    assert r.status_code == 200
    assert r.json()["edit_warnings"]
    assert r.json()["payload"]["data"]["answers"][3]["edited_by_you"] is True


async def test_reject_and_reprepare_supersedes(auth_client):
    posting, package = await _prepared(auth_client)
    r = await auth_client.post(f"/api/apply/packages/{package['id']}/reject", json={"reason": "wrong tone"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert (await auth_client.post(f"/api/apply/packages/{package['id']}/approve",
                                   json={"payload_hash": package["payload_hash"]})).status_code == 409

    second = (await auth_client.post(f"/api/apply/postings/{posting['id']}/prepare")).json()
    third = (await auth_client.post(f"/api/apply/postings/{posting['id']}/prepare")).json()
    assert (second["version"], third["version"]) == (2, 3)
    assert (await auth_client.get(f"/api/apply/packages/{second['id']}")).json()["status"] == "superseded"
    open_ids = [p["id"] for p in (await auth_client.get("/api/apply/packages")).json()["data"]]
    assert open_ids == [third["id"]]


async def test_concurrent_approvals_only_one_wins(make_client):
    alice = await make_client("alice2@example.com")
    _, package = await _prepared(alice)
    url = f"/api/apply/packages/{package['id']}/approve"
    body = {"payload_hash": package["payload_hash"]}
    results = await asyncio.gather(alice.post(url, json=body), alice.post(url, json=body))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409], codes


async def test_prepare_is_rate_limited(auth_client, monkeypatch):
    monkeypatch.setattr(apply_api, "prepare_limiter", apply_api.SlidingWindowLimiter(max_calls=2, window_seconds=600))
    await _setup_candidate(auth_client)
    posting = await _posting(auth_client)
    codes = [(await auth_client.post(f"/api/apply/postings/{posting['id']}/prepare")).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


# --------------------------------------------------------------------- AI --

class FakeAI:
    """Stands in for the OpenAI client: returns queued JSON replies, counts calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=300),
        )


HONEST_LETTER = json.dumps({"cover_letter": (
    "Dear Jane Doe,\n\nI'm applying for the Senior Backend Engineer role at Acme Robotics. As a Backend Engineer "
    "with 5 years of experience, I work every day with Python, SQL, PostgreSQL and AWS, which the role calls for. "
    "At Northwind Logistics I built Python microservices on AWS handling 2 million requests per day and migrated "
    "reporting to PostgreSQL, cutting query time by 40%.\n\nI would welcome the chance to discuss the role.\n\n"
    "Sincerely,\nAlex Rivera\nalex@example.com\nhttps://linkedin.com/in/alexr"
)})
FABRICATED_LETTER = json.dumps({"cover_letter": (
    "Dear Jane Doe,\n\nI'm applying for the Senior Backend Engineer role at Acme Robotics. I have 9 years of "
    "Kubernetes and Kafka experience at Google, where I led a team of 40 engineers and hold a PhD in distributed "
    "systems. I am confident I can contribute from day one and would welcome a conversation about the role.\n\n"
    "Sincerely,\nAlex Rivera"
)})
ROLE_SUMMARY = json.dumps({"summary": "A senior backend role building Python microservices on AWS.", "themes": []})


async def test_ai_cover_letter_used_only_when_it_passes_the_guard(auth_client, db_session):
    fake = FakeAI([ROLE_SUMMARY, HONEST_LETTER])
    _use_services(Services(fetcher=OfflineFetcher(), llm_client=fake))
    _, package = await _prepared(auth_client)
    assert package["generation"]["cover_letter"]["mode"] == "llm"
    assert "2 million requests per day" in package["payload"]["data"]["cover_letter"]
    # Untrusted data travels inside a nonce-delimited block, with '<' escaped.
    user_msg = fake.calls[-1]["messages"][1]["content"]
    assert user_msg.startswith("<data-") and "\\u003c" not in user_msg.split("\n", 1)[0]
    usage = (await db_session.execute(select(func.count(ApplyAIUsage.id)))).scalar_one()
    assert usage == 2


async def test_fabricated_ai_draft_is_discarded(auth_client):
    fake = FakeAI([ROLE_SUMMARY, FABRICATED_LETTER])
    _use_services(Services(fetcher=OfflineFetcher(), llm_client=fake))
    _, package = await _prepared(auth_client)
    gen = package["generation"]["cover_letter"]
    assert gen["mode"] == "deterministic" and gen["ai_draft_discarded"] is True
    assert "Google" not in package["payload"]["data"]["cover_letter"]


async def test_malformed_ai_output_and_provider_errors_fall_back(auth_client):
    fake = FakeAI([ROLE_SUMMARY, "not json", '{"wrong": 1}'])
    _use_services(Services(fetcher=OfflineFetcher(), llm_client=fake))
    _, package = await _prepared(auth_client)
    assert package["generation"]["cover_letter"]["mode"] == "deterministic"
    assert "malformed" in package["generation"]["cover_letter"]["ai_unavailable"]

    fake2 = FakeAI([RuntimeError("upstream said sk-secret-123")])
    _use_services(Services(fetcher=OfflineFetcher(), llm_client=fake2))
    posting = await _posting(auth_client, POSTING.replace("Senior", "Staff"))
    r = await auth_client.post(f"/api/apply/postings/{posting['id']}/prepare")
    gen = r.json()["generation"]["cover_letter"]
    assert gen["mode"] == "deterministic" and "sk-secret" not in json.dumps(r.json())


async def test_ai_budget_is_enforced_before_calling(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "APPLY_AI_DAILY_BUDGET_USD", 0.0001)
    fake = FakeAI([])
    _use_services(Services(fetcher=OfflineFetcher(), llm_client=fake))
    _, package = await _prepared(auth_client)
    assert fake.calls == []
    assert "budget" in package["generation"]["cover_letter"]["ai_unavailable"]


async def test_flagged_postings_never_reach_the_ai(auth_client):
    fake = FakeAI([HONEST_LETTER])
    _use_services(Services(fetcher=OfflineFetcher(), llm_client=fake))
    _, package = await _prepared(auth_client, INJECTED_POSTING)
    assert fake.calls == []
    assert "ai_skipped" in package["generation"]["cover_letter"]


# --------------------------------------------------------------- discovery --

def _board_services(board=GREENHOUSE_BOARD):
    seen = []

    def handler(request):
        seen.append(request.headers["host"])
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(board).encode())

    async def resolver(host):
        return ["93.184.216.34"]

    return Services(fetcher=SafeFetcher(resolver=resolver, transport=httpx.MockTransport(handler))), seen


async def test_discovery_imports_matching_postings_once(auth_client):
    services, seen = _board_services()
    _use_services(services)
    await _setup_candidate(auth_client)
    src = (await auth_client.post("/api/apply/sources", json={
        "provider": "greenhouse", "board_token": "acme", "company_name": "Acme", "keywords": ["engineer"]})).json()
    r = await auth_client.post(f"/api/apply/sources/{src['id']}/run")
    assert r.status_code == 200, r.text
    assert (r.json()["found"], r.json()["matched_filters"], r.json()["new_postings"]) == (2, 1, 1)
    assert seen == ["boards-api.greenhouse.io"]
    postings = (await auth_client.get("/api/apply/postings")).json()["data"]
    assert len(postings) == 1 and postings[0]["source_type"] == "greenhouse"
    assert postings[0]["fit_score"] is not None and postings[0]["company"] == "Acme"

    again = (await auth_client.post(f"/api/apply/sources/{src['id']}/run")).json()
    assert again["new_postings"] == 0 and again["already_saved"] == 1


async def test_discovery_cooldown_and_validation(auth_client, monkeypatch):
    services, _ = _board_services()
    _use_services(services)
    bad = await auth_client.post("/api/apply/sources", json={"provider": "greenhouse", "board_token": "../x", "company_name": "X"})
    assert bad.status_code == 422
    bad = await auth_client.post("/api/apply/sources", json={"provider": "workday", "board_token": "x", "company_name": "X"})
    assert bad.status_code == 422
    src = (await auth_client.post("/api/apply/sources", json={"provider": "greenhouse", "board_token": "acme", "company_name": "Acme"})).json()
    dup = await auth_client.post("/api/apply/sources", json={"provider": "greenhouse", "board_token": "acme", "company_name": "Acme"})
    assert dup.status_code == 409
    monkeypatch.setattr(settings, "APPLY_DISCOVERY_COOLDOWN_SECONDS", 600)
    assert (await auth_client.post(f"/api/apply/sources/{src['id']}/run")).status_code == 200
    r = await auth_client.post(f"/api/apply/sources/{src['id']}/run")
    assert r.status_code == 429 and "Retry-After" in r.headers


async def test_discovery_respects_the_import_cap(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "APPLY_DISCOVERY_MAX_NEW", 1)
    services, _ = _board_services()
    _use_services(services)
    src = (await auth_client.post("/api/apply/sources", json={"provider": "greenhouse", "board_token": "acme", "company_name": "Acme"})).json()
    r = (await auth_client.post(f"/api/apply/sources/{src['id']}/run")).json()
    assert r["matched_filters"] == 2 and r["new_postings"] == 1


async def test_discovery_board_errors_are_reported(auth_client):
    r = await auth_client.post("/api/apply/sources", json={"provider": "lever", "board_token": "acme", "company_name": "Acme"})
    run = await auth_client.post(f"/api/apply/sources/{r.json()['id']}/run")
    assert run.status_code == 502 and run.json()["detail"]["code"] == "discovery_failed"


# ----------------------------------------------------------------- overview --

async def test_overview(auth_client):
    await _prepared(auth_client)
    r = await auth_client.get("/api/apply/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["postings"] == 1 and data["packages"]["ready_for_review"] == 1
    assert data["has_resume"] is True and len(data["to_review"]) == 1
    assert data["top_matches"][0]["fit_score"] is not None


# ------------------------------------------------- hardening (review fixes) --

async def test_extreme_values_in_postings_do_not_crash(auth_client):
    weird = POSTING.replace("$150,000 - $185,000", "$12,000,000 - $18,000,000").replace(
        "jane.doe@acmerobotics.example", "jane@" + "a" * 60 + "." + "b" * 60 + "." + "c" * 60 + ".example"
    ) + "\nAbout " + "Acme " * 80
    r = await auth_client.post("/api/apply/postings", json={"text": weird})
    assert r.status_code == 201, r.text
    assert r.json()["posting"]["analysis"]["salary"] is None


async def test_discovered_postings_can_be_prepared_directly(auth_client):
    services, _ = _board_services()
    _use_services(services)
    await _setup_candidate(auth_client)
    src = (await auth_client.post("/api/apply/sources", json={
        "provider": "greenhouse", "board_token": "acme", "company_name": "Acme", "keywords": ["engineer"]})).json()
    await auth_client.post(f"/api/apply/sources/{src['id']}/run")
    posting = (await auth_client.get("/api/apply/postings")).json()["data"][0]
    detail = (await auth_client.get(f"/api/apply/postings/{posting['id']}")).json()
    assert detail["research"]["verified_facts"]  # researched from the posting, no extra requests
    r = await auth_client.post(f"/api/apply/postings/{posting['id']}/prepare")
    assert r.status_code == 201, r.text
    assert "Acme" in r.json()["payload"]["data"]["cover_letter"]


async def test_failed_discovery_still_starts_the_cooldown(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "APPLY_DISCOVERY_COOLDOWN_SECONDS", 600)
    src = (await auth_client.post("/api/apply/sources", json={"provider": "lever", "board_token": "acme", "company_name": "Acme"})).json()
    assert (await auth_client.post(f"/api/apply/sources/{src['id']}/run")).status_code == 502
    r = await auth_client.post(f"/api/apply/sources/{src['id']}/run")
    assert r.status_code == 429
    assert len(OfflineFetcher.calls) == 1  # the retry never reached the board


async def test_posting_cap_counts_active_postings_and_applies_to_discovery(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "APPLY_MAX_POSTINGS_PER_USER", 1)
    first = await _posting(auth_client)
    r = await auth_client.post("/api/apply/postings", json={"text": POSTING.replace("Senior", "Staff")})
    assert r.status_code == 409
    await auth_client.post(f"/api/apply/postings/{first['id']}/archive")
    assert (await auth_client.post("/api/apply/postings", json={"text": POSTING.replace("Senior", "Staff")})).status_code == 201
    services, _ = _board_services()
    _use_services(services)
    src = (await auth_client.post("/api/apply/sources", json={"provider": "greenhouse", "board_token": "acme", "company_name": "Acme"})).json()
    run = (await auth_client.post(f"/api/apply/sources/{src['id']}/run")).json()
    assert run["new_postings"] == 0 and "maximum" in run["source"]["last_status"]


async def test_apply_request_bodies_are_capped(auth_client):
    r = await auth_client.post("/api/apply/postings", content=b'{"text": "' + b"x" * (1024 * 1024 + 10) + b'"}',
                               headers={"content-type": "application/json"})
    assert r.status_code == 413
    big = {"file": ("cv.txt", b"x" * (7 * 1024 * 1024), "text/plain")}
    assert (await auth_client.post("/api/apply/resume/upload", files=big)).status_code == 413


async def test_concurrent_prepares_never_500(make_client):
    alice = await make_client("alice3@example.com")
    await _setup_candidate(alice)
    posting = await _posting(alice)
    url = f"/api/apply/postings/{posting['id']}/prepare"
    results = await asyncio.gather(alice.post(url), alice.post(url))
    codes = sorted(r.status_code for r in results)
    assert codes in ([201, 201], [201, 409]), codes
    open_pkgs = (await alice.get("/api/apply/packages")).json()["data"]
    assert len(open_pkgs) == 1


async def test_edits_are_throttled(auth_client, monkeypatch):
    monkeypatch.setattr(apply_api, "edit_limiter", apply_api.SlidingWindowLimiter(max_calls=1, window_seconds=600))
    _, package = await _prepared(auth_client)
    body = {"base_hash": package["payload_hash"], "edits": {"cover_letter": "Dear team, thanks for reading."}}
    assert (await auth_client.patch(f"/api/apply/packages/{package['id']}", json=body)).status_code == 200
    assert (await auth_client.patch(f"/api/apply/packages/{package['id']}", json=body)).status_code == 429
