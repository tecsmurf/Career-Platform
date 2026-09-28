"""
Shared pytest fixtures.

Registration performs a real DNS/MX lookup to reject fake email domains.
Unit tests must not depend on live DNS, so by default we stub the domain
check to accept any domain. Individual tests can override it (e.g. to assert
that a fake domain is rejected).
"""
import pytest

from app.services import auth_service


@pytest.fixture(autouse=True)
def _accept_all_email_domains(monkeypatch):
    async def _ok(domain: str) -> bool:
        return True

    monkeypatch.setattr(auth_service, "email_domain_deliverable", _ok)
