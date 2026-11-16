"""Renders docs/splash.png and docs/main.png with synthetic data (no network). Run: python docs/make_screenshots.py"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QApplication

from certdeck import __version__, theme
from certdeck.checker import CertInfo
from certdeck.db import Database
from certdeck.mainwindow import MainWindow
from certdeck.splash import SplashScreen

here = os.path.dirname(__file__)
app = QApplication(sys.argv[:1])
app.setStyleSheet(theme.STYLESHEET)
f = QFont(app.font()); f.setPointSize(10); app.setFont(f)

s = SplashScreen(__version__); s.set_time(2400)
pm = QPixmap(s.size()); pm.fill(0); s.render(pm); pm.save(os.path.join(here, "splash.png"))

now = time.time(); D = 86400
def mk(host, days, issuer="Let's Encrypt", cn=None, trust="", key="EC secp256r1", bits=256, tls="TLSv1.3", san=None, err=""):
    i = CertInfo(checked_at=now - 120, reachable=True, ip="203.0.113.7", tls_version=tls, cipher="TLS_AES_256_GCM_SHA384",
                 latency_ms=84, subject_cn=cn or host, subject=f"CN={cn or host}", issuer_cn="R11", issuer_org=issuer,
                 issuer=f"CN=R11,O={issuer},C=US", not_before=now + (days - 90) * D, not_after=now + days * D,
                 san=san or [host, "www." + host], serial="04A1B2C3D4E5F60718293A4B5C6D7E8F", sig_algorithm="sha256WithRSAEncryption",
                 key_type=key, key_size=bits, sha256="9F" * 32, trust_error=trust)
    return i
db = Database(os.path.join(tempfile.mkdtemp(), "db.json"))
rows = [
    ("example.com", mk("example.com", 71)), ("github.com", mk("github.com", 212, "Sectigo", key="RSA", bits=2048)),
    ("shop.acme.io", mk("shop.acme.io", 12)), ("mail.acme.io", mk("mail.acme.io", 27, "DigiCert")),
    ("legacy.acme.io", mk("legacy.acme.io", -9, "Let's Encrypt", key="RSA", bits=2048, tls="TLSv1.2")),
    ("intranet.local", mk("intranet.local", 400, "Internal CA", trust="self-signed certificate")),
    ("api.acme.io", mk("api.acme.io", 58)), ("old-host.example.net", CertInfo(checked_at=now - 120, error="connection timed out")),
    ("staging.acme.io", mk("staging.acme.io", 5, "Google Trust Services")), ("blog.acme.io:8443", CertInfo()),
]
for h, info in rows:
    e, _ = db.add(h); e.info = info
db.save()
w = MainWindow(db); w.show(); w.table.selectRow(2)
app.processEvents()
w.grab().save(os.path.join(here, "main.png"))
