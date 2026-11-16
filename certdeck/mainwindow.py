"""Main window: domain table with status pills, expiry bars, summary tiles, details panel and scan controls."""
from __future__ import annotations

import base64
import csv
import re
import time
from datetime import datetime

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QSplitter, QStackedWidget, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from . import __version__, checker, theme
from .db import Database, Entry
from .theme import icon

APP_NAME = "Cert Deck"
TITLE = "Cert Deck"
ROLE_KEY, ROLE_SORT = Qt.UserRole, Qt.UserRole + 1
COLS = ["Status", "Domain", "Expires in", "Expiry date", "Issuer", "Subject", "Key", "TLS", "Last scan"]
TILES = [("all", "TOTAL", theme.TEXT), ("ok", "VALID", theme.OK), ("warn", "EXPIRING", theme.WARN),
         ("expired", "EXPIRED", theme.DANGER), ("bad", "PROBLEMS", theme.ORANGE)]


def fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"


def fmt_dt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "never"


# ---------------------------------------------------------------------- background scanning
class _Signals(QObject):
    done = Signal(str, object)          # entry key, CertInfo


class ScanTask(QRunnable):
    def __init__(self, entry: Entry, signals: _Signals):
        super().__init__()
        self.host, self.port, self.key, self.sig = entry.host, entry.port, entry.key, signals

    def run(self) -> None:
        info = checker.scan(self.host, self.port)
        self.sig.done.emit(self.key, info)


# ---------------------------------------------------------------------- table pieces
class SortItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(ROLE_SORT), other.data(ROLE_SORT)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class StatusDelegate(QStyledItemDelegate):
    """Rounded coloured pill with the status text."""
    def paint(self, p: QPainter, opt, idx) -> None:
        super().paint(p, opt, idx)                      # background / selection
        col = QColor(idx.data(Qt.UserRole + 2) or theme.MUTED)
        text = idx.data(Qt.DisplayRole) or ""
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(opt.font)
        f.setPointSizeF(max(7.5, opt.font.pointSizeF() - 1.5))
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(text) + 22
        r = QRectF(opt.rect.left() + 8, opt.rect.center().y() - 10, min(w, opt.rect.width() - 12), 20)
        bg = QColor(col)
        bg.setAlpha(40)
        p.setPen(QPen(col, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)
        p.setBrush(col)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(r.left() + 10, r.center().y()), 3, 3)
        p.setPen(col)
        p.drawText(r.adjusted(18, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.restore()

    def displayText(self, *_):
        return ""

    def sizeHint(self, opt, idx):
        return QSize(130, 34)


class DaysDelegate(QStyledItemDelegate):
    """Days left as text plus a thin bar (full = 1 year or more)."""
    def paint(self, p: QPainter, opt, idx) -> None:
        super().paint(p, opt, idx)
        days = idx.data(ROLE_SORT)
        if days is None or days >= 10**8:
            return
        col = QColor(idx.data(Qt.UserRole + 2) or theme.MUTED)
        r = opt.rect.adjusted(10, 0, -12, 0)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(col)
        txt = f"{days} d" if days >= 0 else f"{-days} d ago"
        p.drawText(QRectF(r.left(), r.top() + 3, r.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, txt)
        bar = QRectF(r.left(), r.bottom() - 9, r.width(), 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(bar, 2, 2)
        frac = max(0.0, min(1.0, days / 365.0)) if days > 0 else 1.0
        p.setBrush(col)
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(frac, 0.04), 4), 2, 2)
        p.restore()

    def displayText(self, *_):
        return ""


class Tile(QFrame):
    """Clickable summary tile that also works as table filter."""
    clicked = Signal(str)

    def __init__(self, key: str, title: str, color: str):
        super().__init__()
        self.key, self.color = key, color
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(0)
        self.num = QLabel("0")
        self.num.setStyleSheet(f"font-size:30px; font-weight:800; color:{color}; background:transparent;")
        t = QLabel(title)
        t.setObjectName("cardTitle")
        lay.addWidget(self.num)
        lay.addWidget(t)
        self.set_active(False)

    def set_active(self, on: bool) -> None:
        c = QColor(self.color)
        border = self.color if on else theme.BORDER
        bg = f"rgba({c.red()},{c.green()},{c.blue()},30)" if on else theme.CARD
        self.setStyleSheet(f"QFrame#tile{{background:{bg}; border:1px solid {border}; border-radius:10px;}}"
                           f"QFrame#tile:hover{{border-color:{self.color};}} QFrame#tile QLabel{{background:transparent;}}")

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key)


class Pill(QLabel):
    def set_status(self, status: str, text: str | None = None) -> None:
        col, label = theme.STATUS[status]
        c = QColor(col)
        self.setText(text or label)
        self.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},38); color:{col}; border:1px solid {col};"
                           f"border-radius:13px; padding:4px 14px; font-weight:700; letter-spacing:0.5px;")


# ---------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, db: Database | None = None):
        super().__init__()
        self.db = db or Database()
        self.setWindowTitle(TITLE)
        self.resize(1440, 780)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(12)
        self.sig = _Signals()
        self.sig.done.connect(self._on_result)
        self.scanning: set[str] = set()
        self._batch_total = 0
        self._batch_done = 0
        self.filter = "all"
        self._building = False
        self._build_ui()
        self.table.sortByColumn(2, Qt.AscendingOrder)      # soonest expiry first
        self.populate()
        geo = self.db.settings.get("geometry")
        if geo:
            try:
                self.restoreGeometry(base64.b64decode(geo))
            except Exception:
                pass

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(16, 14, 16, 8)
        v.setSpacing(12)

        # header: logo + title + tiles
        top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icon("shield", theme.ACCENT).pixmap(34, 34))
        title = QLabel(f'<span style="font-size:22px;font-weight:900;color:#f1f5f9">Cert</span>'
                       f'<span style="font-size:22px;font-weight:900;color:{theme.ACCENT}"> Deck</span>')
        top.addWidget(logo)
        top.addWidget(title)
        top.addSpacing(18)
        self.tiles: dict[str, Tile] = {}
        for key, name, col in TILES:
            t = Tile(key, name, col)
            t.clicked.connect(self.set_filter)
            self.tiles[key] = t
            top.addWidget(t)
        top.addStretch(1)
        v.addLayout(top)

        # toolbar card: add domain, scan buttons, threshold
        bar = QFrame()
        bar.setObjectName("card")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("Add a domain: example.com  ·  host:port  ·  https://…   (several: separate with space or comma)")
        self.add_edit.setMinimumWidth(380)
        self.add_edit.returnPressed.connect(self.add_domains)
        b_add = QPushButton(icon("plus", theme.TEXT), " Add")
        b_add.clicked.connect(self.add_domains)
        self.b_scan = QPushButton(icon("scan", "#04211d"), "  Scan all")
        self.b_scan.setObjectName("primary")
        self.b_scan.setMinimumHeight(34)
        self.b_scan.clicked.connect(self.scan_all)
        self.b_scan_sel = QPushButton(icon("scan_sel"), " Scan selected")
        self.b_scan_sel.clicked.connect(self.scan_selected)
        self.b_del = QPushButton(icon("trash"), " Remove")
        self.b_del.clicked.connect(self.remove_selected)
        h.addWidget(self.add_edit, 1)
        h.addWidget(b_add)
        h.addSpacing(8)
        h.addWidget(self.b_scan)
        h.addWidget(self.b_scan_sel)
        h.addWidget(self.b_del)
        h.addSpacing(8)
        lab = QLabel("WARN WHEN EXPIRING WITHIN")
        lab.setObjectName("cardTitle")
        self.thr = QSpinBox()
        self.thr.setRange(1, 3650)
        self.thr.setSuffix(" days")
        self.thr.setValue(int(self.db.settings.get("threshold_days", 30)))
        self.thr.setFixedWidth(100)
        self.thr.setToolTip("Threshold applied to all certificates. Changing it recolours the table instantly (no rescan).")
        self.thr.valueChanged.connect(self._threshold_changed)
        h.addWidget(lab)
        h.addWidget(self.thr)
        self.b_menu = QToolButton()
        self.b_menu.setIcon(icon("menu"))
        self.b_menu.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(self.b_menu)
        m.addAction(icon("import"), "Import list…", self.import_list)
        m.addAction(icon("export"), "Export CSV…", self.export_csv)
        m.addSeparator()
        self.act_startup = m.addAction("Scan once at program start")
        self.act_startup.setCheckable(True)
        self.act_startup.setChecked(bool(self.db.settings.get("scan_on_start", True)))
        self.act_startup.toggled.connect(self._startup_toggled)
        m.addSeparator()
        m.addAction("Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.db.path.parent))))
        self.b_menu.setMenu(m)
        h.addWidget(self.b_menu)
        v.addWidget(bar)

        # table + details
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([c.upper() for c in COLS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemSelectionChanged.connect(self._show_details)
        self.table.setItemDelegateForColumn(0, StatusDelegate(self.table))
        self.table.setItemDelegateForColumn(2, DaysDelegate(self.table))
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setHighlightSections(False)
        for i, w in enumerate([136, 200, 104, 98, 150, 140, 80, 62, 140]):
            self.table.setColumnWidth(i, w)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setStyleSheet("QTableWidget::item{padding-left:8px;} QTableWidget::item:selected{background:#173a3a;}")

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.empty = QLabel("<div style='text-align:center'><span style='font-size:46px;color:#2a3544'>⛨</span><br>"
                            "<span style='font-size:16px;font-weight:700;color:#d9e1ea'>No domains yet</span><br>"
                            f"<span style='color:{theme.MUTED}'>Type a domain above and press Enter, then <b>Scan all</b>.</span></div>")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setTextFormat(Qt.RichText)
        self.stack.addWidget(self.empty)
        split.addWidget(self.stack)

        self.detail = self._build_detail()
        split.addWidget(self.detail)
        split.setStretchFactor(0, 1)
        split.setSizes([1100, 330])
        v.addWidget(split, 1)

        sb = self.statusBar()
        self.msg = QLabel("")
        self.prog = QProgressBar()
        self.prog.setFixedWidth(220)
        self.prog.setVisible(False)
        sb.addWidget(self.msg, 1)
        sb.addPermanentWidget(self.prog)
        sb.addPermanentWidget(QLabel(f"v{__version__}  ·  {self.db.path}"))
        QShortcut(QKeySequence(Qt.Key_Delete), self.table, activated=self.remove_selected)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.scan_all)
        QShortcut(QKeySequence("F5"), self, activated=self.scan_all)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: (self.add_edit.setFocus(), self.add_edit.selectAll()))

    def _build_detail(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(300)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        t = QLabel("DETAILS")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        self.d_host = QLabel("Select a domain")
        self.d_host.setStyleSheet("font-size:18px; font-weight:800; color:#f1f5f9;")
        self.d_host.setWordWrap(True)
        self.d_host.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.d_pill = Pill()
        self.d_pill.setAlignment(Qt.AlignCenter)
        self.d_pill.hide()
        pr = QHBoxLayout()
        pr.addWidget(self.d_pill)
        pr.addStretch(1)
        self.d_msg = QLabel("")
        self.d_msg.setWordWrap(True)
        lay.addWidget(self.d_host)
        lay.addLayout(pr)
        lay.addWidget(self.d_msg)
        self.d_grid = QGridLayout()
        self.d_grid.setHorizontalSpacing(12)
        self.d_grid.setVerticalSpacing(7)
        self.d_grid.setColumnStretch(1, 1)
        lay.addLayout(self.d_grid)
        self.d_rows: dict[str, QLabel] = {}
        fields = [("expires", "Expires"), ("valid_from", "Valid from"), ("issuer", "Issuer"), ("subject", "Subject"),
                  ("key", "Public key"), ("sig", "Signature"), ("tls", "Protocol"), ("cipher", "Cipher"),
                  ("ip", "Address"), ("lat", "Handshake"), ("serial", "Serial"), ("sha", "SHA-256"), ("scan", "Last scan")]
        for i, (k, name) in enumerate(fields):
            a = QLabel(name.upper())
            a.setObjectName("cardTitle")
            a.setAlignment(Qt.AlignRight | Qt.AlignTop)
            b = QLabel("—")
            b.setWordWrap(True)
            b.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if k in ("serial", "sha"):
                b.setStyleSheet(f"font-family:{theme.MONO}; font-size:11px; color:{theme.MUTED};")
            self.d_grid.addWidget(a, i, 0)
            self.d_grid.addWidget(b, i, 1)
            self.d_rows[k] = b
        s = QLabel("SUBJECT ALTERNATIVE NAMES")
        s.setObjectName("cardTitle")
        lay.addWidget(s)
        self.d_san = QPlainTextEdit()
        self.d_san.setReadOnly(True)
        self.d_san.setMinimumHeight(80)
        lay.addWidget(self.d_san, 1)
        return card

    # ------------------------------------------------------------------ table content
    def threshold(self) -> int:
        return self.thr.value()

    def _entry_of_row(self, row: int) -> Entry | None:
        it = self.table.item(row, 1)
        return self.db.find(*self._split_key(it.data(ROLE_KEY))) if it else None

    @staticmethod
    def _split_key(key: str) -> tuple[str, int]:
        h, _, p = key.rpartition(":")
        return h, int(p)

    def _status_of(self, e: Entry) -> str:
        return "never" if e.key in self.scanning and not e.info.checked_at else e.info.status(self.threshold())

    def _matches_filter(self, status: str) -> bool:
        f = self.filter
        return f == "all" or f == status or (f == "bad" and status in ("invalid", "error"))

    def populate(self) -> None:
        """Rebuilds the whole table (after add/remove/filter). Cheap: tens of rows."""
        sel = {e.key for e in self.selected_entries()}
        self._building = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        thr = self.threshold()
        for e in self.db.entries:
            if not self._matches_filter(e.info.status(thr)):
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c in range(len(COLS)):
                self.table.setItem(r, c, SortItem())
            self._fill_row(r, e)
        self.table.setSortingEnabled(True)
        self._building = False
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1).data(ROLE_KEY) in sel:
                self.table.selectRow(r)
        self._update_tiles()
        self.stack.setCurrentIndex(0 if (self.db.entries or self.filter != "all") else 1)
        self._show_details()

    def _row_of(self, key: str) -> int:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 1).data(ROLE_KEY) == key:
                return r
        return -1

    def _fill_row(self, r: int, e: Entry) -> None:
        info, thr = e.info, self.threshold()
        scanning = e.key in self.scanning
        status = e.info.status(thr)
        color, label = theme.STATUS[status]
        if scanning:
            color, label = theme.INFO, "SCANNING…"
        days = info.days_left()
        tint = {"warn": (251, 191, 36, 16), "expired": (248, 113, 113, 20), "invalid": (251, 146, 60, 14)}.get(status)
        vals = [
            (label, {"never": 5, "ok": 0, "warn": 1, "expired": 2, "invalid": 3, "error": 4}[status]),
            (e.label, e.host),
            ("", days if days is not None else 10**9),
            (fmt_date(info.not_after) if info.has_cert else "—", info.not_after),
            (info.issuer_org or info.issuer_cn or ("—" if info.has_cert else (info.error or "—")), (info.issuer_org or info.issuer_cn).lower()),
            (info.subject_cn or ("—" if info.has_cert else ""), info.subject_cn.lower()),
            (f"{info.key_type.split()[0]} {info.key_size}" if info.key_type else "—", info.key_type),
            (info.tls_version.replace("TLSv", "TLS ") or "—", info.tls_version),
            (fmt_dt(info.checked_at) if info.checked_at else "never", info.checked_at),
        ]
        self._building = True
        for c, (text, sk) in enumerate(vals):
            it = self.table.item(r, c)
            it.setText(text)
            it.setData(ROLE_KEY, e.key)
            it.setData(ROLE_SORT, sk)
            it.setData(Qt.UserRole + 2, color)
            it.setBackground(QColor(*tint) if tint else QColor(0, 0, 0, 0))
            it.setForeground(QColor(theme.TEXT))
            it.setToolTip(info.error or info.trust_error or "")
        self.table.item(r, 1).setForeground(QColor("#f1f5f9"))
        f = self.table.item(r, 1).font()
        f.setBold(True)
        self.table.item(r, 1).setFont(f)
        if not info.has_cert:
            self.table.item(r, 4).setForeground(QColor(theme.MUTED))
        for c in (3, 4, 5, 6, 7, 8):
            if info.has_cert or c == 8:
                self.table.item(r, c).setForeground(QColor(theme.MUTED if c in (6, 7, 8) else theme.TEXT))
        if status in ("expired",):
            self.table.item(r, 3).setForeground(QColor(theme.DANGER))
        self._building = False

    def _update_tiles(self) -> None:
        thr = self.threshold()
        counts = {"all": 0, "ok": 0, "warn": 0, "expired": 0, "bad": 0}
        for e in self.db.entries:
            s = e.info.status(thr)
            counts["all"] += 1
            if s in counts:
                counts[s] += 1
            elif s in ("invalid", "error"):
                counts["bad"] += 1
        for k, t in self.tiles.items():
            t.num.setText(str(counts[k]))
            t.set_active(k == self.filter)
        self.b_scan.setEnabled(bool(self.db.entries))

    def set_filter(self, key: str) -> None:
        self.filter = "all" if key == self.filter else key
        self.populate()

    def refresh_all(self) -> None:
        self.table.setSortingEnabled(False)             # rows must not move while they are being rewritten
        for r in range(self.table.rowCount()):
            e = self._entry_of_row(r)
            if e:
                self._fill_row(r, e)
        self.table.setSortingEnabled(True)
        self._update_tiles()
        self._show_details()

    def _threshold_changed(self, v: int) -> None:
        self.db.settings["threshold_days"] = v
        self.db.save()
        if self.filter != "all":
            self.populate()
        else:
            self.refresh_all()

    def _startup_toggled(self, on: bool) -> None:
        self.db.settings["scan_on_start"] = on
        self.db.save()

    # ------------------------------------------------------------------ details panel
    def selected_entries(self) -> list[Entry]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        out = []
        for r in rows:
            e = self._entry_of_row(r)
            if e:
                out.append(e)
        return out

    def _show_details(self) -> None:
        if self._building:
            return
        sel = self.selected_entries()
        self.b_scan_sel.setEnabled(bool(sel))
        self.b_del.setEnabled(bool(sel))
        if len(sel) != 1:
            self.d_host.setText("Select a domain" if not sel else f"{len(sel)} domains selected")
            self.d_pill.hide()
            self.d_msg.setText("")
            for b in self.d_rows.values():
                b.setText("—")
            self.d_san.setPlainText("")
            return
        e = sel[0]
        i, thr = e.info, self.threshold()
        st = i.status(thr)
        self.d_host.setText(e.label)
        self.d_pill.set_status(st)
        self.d_pill.show()
        d = i.days_left()
        msgs = {"ok": f"{d} days left.", "warn": f"Expires in {d} day(s): inside the {thr}-day threshold.",
                "expired": f"Expired {-d} day(s) ago." if d is not None else "Expired.",
                "invalid": f"Certificate not trusted: {i.trust_error}.", "error": i.error or "Could not retrieve the certificate.",
                "never": "Not scanned yet. Press Scan."}
        text = msgs[st]
        if st == "expired" and i.trust_error and "expired" not in i.trust_error.lower():
            text += f" Also: {i.trust_error}."
        self.d_msg.setText(text)
        self.d_msg.setStyleSheet(f"color:{theme.STATUS[st][0]};")
        R = self.d_rows
        R["expires"].setText(f"{fmt_dt(i.not_after)}  ({d} d)" if i.has_cert else "—")
        R["valid_from"].setText(fmt_dt(i.not_before) if i.has_cert else "—")
        R["issuer"].setText(i.issuer or "—")
        R["subject"].setText(i.subject or "—")
        R["key"].setText(f"{i.key_type} {i.key_size} bit" if i.key_type else "—")
        R["sig"].setText(i.sig_algorithm or "—")
        R["tls"].setText(i.tls_version or "—")
        R["cipher"].setText(i.cipher or "—")
        R["ip"].setText(i.ip or "—")
        R["lat"].setText(f"{i.latency_ms} ms" if i.reachable and i.latency_ms else "—")
        R["serial"].setText(i.serial or "—")
        R["sha"].setText(":".join(re.findall("..", i.sha256)) if i.sha256 else "—")
        R["scan"].setText(fmt_dt(i.checked_at))
        extra = []
        if i.self_signed:
            extra.append("self-signed")
        if i.wildcard:
            extra.append("wildcard")
        if i.has_cert and not i.hostname_match:
            extra.append("hostname mismatch")
        self.d_san.setPlainText("\n".join(i.san) + (("\n\n# " + ", ".join(extra)) if extra else ""))

    # ------------------------------------------------------------------ actions
    def say(self, text: str, error: bool = False) -> None:
        self.msg.setText(text)
        self.msg.setStyleSheet(f"color:{theme.DANGER if error else theme.MUTED};")

    def add_domains(self) -> None:
        parts = [p for p in re.split(r"[\s,;]+", self.add_edit.text()) if p]
        if not parts:
            return
        added, dup, bad, last = 0, 0, [], None
        for p in parts:
            try:
                e, created = self.db.add(p)
            except ValueError:
                bad.append(p)
                continue
            added += created
            dup += not created
            last = e
        if bad:
            self.say(f"Not a valid domain: {', '.join(bad)}", error=True)
            self.add_edit.setText(" ".join(bad))
        else:
            self.add_edit.clear()
            self.say(f"Added {added} domain(s)" + (f", {dup} already present" if dup else "") + ". Press Scan to check them.")
        if self.filter != "all":
            self.filter = "all"
        self.populate()
        if last:
            r = self._row_of(last.key)
            if r >= 0:
                self.table.selectRow(r)
                self.table.scrollToItem(self.table.item(r, 1))

    def remove_selected(self) -> None:
        sel = self.selected_entries()
        if not sel:
            return
        names = ", ".join(e.label for e in sel[:4]) + ("…" if len(sel) > 4 else "")
        if QMessageBox.question(self, "Remove", f"Remove {len(sel)} domain(s) from the list?\n{names}") != QMessageBox.Yes:
            return
        for e in sel:
            self.db.remove(e)
        self.populate()
        self.say(f"Removed {len(sel)} domain(s).")

    def scan_all(self) -> None:
        self._scan(list(self.db.entries))

    def scan_selected(self) -> None:
        self._scan(self.selected_entries())

    def _scan(self, entries: list[Entry]) -> None:
        entries = [e for e in entries if e.key not in self.scanning]
        if not entries:
            return
        if not self.scanning:
            self._batch_total = self._batch_done = 0
        self._batch_total += len(entries)
        self.table.setSortingEnabled(False)
        for e in entries:
            self.scanning.add(e.key)
            r = self._row_of(e.key)
            if r >= 0:
                self._fill_row(r, e)
            self.pool.start(ScanTask(e, self.sig))
        self.table.setSortingEnabled(True)
        self.prog.setRange(0, self._batch_total)
        self.prog.setValue(self._batch_done)
        self.prog.setVisible(True)
        self.say(f"Scanning {len(entries)} domain(s)…")

    def _on_result(self, key: str, info) -> None:
        self.scanning.discard(key)
        self._batch_done += 1
        host, port = self._split_key(key)
        e = self.db.find(host, port)
        if e:                                           # may have been removed meanwhile
            e.info = info
            r = self._row_of(key)
            if r >= 0:
                self.table.setSortingEnabled(False)
                self._fill_row(r, e)
                self.table.setSortingEnabled(True)
        self.prog.setValue(self._batch_done)
        if not self.scanning:
            self.db.save()
            self.prog.setVisible(False)
            self._update_tiles()
            if self.filter != "all":
                self.populate()
            self._show_details()
            bad = sum(1 for x in self.db.entries if x.info.status(self.threshold()) in ("expired", "invalid", "error", "warn"))
            self.say(f"Scan finished at {datetime.now():%H:%M:%S}: {self._batch_total} checked, {bad} need attention.")
        else:
            self._update_tiles()
            if self.selected_entries() and self.selected_entries()[0].key == key:
                self._show_details()

    def startup_scan(self) -> None:
        """Called once after the splash screen: the only automatic scan the program ever does."""
        if self.db.settings.get("scan_on_start", True) and self.db.entries:
            self.scan_all()

    def _context_menu(self, pos) -> None:
        sel = self.selected_entries()
        if not sel:
            return
        m = QMenu(self)
        m.addAction(icon("scan"), "Scan", self.scan_selected)
        if len(sel) == 1:
            e = sel[0]
            m.addAction(icon("copy"), "Copy domain", lambda: QGuiApplication.clipboard().setText(e.label))
            if e.info.sha256:
                m.addAction(icon("copy"), "Copy SHA-256 fingerprint", lambda: QGuiApplication.clipboard().setText(e.info.sha256))
            m.addAction("Open in browser", lambda: QDesktopServices.openUrl(QUrl(f"https://{e.host}" + ("" if e.port == 443 else f":{e.port}"))))
        m.addSeparator()
        m.addAction(icon("trash", theme.DANGER), "Remove", self.remove_selected)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ import / export
    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "certificates.csv", "CSV (*.csv)")
        if not path:
            return
        thr = self.threshold()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["domain", "port", "status", "days_left", "not_before", "not_after", "issuer", "subject",
                        "san", "key", "signature", "tls", "sha256", "error", "checked_at"])
            for e in self.db.entries:
                i = e.info
                w.writerow([e.host, e.port, i.status(thr), i.days_left() if i.has_cert else "", fmt_dt(i.not_before) if i.has_cert else "",
                            fmt_dt(i.not_after) if i.has_cert else "", i.issuer, i.subject, " ".join(i.san),
                            f"{i.key_type} {i.key_size}".strip(), i.sig_algorithm, i.tls_version, i.sha256,
                            i.error or i.trust_error, fmt_dt(i.checked_at) if i.checked_at else ""])
        self.say(f"Exported {len(self.db.entries)} rows to {path}")

    def import_list(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import list", "", "Text / CSV (*.txt *.csv *.list);;All files (*)")
        if not path:
            return
        n = bad = 0
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.split("#", 1)[0].split(",")[0].strip()
                if not line:
                    continue
                try:
                    n += self.db.add(line)[1]
                except ValueError:
                    bad += 1
        self.populate()
        self.say(f"Imported {n} domain(s)" + (f", {bad} lines skipped" if bad else "") + ". Press Scan to check them.")

    # ------------------------------------------------------------------ lifecycle
    def closeEvent(self, ev) -> None:
        self.db.settings["geometry"] = base64.b64encode(bytes(self.saveGeometry())).decode()
        try:
            self.db.save()
        except OSError:
            pass
        self.pool.clear()
        self.pool.waitForDone(3000)
        super().closeEvent(ev)
