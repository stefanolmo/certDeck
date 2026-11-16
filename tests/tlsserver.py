"""Local TLS servers with generated certificates, used to test the scanner without Internet."""
from __future__ import annotations

import datetime as dt
import socket
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def make_cert(cn: str, days_valid: float, san: list[str] | None = None, issuer_cn: str | None = None):
    """Returns (cert_pem, key_pem). days_valid < 0 builds an already expired certificate."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    if days_valid >= 0:
        nb, na = now - dt.timedelta(days=1), now + dt.timedelta(days=days_valid)
    else:
        nb, na = now + dt.timedelta(days=days_valid - 30), now + dt.timedelta(days=days_valid)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    iss = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn or cn)])
    b = (x509.CertificateBuilder().subject_name(subj).issuer_name(iss).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(nb).not_valid_after(na))
    b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in (san or [cn])]), critical=False)
    cert = b.sign(key, hashes.SHA256())
    return (cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


class TlsServer:
    def __init__(self, tmp_path, cn="localhost", days_valid=90, san=None):
        cert, key = make_cert(cn, days_valid, san)
        (tmp_path / f"{cn}.pem").write_bytes(cert)
        (tmp_path / f"{cn}.key").write_bytes(key)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(tmp_path / f"{cn}.pem", tmp_path / f"{cn}.key")
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = False
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _loop(self):
        self.sock.settimeout(0.2)
        while not self.stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                continue
            try:
                c.settimeout(3)
                with self.ctx.wrap_socket(c, server_side=True):
                    pass
            except Exception:
                c.close()

    def close(self):
        self.stop = True
        self.sock.close()
