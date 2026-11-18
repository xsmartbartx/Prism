"""Download a file from a link, for import and scheduled refresh.

The server makes this request on someone's behalf, so a link is the classic
server-side request forgery surface: a link (or a redirect) pointing at an
internal service, the cloud metadata endpoint or another container must never
be fetched. Every hop — the link itself and each redirect — is checked before
anything connects:

* ``https`` only, no ``user:password@`` in the address;
* every address the host name resolves to must be a public one. Private
  networks are allowed only when the instance opts in (``allow_private``), and
  even then loopback, link-local (cloud metadata), multicast and unspecified
  addresses stay refused;
* the connection goes to the address that was checked (no second lookup that a
  short-lived DNS answer could change), and TLS is verified for the host name;
* at most five redirects, each checked the same way;
* no compressed responses, a size cap, and one time limit for the whole fetch.

Nothing here touches the database; the caller decides what a fetched file
becomes. ``Fetched.kind`` is sniffed from the bytes, never trusted from the
server's ``Content-Type``.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlsplit

from core.errors import ConnectorError

USER_AGENT = "Prism (link refresh)"
MAX_URL_LENGTH = 2000
KIND_EXTENSION = {"csv": ".csv", "xlsx": ".xlsx", "sqlite": ".sqlite", "parquet": ".parquet"}
_REDIRECTS = {301, 302, 303, 307, 308}
# Refused even when private networks are allowed: AWS's IPv6 metadata address is a
# unique-local one, so the link-local rule alone would not catch it.
_ALWAYS_REFUSED = (ipaddress.ip_network("fd00:ec2::254/128"),)
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# What "private networks allowed" opens up: the RFC 1918 ranges, carrier-grade NAT and IPv6
# unique-local addresses. Documentation, benchmarking and reserved ranges stay refused.
_PRIVATE = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
)


class LinkError(ConnectorError):
    """The link cannot be fetched (refused, unreachable, or not a usable file)."""


@dataclass(frozen=True)
class LinkPolicy:
    max_bytes: int
    allow_private: bool = False
    timeout_s: float = 60.0
    connect_timeout_s: float = 10.0
    max_redirects: int = 5


@dataclass(frozen=True)
class Target:
    """One checked hop: where to connect and what to ask for."""

    url: str
    host: str
    port: int
    path: str


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names
    body: bytes | None = None
    too_large: bool = False


@dataclass(frozen=True)
class Fetched:
    url: str  # the final address, after redirects
    not_modified: bool = False
    data: bytes = b""
    kind: str = ""
    filename: str = ""
    etag: str | None = None
    last_modified: str | None = None


Resolver = Callable[[str, int], list[str]]
Transport = Callable[[list[str], Target, dict[str, str], float, int, LinkPolicy], Response]


# ----------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------


def check_url(url: str) -> Target:
    """Parse and check an address without connecting. Raises LinkError."""
    url = (url or "").strip()
    if not url:
        raise LinkError("Enter a link")
    if len(url) > MAX_URL_LENGTH:
        raise LinkError(f"Links can be at most {MAX_URL_LENGTH} characters")
    if any(ord(ch) < 33 for ch in url):
        raise LinkError("The link contains spaces or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise LinkError("That is not a valid link") from exc
    if parts.scheme.lower() != "https":
        raise LinkError("Only https:// links can be imported")
    if parts.username is not None or parts.password is not None:
        raise LinkError("Links with a user name or password in them are not accepted")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise LinkError("The link has no host name")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return Target(url=url, host=host, port=port or 443, path=path)


def address_problem(address: str, *, allow_private: bool) -> str | None:
    """Why this address must not be connected to, or None when it may be."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return "not an IP address"
    if isinstance(ip, ipaddress.IPv6Address):
        if any(ip in net for net in _ALWAYS_REFUSED):
            return "a cloud metadata address"
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return address_problem(str(embedded), allow_private=allow_private)
    if ip.is_unspecified:
        return "an unspecified address"
    if ip.is_loopback:
        return "a loopback address"
    if ip.is_link_local:
        return "a link-local address (such as the cloud metadata service)"
    if ip.is_multicast:
        return "a multicast address"
    if isinstance(ip, ipaddress.IPv4Address) and ip == ipaddress.IPv4Address("255.255.255.255"):
        return "a broadcast address"
    if ip.is_global:
        return None
    if allow_private and any(ip in net for net in _PRIVATE):
        return None
    return "a private or reserved network address"


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise LinkError(f"Could not find the server {host}") from exc
    seen: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        if addr not in seen:
            seen.append(addr)
    return seen


def checked_addresses(target: Target, policy: LinkPolicy, resolver: Resolver) -> list[str]:
    addresses = resolver(target.host, target.port)
    if not addresses:
        raise LinkError(f"Could not find the server {target.host}")
    for addr in addresses:
        problem = address_problem(addr, allow_private=policy.allow_private)
        if problem:
            raise LinkError(f"{target.host} points at {problem}, which links may not reach")
    return addresses


# ----------------------------------------------------------------------
# Transport
# ----------------------------------------------------------------------


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a fixed, already-checked IP, with TLS verified for the host name."""

    def __init__(
        self, address: str, host: str, port: int, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._tls = context

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)


def tls_context() -> ssl.SSLContext:
    """Certificate checks against the system's trusted roots (tests swap in their own)."""
    return ssl.create_default_context()


def https_transport(
    addresses: list[str],
    target: Target,
    headers: dict[str, str],
    deadline: float,
    max_bytes: int,
    policy: LinkPolicy,
) -> Response:
    context = tls_context()
    failure: Exception | None = None
    for address in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LinkError("The link took too long to answer")
        conn = _PinnedHTTPSConnection(
            address, target.host, target.port, min(policy.connect_timeout_s, remaining), context
        )
        try:
            conn.connect()
        except ssl.SSLCertVerificationError as exc:
            conn.close()
            raise LinkError(f"{target.host} did not present a valid certificate") from exc
        except OSError as exc:
            conn.close()
            failure = exc
            continue
        try:
            return _exchange(conn, target, headers, deadline, max_bytes)
        except (OSError, http.client.HTTPException) as exc:
            if isinstance(exc, TimeoutError):
                raise LinkError("The link took too long to answer") from exc
            raise LinkError(f"The download from {target.host} failed") from exc
        finally:
            conn.close()
    raise LinkError(f"Could not connect to {target.host}") from failure


def _exchange(
    conn: _PinnedHTTPSConnection,
    target: Target,
    headers: dict[str, str],
    deadline: float,
    max_bytes: int,
) -> Response:
    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise LinkError("The link took too long to answer")
        return left

    # Keep the socket itself: http.client drops ``conn.sock`` once a response will close the
    # connection, but the response still reads from it, and every read needs the deadline.
    sock = conn.sock
    assert sock is not None
    sock.settimeout(remaining())
    conn.request("GET", target.path, headers=headers)
    resp = conn.getresponse()
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    if resp.status != 200:
        return Response(resp.status, hdrs)
    declared = hdrs.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        return Response(200, hdrs, too_large=True)
    chunks: list[bytes] = []
    total = 0
    while not resp.isclosed():  # the response closes the socket once the body is read
        sock.settimeout(remaining())
        # read1: at most one network read, so the deadline is checked between reads even when
        # a server trickles bytes.
        chunk = resp.read1(min(1 << 16, max_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            return Response(200, hdrs, too_large=True)
    return Response(200, hdrs, b"".join(chunks))


# ----------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------


def fetch(
    url: str,
    policy: LinkPolicy,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    resolver: Resolver = system_resolver,
    transport: Transport = https_transport,
    clock: Callable[[], float] = time.monotonic,
) -> Fetched:
    """Download ``url`` under ``policy``. Raises LinkError with a user-facing message."""
    deadline = clock() + policy.timeout_s
    current = url
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    for _hop in range(policy.max_redirects + 1):
        target = check_url(current)
        addresses = checked_addresses(target, policy, resolver)
        if clock() >= deadline:
            raise LinkError("The link took too long to answer")
        resp = transport(addresses, target, headers, deadline, policy.max_bytes, policy)
        if resp.status in _REDIRECTS:
            location = resp.headers.get("location", "").strip()
            if not location:
                raise LinkError(f"The link redirected (HTTP {resp.status}) without saying where")
            current = urljoin(target.url, location)
            continue
        if resp.status == 304:
            return Fetched(
                url=target.url, not_modified=True, etag=etag, last_modified=last_modified
            )
        if resp.status != 200:
            raise LinkError(_status_message(resp.status, target.host))
        encoding = resp.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("", "identity"):
            raise LinkError(
                "The server sent a compressed response; links must serve the file as is"
            )
        if resp.too_large or resp.body is None:
            mb = policy.max_bytes // (1024 * 1024)
            raise LinkError(f"The file at the link is larger than the {mb} MB limit")
        kind = sniff_kind(resp.body, resp.headers.get("content-type", ""))
        return Fetched(
            url=target.url,
            data=resp.body,
            kind=kind,
            filename=suggest_filename(target, resp.headers, kind),
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )
    raise LinkError(f"The link redirected more than {policy.max_redirects} times")


def _status_message(status: int, host: str) -> str:
    if status in (401, 403):
        return (
            f"{host} refused the download (HTTP {status}). The file must be shared publicly, "
            "or published as a direct download link"
        )
    if status == 404:
        return f"Nothing was found at the link (HTTP 404 from {host})"
    if status == 429:
        return f"{host} is limiting requests (HTTP 429); try again later"
    return f"{host} answered HTTP {status}"


# ----------------------------------------------------------------------
# What the bytes are
# ----------------------------------------------------------------------


def sniff_kind(data: bytes, content_type: str = "") -> str:
    """Decide the file kind from its content. Raises LinkError for anything unusable."""
    if not data:
        raise LinkError("The link returned an empty file")
    if data.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if data.startswith(b"PAR1"):
        return "parquet"
    if data.startswith(b"PK\x03\x04"):
        return "xlsx"
    head = data[:4096]
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if (
        "html" in content_type.lower()
        or text.startswith(b"<!doctype html")
        or text.startswith(b"<html")
    ):
        raise LinkError(
            "The link returned a web page, not a file. Use a direct download link "
            "(for a Google Sheet: File → Share → Publish to web, then choose CSV)"
        )
    if b"\x00" in head:
        raise LinkError("The link did not return a CSV, Excel, Parquet or SQLite file")
    return "csv"


_DISPOSITION_NAME = re.compile(
    r"""filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)|filename\s*=\s*"([^"]*)"|filename\s*=\s*([^;]+)""",
)


def suggest_filename(target: Target, headers: dict[str, str], kind: str) -> str:
    """A file name for the import: the server's own, else the link's last path part."""
    ext = KIND_EXTENSION[kind]
    name = ""
    for m in _DISPOSITION_NAME.finditer(headers.get("content-disposition", "")):
        candidate = unquote(m.group(1)) if m.group(1) else (m.group(2) or m.group(3) or "")
        if candidate.strip():
            name = candidate.strip()
            if m.group(1):
                break  # the RFC 5987 form wins over the plain one
    if not name:
        segment = target.path.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        name = unquote(segment) or target.host
    stem = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in stem:
        base, current = stem.rsplit(".", 1)
        if f".{current.lower()}" in (ext, ".tsv", ".txt", ".xlsm", ".sqlite3", ".db"):
            stem = base
    stem = stem.strip(" .") or target.host
    if stem.lower() in ("pub", "export", "download", "file", "raw"):
        stem = target.host
    return f"{stem}{ext}"
