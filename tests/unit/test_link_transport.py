"""The real HTTPS transport against a local TLS server (pinned address, verified host name)."""

from __future__ import annotations

import datetime as dt
import ssl
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from data.connectors import link
from data.connectors.link import LinkError, LinkPolicy, Target, https_transport

HOST = "link.test"
BODY = b"Region,Units\nEU,3\n" * 200


def _cert(tmp: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp / "cert.pem", tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class Handler(BaseHTTPRequestHandler):
    seen: list[dict[str, str]] = []

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass

    def do_GET(self) -> None:
        Handler.seen.append({"path": self.path, "host": self.headers.get("Host", "")})
        if self.path == "/slow":
            time.sleep(1.5)
        if self.path.startswith("/chunked"):
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(3):
                part = BODY[:500]
                self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            return
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/data.csv")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.send_header("ETag", '"abc"')
        self.end_headers()
        self.wfile.write(BODY)


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[int]:
    cert, key = _cert(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    trusted = ssl.create_default_context(cafile=str(cert))
    monkeypatch.setattr(link, "tls_context", lambda: trusted)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    Handler.seen = []
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(port: int, path: str, *, host: str = HOST, max_bytes: int = 100_000,
         timeout: float = 10.0) -> link.Response:
    target = Target(url=f"https://{host}:{port}{path}", host=host, port=port, path=path)
    policy = LinkPolicy(max_bytes=max_bytes, timeout_s=timeout)
    return https_transport(["127.0.0.1"], target, {"User-Agent": "t"}, time.monotonic() + timeout,
                           max_bytes, policy)


def test_downloads_over_a_pinned_verified_connection(server: int) -> None:
    resp = _get(server, "/data.csv")
    assert resp.status == 200 and resp.body == BODY and resp.headers["etag"] == '"abc"'
    assert Handler.seen[-1]["host"] == f"{HOST}:{server}"  # the name, not the pinned address


def test_chunked_and_size_limits(server: int) -> None:
    assert _get(server, "/chunked").body == BODY[:500] * 3
    assert _get(server, "/chunked", max_bytes=1000).too_large
    assert _get(server, "/data.csv", max_bytes=100).too_large  # Content-Length says too big


def test_redirect_is_returned_not_followed(server: int) -> None:
    resp = _get(server, "/moved")
    assert resp.status == 302 and resp.headers["location"] == "/data.csv" and resp.body is None


def test_certificate_must_match_the_host_name(server: int) -> None:
    with pytest.raises(LinkError, match="valid certificate"):
        _get(server, "/data.csv", host="other.test")


def test_unreachable_and_slow(server: int) -> None:
    with pytest.raises(LinkError, match="took too long"):
        _get(server, "/slow", timeout=0.5)
    closed = Target(url="https://link.test:1/", host=HOST, port=1, path="/")
    with pytest.raises(LinkError, match="Could not connect"):
        https_transport(["127.0.0.1"], closed, {}, time.monotonic() + 5, 10, LinkPolicy(10))
