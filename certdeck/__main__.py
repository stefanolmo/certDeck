import argparse
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, theme
from .db import Database
from .mainwindow import APP_NAME, MainWindow
from .splash import SplashScreen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="certdeck", description="TLS certificate monitor")
    ap.add_argument("--db", metavar="FILE", help="use this database file instead of ~/.local/share/certdeck/certdeck.json")
    ap.add_argument("--no-splash", action="store_true", help="do not show the splash screen")
    ap.add_argument("--screenshot", metavar="PNG", help="(development) save a screenshot and exit")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("certdeck")
    icon_path = os.path.join(os.path.dirname(__file__), "certdeck.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    app.setStyleSheet(theme.STYLESHEET)
    f = QFont(app.font())
    f.setPointSize(10)
    app.setFont(f)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    use_splash = not (args.no_splash or args.screenshot or os.environ.get("CERTDECK_NO_SPLASH"))
    splash = None
    if use_splash:
        splash = SplashScreen(__version__)
        splash.start()
        app.processEvents()
    w = MainWindow(Database(args.db))
    if splash is None:
        w.show()
        if not args.screenshot:
            QTimer.singleShot(0, w.startup_scan)
    else:
        splash.finished.connect(w.show)
        splash.finished.connect(w.raise_)
        splash.finished.connect(w.startup_scan)        # the only automatic scan: once, at program start
    if args.screenshot:
        w.scan_all()
        QTimer.singleShot(int(os.environ.get("CERTDECK_SHOT_DELAY", "6000")),
                          lambda: (w.grab().save(args.screenshot), w.close(), app.quit()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
