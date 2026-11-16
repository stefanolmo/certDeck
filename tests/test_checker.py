import socket
import time

import pytest

from certdeck import checker
from certdeck.checker import CertInfo, parse_target
from tlsserver import TlsServer


@pytest.mark.parametrize("text,expected", [
    ("example.com", ("example.com", 443)),
    ("  HTTPS://Example.COM:8443/a/b?x=1 ", ("example.com", 8443)),
    ("host.local:9443", ("host.local", 9443)),
    ("user@mail.example.org", ("mail.example.org", 443)),
    ("example.com.", ("example.com", 443)),
    ("127.0.0.1:4443", ("127.0.0.1", 4443)),
    ("[::1]:8443", ("::1", 8443)),
    ("bücher.example", ("xn--bcher-kva.example", 443)),
])
def test_parse_target(text, expected):
    assert parse_target(text) == expected


@pytest.mark.parametrize("bad", ["", "   ", "exa mple.com", "a..b:99999", "http://", "bad:host:port", "!!!"])
def test_parse_target_rejects(bad):
    with pytest.raises(ValueError):
        parse_target(bad)


def test_scan_self_signed_is_not_trusted(tmp_path):
    srv = TlsServer(tmp_path, "localhost", 90)
    try:
        info = checker.scan("localhost", srv.port)
    finally:
        srv.close()
    assert info.reachable and info.has_cert
    assert info.subject_cn == "localhost" and info.self_signed
    assert info.trust_error                     # unknown CA
    assert 88 <= info.days_left() <= 90
    assert info.key_type.startswith("EC") and info.sha256 and info.tls_version.startswith("TLS")
    assert info.status(30) == "invalid"


def test_scan_expired(tmp_path):
    srv = TlsServer(tmp_path, "localhost", -5)
    try:
        info = checker.scan("localhost", srv.port)
    finally:
        srv.close()
    assert info.days_left() < 0 and info.status(30) == "expired"


def test_hostname_mismatch(tmp_path):
    srv = TlsServer(tmp_path, "other.example", 90)
    try:
        info = checker.scan("localhost", srv.port)
    finally:
        srv.close()
    assert not info.hostname_match and info.status(30) == "invalid"


def test_unreachable():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    info = checker.scan("127.0.0.1", port, timeout=2)
    assert not info.reachable and "refused" in info.error and info.status(30) == "error"


def test_dns_failure():
    info = checker.scan("no-such-host.invalid", 443, timeout=2)
    assert info.status(30) == "error" and info.error


def test_status_thresholds():
    now = time.time()
    i = CertInfo(checked_at=now, not_after=now + 20 * 86400, not_before=now - 86400)
    assert i.status(30) == "warn" and i.status(10) == "ok"
    assert i.status(20) == "warn"
    i.not_after = now - 1
    assert i.status(30) == "expired"
    assert CertInfo().status(30) == "never"
    i.trust_error = "unable to get local issuer certificate"
    i.not_after = now + 200 * 86400
    assert i.status(30) == "invalid"


def test_roundtrip_dict():
    i = CertInfo(checked_at=1.0, subject_cn="x", san=["a", "b"], not_after=5.0)
    assert CertInfo.from_dict(i.to_dict()) == i
    assert CertInfo.from_dict({"bogus": 1}) == CertInfo()
