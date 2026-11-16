"""TLS certificate inspection: connects to host:port, validates the chain and extracts the certificate details."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import ExtensionOID, NameOID

DEFAULT_PORT = 443

# status codes (also used by the UI)
NEVER, OK, WARN, EXPIRED, INVALID, ERROR = "never", "ok", "warn", "expired", "invalid", "error"


@dataclass
class CertInfo:
    """Result of one scan. Plain data so it can be stored as JSON."""
    checked_at: float = 0.0           # unix time of the scan, 0 = never
    reachable: bool = False
    error: str = ""                   # connection / handshake error (no certificate available)
    trust_error: str = ""             # certificate obtained but not trusted (hostname, CA, self-signed…)
    ip: str = ""
    tls_version: str = ""
    cipher: str = ""
    latency_ms: int = 0
    subject_cn: str = ""
    subject: str = ""
    issuer_cn: str = ""
    issuer_org: str = ""
    issuer: str = ""
    not_before: float = 0.0
    not_after: float = 0.0
    san: list[str] = field(default_factory=list)
    serial: str = ""
    sha256: str = ""
    sig_algorithm: str = ""
    key_type: str = ""
    key_size: int = 0
    self_signed: bool = False
    hostname_match: bool = True
    wildcard: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CertInfo":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in (d or {}).items() if k in known})

    # -------------------------------------------------------------- derived values
    @property
    def has_cert(self) -> bool:
        return self.not_after > 0

    def days_left(self, now: float | None = None) -> int | None:
        """Whole days until expiry (negative = already expired), None without a certificate."""
        if not self.has_cert:
            return None
        now = time.time() if now is None else now
        return int((self.not_after - now) // 86400)

    def status(self, threshold_days: int, now: float | None = None) -> str:
        """Classification shown in the table. Depends on the threshold, so it is computed on the fly."""
        if not self.checked_at:
            return NEVER
        if not self.has_cert:
            return ERROR
        now = time.time() if now is None else now
        if self.not_after <= now:
            return EXPIRED
        if self.trust_error:
            return INVALID
        if (self.not_after - now) / 86400 <= threshold_days:
            return WARN
        return OK


def parse_target(text: str) -> tuple[str, int]:
    """'https://Example.com:8443/path' -> ('example.com', 8443). Raises ValueError for garbage."""
    s = text.strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    s = re.split(r"[/?#]", s, maxsplit=1)[0]
    s = s.rsplit("@", 1)[-1]
    port = DEFAULT_PORT
    if s.startswith("["):                           # [ipv6]:port
        host, _, rest = s[1:].partition("]")
        if rest.startswith(":"):
            port = int(rest[1:])
    elif s.count(":") == 1:
        s, p = s.split(":")
        host, port = s, int(p)
    else:
        host = s
    host = host.strip(".")
    if not host or not (1 <= port <= 65535):
        raise ValueError(f"invalid domain: {text!r}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as e:
            raise ValueError(f"invalid domain: {text!r}") from e
        if not re.fullmatch(r"[a-z0-9_]([a-z0-9_.-]*[a-z0-9_])?", host):
            raise ValueError(f"invalid domain: {text!r}")
    return host, port


def _name_attr(name: x509.Name, oid) -> str:
    try:
        v = name.get_attributes_for_oid(oid)
        return str(v[0].value) if v else ""
    except Exception:
        return ""


def _ts(dt: datetime) -> float:
    return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()


def _key_info(pub) -> tuple[str, int]:
    if isinstance(pub, rsa.RSAPublicKey):
        return "RSA", pub.key_size
    if isinstance(pub, ec.EllipticCurvePublicKey):
        return f"EC {pub.curve.name}", pub.key_size
    if isinstance(pub, ed25519.Ed25519PublicKey):
        return "Ed25519", 256
    if isinstance(pub, ed448.Ed448PublicKey):
        return "Ed448", 448
    if isinstance(pub, dsa.DSAPublicKey):
        return "DSA", pub.key_size
    return type(pub).__name__, 0


def host_matches(host: str, names: list[str]) -> bool:
    host = host.lower()
    for n in names:
        n = n.lower()
        if n == host:
            return True
        if n.startswith("*.") and "." in host and host.split(".", 1)[1] == n[2:]:
            return True
    return False


def _fill_from_der(info: CertInfo, der: bytes, host: str) -> None:
    c = x509.load_der_x509_certificate(der)
    info.subject_cn = _name_attr(c.subject, NameOID.COMMON_NAME)
    info.subject = c.subject.rfc4514_string()
    info.issuer_cn = _name_attr(c.issuer, NameOID.COMMON_NAME)
    info.issuer_org = _name_attr(c.issuer, NameOID.ORGANIZATION_NAME)
    info.issuer = c.issuer.rfc4514_string()
    info.not_before = _ts(c.not_valid_before_utc)
    info.not_after = _ts(c.not_valid_after_utc)
    info.serial = format(c.serial_number, "X")
    info.sha256 = hashlib.sha256(der).hexdigest().upper()
    info.self_signed = c.subject == c.issuer
    try:
        info.sig_algorithm = c.signature_algorithm_oid._name or c.signature_algorithm_oid.dotted_string
    except Exception:
        info.sig_algorithm = ""
    info.key_type, info.key_size = _key_info(c.public_key())
    names: list[str] = []
    try:
        ext = c.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        names = list(ext.get_values_for_type(x509.DNSName)) + [str(i) for i in ext.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        pass
    info.san = names
    match_names = names or ([info.subject_cn] if info.subject_cn else [])
    info.hostname_match = host_matches(host, match_names)
    info.wildcard = any(n.startswith("*.") for n in names) or info.subject_cn.startswith("*.")


def _handshake(host: str, port: int, timeout: float, verify: bool) -> tuple[bytes, str, str, str, int]:
    """Returns (der, tls_version, cipher_name, ip, latency_ms). Raises ssl.SSLCertVerificationError if verify fails."""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    t0 = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        ip = raw.getpeername()[0]
        server_name = None if _is_ip(host) else host
        with ctx.wrap_socket(raw, server_hostname=server_name) as s:
            lat = int((time.perf_counter() - t0) * 1000)
            der = s.getpeercert(binary_form=True)
            cipher = s.cipher()
            return der, s.version() or "", cipher[0] if cipher else "", ip, lat


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def scan(host: str, port: int = DEFAULT_PORT, timeout: float = 8.0) -> CertInfo:
    """Full inspection of one endpoint. Never raises: problems are reported inside the result."""
    info = CertInfo(checked_at=time.time())
    try:
        try:
            der, ver, cipher, ip, lat = _handshake(host, port, timeout, verify=True)
        except ssl.SSLCertVerificationError as e:
            info.trust_error = (e.verify_message or str(e)).strip()
            # certificate is bad but we still want to show it: repeat without validation
            der, ver, cipher, ip, lat = _handshake(host, port, timeout, verify=False)
        info.reachable = True
        info.ip, info.tls_version, info.cipher, info.latency_ms = ip, ver, cipher, lat
        if not der:
            info.error = "the server sent no certificate"
            return info
        _fill_from_der(info, der, host)
        if not info.hostname_match and not info.trust_error:
            info.trust_error = "hostname mismatch"
    except socket.gaierror:
        info.error = "DNS: name not found"
    except (socket.timeout, TimeoutError):
        info.error = "connection timed out"
    except ConnectionRefusedError:
        info.error = "connection refused"
    except ssl.SSLError as e:
        info.reachable = True
        info.error = f"TLS error: {e.reason or e}"
    except OSError as e:
        info.error = f"network error: {e.strerror or e}"
    except Exception as e:                              # parsing problems etc.
        info.error = f"{type(e).__name__}: {e}"
    return info
