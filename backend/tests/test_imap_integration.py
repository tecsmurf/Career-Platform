"""
Real-protocol integration test (optional).

Runs the production IMAP transport end-to-end against a real IMAP server
implementation (pymap) behind a real TLS terminator:

    API → sync engine → PinnedIMAP4_SSL → TLS (cert verified against a test CA,
    SNI host name) → IMAP server

Only two things are substituted: DNS (a fake host name can't be resolved, and
127.0.0.1 would rightly be blocked by the SSRF guard — which has its own tests)
and the trust store (a throwaway test CA instead of the system CAs).

Skipped automatically unless `pymap` is installed:
    pip install pymap && pytest tests/test_imap_integration.py
"""
import imaplib
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pymap")

from cryptography import x509                                              # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization           # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec                   # noqa: E402
from cryptography.x509.oid import NameOID                                  # noqa: E402

from app.services.email import imap_client, providers                      # noqa: E402
from tests.email_fakes import AMAZON_ORDER, NOTION_INTERVIEW, STRIPE_CONFIRM   # noqa: E402

HOST = "imap.test-provider.com"
USER = "me@test-provider.com"
PASSWORD = "imap-secret-123"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_ca_and_leaf(tmp: str) -> tuple[str, str, str]:
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Career Platform Test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
          .not_valid_after(now + timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)]))
            .issuer_name(ca_name).public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    paths = [os.path.join(tmp, n) for n in ("ca.pem", "leaf.pem", "leaf.key")]
    with open(paths[0], "wb") as f:
        f.write(ca.public_bytes(serialization.Encoding.PEM))
    with open(paths[1], "wb") as f:
        f.write(leaf.public_bytes(serialization.Encoding.PEM))
    with open(paths[2], "wb") as f:
        f.write(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return tuple(paths)


class TLSTerminator:
    """Accepts TLS on `port` and pipes plaintext to the IMAP server."""

    def __init__(self, cert: str, key: str, upstream_port: int):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, key)
        self.upstream = upstream_port
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.handshakes_ok = 0
        self.handshakes_failed = 0
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(raw,), daemon=True).start()

    def _handle(self, raw):
        try:
            tls = self.ctx.wrap_socket(raw, server_side=True)
        except (ssl.SSLError, OSError):
            self.handshakes_failed += 1
            raw.close()
            return
        self.handshakes_ok += 1
        up = socket.create_connection(("127.0.0.1", self.upstream))

        def pump(src, dst):
            try:
                while data := src.recv(65536):
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.close()
                    except OSError:
                        pass
        threading.Thread(target=pump, args=(tls, up), daemon=True).start()
        pump(up, tls)

    def close(self):
        self.sock.close()


@pytest.fixture(scope="module")
def real_imap():
    tmp = tempfile.mkdtemp()
    ca, leaf, key = _make_ca_and_leaf(tmp)
    imap_port = _free_port()
    exe = shutil.which("pymap") or sys.executable
    cmd = ([exe] if exe != sys.executable else [sys.executable, "-m", "pymap"]) + [
        "--host", "127.0.0.1", "--port", str(imap_port), "--no-tls",
        "dict", "--demo-user", USER, "--demo-password", PASSWORD,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", imap_port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("pymap did not start")
    term = TLSTerminator(leaf, key, imap_port)
    yield {"imap_port": imap_port, "tls_port": term.port, "ca": ca, "term": term}
    term.close()
    proc.terminate()
    proc.wait(timeout=5)


def _plain(real_imap) -> imaplib.IMAP4:
    m = imaplib.IMAP4("127.0.0.1", real_imap["imap_port"])
    m.login(USER, PASSWORD)
    return m


@pytest.fixture
def production_transport(real_imap, monkeypatch):
    """Real PinnedIMAP4_SSL + verification; only DNS and the trust store are swapped."""
    def trusted_ctx():
        ctx = ssl.create_default_context(cafile=real_imap["ca"])
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx
    monkeypatch.setattr(imap_client, "resolve_address", lambda host, port: "127.0.0.1")
    monkeypatch.setattr(imap_client, "build_tls_context", trusted_ctx)
    monkeypatch.setattr(providers.GenericIMAPProvider, "port", real_imap["tls_port"])
    assert imap_client.connect_imap is imap_client._default_connect      # the real transport
    return real_imap


async def test_full_flow_against_real_imap_server(make_client, production_transport):
    m = _plain(production_transport)
    for raw in (STRIPE_CONFIRM, NOTION_INTERVIEW, AMAZON_ORDER):
        assert m.append("INBOX", None, imaplib.Time2Internaldate(time.time()), raw)[0] == "OK"
    m.logout()

    c = await make_client("real@example.com")
    res = await c.post("/api/email/connect", json={"provider": "imap", "email": USER, "password": PASSWORD, "host": HOST})
    assert res.status_code == 200, res.text

    s = (await c.post("/api/email/sync")).json()["summary"]
    assert s["status"] == "success" and s["new_messages"] >= 3 and s["new_suggestions"] == 2
    companies = {x["company"] for x in (await c.get("/api/email/suggestions")).json()["data"]}
    assert companies == {"Stripe", "Notion"}

    again = (await c.post("/api/email/sync")).json()["summary"]
    assert again["new_messages"] == 0 and again["new_suggestions"] == 0          # idempotent

    m = _plain(production_transport)
    m.select('"INBOX"', True)
    _typ, flags = m.uid("FETCH", "1:*", "(FLAGS)")
    m.logout()
    assert flags and not any(b"\\Seen" in f for f in flags if isinstance(f, bytes))  # nothing marked read


async def test_wrong_password_rejected_by_real_server(make_client, production_transport):
    c = await make_client("wrongpw@example.com")
    res = await c.post("/api/email/connect", json={"provider": "imap", "email": USER, "password": "nope-nope", "host": HOST})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "auth_failed"


async def test_untrusted_certificate_rejected_before_login(make_client, real_imap, monkeypatch):
    """System trust store (production default) does not trust the test CA."""
    monkeypatch.setattr(imap_client, "resolve_address", lambda host, port: "127.0.0.1")
    monkeypatch.setattr(providers.GenericIMAPProvider, "port", real_imap["tls_port"])
    before_ok = real_imap["term"].handshakes_ok
    c = await make_client("tls@example.com")
    res = await c.post("/api/email/connect", json={"provider": "imap", "email": USER, "password": PASSWORD, "host": HOST})
    assert res.status_code == 502 and res.json()["detail"]["code"] == "tls_failed"
    assert real_imap["term"].handshakes_ok == before_ok        # no TLS session → password never sent


async def test_certificate_for_another_host_rejected(make_client, production_transport):
    before_ok = production_transport["term"].handshakes_ok
    c = await make_client("sni@example.com")
    res = await c.post("/api/email/connect", json={
        "provider": "imap", "email": USER, "password": PASSWORD, "host": "imap.other-provider.com"})
    assert res.status_code == 502 and res.json()["detail"]["code"] == "tls_failed"
    assert production_transport["term"].handshakes_ok == before_ok
