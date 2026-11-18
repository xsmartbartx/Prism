"""Link downloads: address checks (SSRF), redirects, limits and file sniffing."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from data.connectors.link import (
    LinkError,
    LinkPolicy,
    Response,
    Target,
    address_problem,
    check_url,
    fetch,
    sniff_kind,
    suggest_filename,
)

POLICY = LinkPolicy(max_bytes=1000)
CSV = b"Region,Units\nEU,3\nUS,5\n"


def resolver(table: dict[str, list[str]]) -> Callable[[str, int], list[str]]:
    def resolve(host: str, port: int) -> list[str]:
        return table.get(host, ["93.184.216.34"])

    return resolve


class FakeServer:
    """Answers by URL; records each request (address list, target, headers)."""

    def __init__(self, routes: dict[str, Response]) -> None:
        self.routes = routes
        self.calls: list[tuple[list[str], Target, dict[str, str]]] = []

    def __call__(
        self,
        addresses: list[str],
        target: Target,
        headers: dict[str, str],
        deadline: float,
        max_bytes: int,
        policy: LinkPolicy,
    ) -> Response:
        self.calls.append((addresses, target, dict(headers)))
        resp = self.routes[target.url]
        if resp.body is not None and len(resp.body) > max_bytes:
            return Response(resp.status, resp.headers, too_large=True)
        return resp


def ok(body: bytes = CSV, **headers: str) -> Response:
    return Response(200, {k.replace("_", "-"): v for k, v in headers.items()}, body)


class TestUrls:
    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("", "Enter a link"),
            ("http://example.com/a.csv", "Only https"),
            ("ftp://example.com/a.csv", "Only https"),
            ("file:///etc/passwd", "Only https"),
            ("https://user:pw@example.com/a.csv", "user name or password"),
            ("https:///a.csv", "no host"),
            ("https://example.com:99999/a.csv", "not a valid link"),
            ("https://exa mple.com/a.csv", "spaces"),
            ("https://example.com/" + "a" * 2000, "at most"),
        ],
    )
    def test_rejects(self, url: str, message: str) -> None:
        with pytest.raises(LinkError, match=message):
            check_url(url)

    def test_parses(self) -> None:
        t = check_url(" https://Example.com:8443/x/data.csv?gid=0&output=csv ")
        assert (t.host, t.port, t.path) == ("example.com", 8443, "/x/data.csv?gid=0&output=csv")
        assert check_url("https://example.com").path == "/"


class TestAddresses:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "0.0.0.0",
            "10.1.2.3",
            "172.17.0.2",  # a Docker bridge network
            "192.168.1.10",
            "100.64.0.1",
            "169.254.169.254",  # cloud metadata
            "192.0.2.1",
            "224.0.0.1",
            "255.255.255.255",
            "::1",
            "::",
            "fe80::1",
            "fc00::1",
            "fd00:ec2::254",
            "::ffff:127.0.0.1",  # IPv4-mapped
            "::ffff:169.254.169.254",
            "2002:a9fe:a9fe::1",  # 6to4 around 169.254.169.254
            "64:ff9b::a00:1",  # NAT64 around 10.0.0.1
            "2001::1",  # Teredo
            "not-an-ip",
        ],
    )
    def test_refused_by_default(self, address: str) -> None:
        assert address_problem(address, allow_private=False) is not None

    @pytest.mark.parametrize("address", ["93.184.216.34", "2606:2800:220:1::1", "::ffff:8.8.8.8"])
    def test_public_allowed(self, address: str) -> None:
        assert address_problem(address, allow_private=False) is None

    def test_private_opt_in_keeps_the_dangerous_ones_out(self) -> None:
        for address in ("10.1.2.3", "172.17.0.2", "192.168.1.10", "100.64.0.1", "fd12::1"):
            assert address_problem(address, allow_private=True) is None, address
        for address in (
            "127.0.0.1",
            "169.254.169.254",
            "fe80::1",
            "fd00:ec2::254",
            "0.0.0.0",
            "192.0.2.1",
            "::ffff:169.254.169.254",
        ):
            assert address_problem(address, allow_private=True) is not None, address


class TestFetch:
    def test_downloads_and_sends_conditional_headers(self) -> None:
        server = FakeServer({"https://data.test/q1.csv": ok(etag='"v2"', last_modified="Tue")})
        got = fetch(
            "https://data.test/q1.csv",
            POLICY,
            etag='"v1"',
            last_modified="Mon",
            resolver=resolver({}),
            transport=server,
        )
        assert (got.data, got.kind, got.filename, got.etag, got.last_modified) == (
            CSV,
            "csv",
            "q1.csv",
            '"v2"',
            "Tue",
        )
        headers = server.calls[0][2]
        assert headers["If-None-Match"] == '"v1"' and headers["If-Modified-Since"] == "Mon"
        assert headers["Accept-Encoding"] == "identity"

    def test_host_resolving_anywhere_private_is_refused_before_connecting(self) -> None:
        server = FakeServer({})
        for addresses in (["10.0.0.5"], ["93.184.216.34", "127.0.0.1"]):
            with pytest.raises(LinkError, match="may not reach"):
                fetch(
                    "https://intranet.test/a.csv",
                    POLICY,
                    resolver=resolver({"intranet.test": addresses}),
                    transport=server,
                )
        assert server.calls == []

    def test_connects_to_the_checked_addresses(self) -> None:
        server = FakeServer({"https://data.test/a.csv": ok()})
        fetch("https://data.test/a.csv", POLICY, resolver=resolver({"data.test": ["8.8.4.4"]}),
              transport=server)
        assert server.calls[0][0] == ["8.8.4.4"]

    def test_follows_redirects_and_checks_each_hop(self) -> None:
        server = FakeServer(
            {
                "https://docs.test/pub?output=csv": Response(307, {"location": "/export/a"}),
                "https://docs.test/export/a": Response(
                    302, {"location": "https://cdn.test/file.csv"}
                ),
                "https://cdn.test/file.csv": ok(),
            }
        )
        got = fetch("https://docs.test/pub?output=csv", POLICY, resolver=resolver({}),
                    transport=server)
        assert got.url == "https://cdn.test/file.csv" and got.data == CSV

        evil = FakeServer(
            {"https://docs.test/a": Response(302, {"location": "https://meta.test/latest"})}
        )
        with pytest.raises(LinkError, match="may not reach"):
            fetch("https://docs.test/a", POLICY,
                  resolver=resolver({"meta.test": ["169.254.169.254"]}), transport=evil)
        downgrade = FakeServer(
            {"https://docs.test/a": Response(301, {"location": "http://docs.test/a"})}
        )
        with pytest.raises(LinkError, match="Only https"):
            fetch("https://docs.test/a", POLICY, resolver=resolver({}), transport=downgrade)

    def test_redirect_limits(self) -> None:
        loop = FakeServer({"https://a.test/x": Response(302, {"location": "https://a.test/x"})})
        with pytest.raises(LinkError, match="more than 5 times"):
            fetch("https://a.test/x", POLICY, resolver=resolver({}), transport=loop)
        assert len(loop.calls) == 6
        nowhere = FakeServer({"https://a.test/x": Response(302, {})})
        with pytest.raises(LinkError, match="without saying where"):
            fetch("https://a.test/x", POLICY, resolver=resolver({}), transport=nowhere)

    def test_not_modified(self) -> None:
        server = FakeServer({"https://a.test/x.csv": Response(304)})
        got = fetch("https://a.test/x.csv", POLICY, etag='"v1"', resolver=resolver({}),
                    transport=server)
        assert got.not_modified and got.data == b"" and got.etag == '"v1"'

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (Response(403), "shared publicly"),
            (Response(404), "Nothing was found"),
            (Response(429), "limiting requests"),
            (Response(500), "answered HTTP 500"),
            (ok(b"x" * 1001), "larger than"),
            (ok(CSV, content_encoding="gzip"), "compressed"),
            (ok(b"<!DOCTYPE html><html>sign in</html>"), "web page"),
            (ok(CSV, content_type="text/html; charset=utf-8"), "web page"),
            (ok(b"\x00\x01\x02binary"), "did not return"),
            (ok(b""), "empty file"),
        ],
    )
    def test_unusable_answers(self, response: Response, message: str) -> None:
        server = FakeServer({"https://a.test/x": response})
        with pytest.raises(LinkError, match=message):
            fetch("https://a.test/x", POLICY, resolver=resolver({}), transport=server)

    def test_time_limit_covers_the_whole_fetch(self) -> None:
        ticks = iter([0.0, 61.0])
        server = FakeServer({"https://a.test/x": ok()})
        with pytest.raises(LinkError, match="too long"):
            fetch("https://a.test/x", LinkPolicy(max_bytes=1000), resolver=resolver({}),
                  transport=server, clock=lambda: next(ticks))
        assert server.calls == []


class TestFiles:
    def test_sniffs_kind_from_bytes(self) -> None:
        assert sniff_kind(b"SQLite format 3\x00rest") == "sqlite"
        assert sniff_kind(b"PAR1....PAR1") == "parquet"
        assert sniff_kind(b"PK\x03\x04rest", "text/csv") == "xlsx"
        assert sniff_kind("﻿a;b\n1;2\n".encode(), "application/octet-stream") == "csv"

    def test_filenames(self) -> None:
        t = check_url("https://docs.test/spreadsheets/d/e/abc/pub?output=csv")
        assert suggest_filename(t, {}, "csv") == "docs.test.csv"
        disp = {"content-disposition": 'attachment; filename="Sales 2026 - Q1.csv"'}
        assert suggest_filename(t, disp, "csv") == "Sales 2026 - Q1.csv"
        rfc = {"content-disposition": "attachment; filename=plain.csv; filename*=UTF-8''Zu%C3%BCrich.xlsx"}
        assert suggest_filename(t, rfc, "xlsx") == "Zuürich.xlsx"
        assert suggest_filename(check_url("https://h.test/data/report.tsv"), {}, "csv") == "report.csv"
        assert suggest_filename(check_url("https://h.test/a/../../etc"), {}, "csv") == "etc.csv"
        assert suggest_filename(check_url("https://h.test/"), {}, "parquet") == "h.test.parquet"
