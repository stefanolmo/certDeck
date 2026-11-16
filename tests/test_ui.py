import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from certdeck import theme
from certdeck.checker import CertInfo
from certdeck.db import Database
from certdeck.mainwindow import MainWindow
from certdeck.splash import SplashScreen
from tlsserver import TlsServer


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.STYLESHEET)
    return a


def wait(app, cond, timeout=15):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    assert cond()


def make(tmp_path, app):
    return MainWindow(Database(tmp_path / "db.json"))


def test_add_does_not_scan_and_persists(app, tmp_path):
    w = make(tmp_path, app)
    assert w.stack.currentIndex() == 1                       # empty state
    w.add_edit.setText("a.example, https://b.example:8443/x bad!!")
    w.add_domains()
    assert w.table.rowCount() == 2 and w.add_edit.text() == "bad!!"
    assert not w.scanning                                     # adding never starts a scan
    assert w.tiles["all"].num.text() == "2"
    w2 = make(tmp_path, app)
    assert w2.table.rowCount() == 2
    w2.startup_scan = w2.startup_scan                         # exists; scan_on_start only runs when called
    assert not w2.scanning


def test_scan_and_threshold_recolour(app, tmp_path):
    srv = TlsServer(tmp_path, "localhost", 20)
    try:
        w = make(tmp_path, app)
        w.add_edit.setText(f"localhost:{srv.port}")
        w.add_domains()
        w.scan_all()
        wait(app, lambda: not w.scanning)
    finally:
        srv.close()
    e = w.db.entries[0]
    assert e.info.has_cert
    # self-signed -> "invalid" regardless of the threshold: shown in PROBLEMS
    assert w.tiles["bad"].num.text() == "1"
    # make it look trusted and check the threshold: 20 days left
    e.info.trust_error = ""
    w.thr.setValue(31)
    assert w.tiles["warn"].num.text() == "1" and w.tiles["ok"].num.text() == "0"
    w.thr.setValue(10)
    assert w.tiles["ok"].num.text() == "1" and w.tiles["warn"].num.text() == "0"
    assert Database(tmp_path / "db.json").settings["threshold_days"] == 10
    assert Database(tmp_path / "db.json").entries[0].info.has_cert     # results survive a restart


def test_startup_scan_is_optional(app, tmp_path):
    db = Database(tmp_path / "db.json")
    db.add("localhost:1")
    db.settings["scan_on_start"] = False
    w = MainWindow(db)
    w.startup_scan()
    assert not w.scanning
    w.db.settings["scan_on_start"] = True
    w.startup_scan()
    assert w.scanning
    wait(app, lambda: not w.scanning)


def test_filter_and_remove(app, tmp_path, monkeypatch):
    db = Database(tmp_path / "db.json")
    for h in ("a.test", "b.test"):
        db.add(h)
    now = time.time()
    db.entries[0].info = CertInfo(checked_at=now, reachable=True, not_after=now - 86400, not_before=now - 9e6, subject_cn="a")
    w = MainWindow(db)
    w.set_filter("expired")
    assert w.table.rowCount() == 1
    w.set_filter("expired")                                    # click again = back to all
    assert w.table.rowCount() == 2
    w.table.selectRow(0)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w.remove_selected()
    assert len(w.db.entries) == 1


def test_splash_renders(app):
    s = SplashScreen("0.1.0")
    for ms in (0, 500, 1500, 2900):
        s.set_time(ms)
        assert not s.grab().isNull()
