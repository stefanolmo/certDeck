"""Animated splash screen: a chain of certificates rises, a scan ring sweeps and the check mark is drawn."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from . import theme

W, H = 780, 440
CREDITS = "Stefano Ciurleo & Claude Code - 2026"
ORIGIN = (W * 0.68, H * 0.60)


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class SplashScreen(QWidget):
    finished = Signal()

    def __init__(self, version: str, duration_ms: int = 3000, parent=None):
        super().__init__(parent)
        self.version = version
        self.duration = duration_ms
        self.t = 0.0                       # elapsed ms (set_time() overrides it for stills)
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self._clock = QElapsedTimer()
        self._tick = QTimer(self, interval=16)
        self._tick.timeout.connect(self._advance)
        yaw, pitch = math.radians(-35), math.radians(55)
        cz, sz, cx, sx = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
        rx = np.array([[1, 0, 0], [0, cx, sx], [0, -sx, cx]])
        self._rot = rx @ rz

    def _proj(self, pts, origin=ORIGIN) -> np.ndarray:
        q = np.atleast_2d(np.asarray(pts, float)) @ self._rot.T
        return np.column_stack([origin[0] + q[:, 0], origin[1] - q[:, 1]])

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.center().x() - W // 2, g.center().y() - H // 2)
        self.show()
        self.raise_()
        self._clock.start()
        self._tick.start()

    def _advance(self) -> None:
        self.t = float(self._clock.elapsed())
        if self.t >= self.duration:
            self._tick.stop()
            self.close()
            self.finished.emit()
            return
        self.update()

    def set_time(self, ms: float) -> None:
        self.t = ms
        self.update()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self.t / max(self.duration, 1)
        fade_in = _ease(self.t / 350.0)
        fade_out = 1.0 - _ease((self.t - (self.duration - 300)) / 300.0)
        p.setOpacity(max(0.0, min(fade_in, fade_out)))
        self._paint_card(p)
        self._paint_grid(p)
        self._paint_chain(p, k)
        self._paint_text(p)
        self._paint_progress(p, k)
        p.end()

    def _paint_card(self, p: QPainter) -> None:
        rect = QRectF(8, 8, W - 16, H - 16)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        glow = QRadialGradient(QPointF(W * 0.68, H * 0.45), W * 0.62)
        glow.setColorAt(0, QColor(45, 212, 191, 38))
        glow.setColorAt(1, QColor(45, 212, 191, 0))
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor("#141b24"))
        g.setColorAt(1, QColor("#0a0e13"))
        p.fillPath(path, g)
        p.fillPath(path, QBrush(glow))
        p.setPen(QPen(QColor(theme.BORDER), 1.5))
        p.drawPath(path)
        p.setClipPath(path)

    def _paint_grid(self, p: QPainter) -> None:
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        span, step = 220, 22
        for v in range(-span, span + 1, step):
            a = self._proj([[v, -span, -45.0], [v, span, -45.0]])
            b = self._proj([[-span, v, -45.0], [span, v, -45.0]])
            p.drawLine(QPointF(*a[0]), QPointF(*a[1]))
            p.drawLine(QPointF(*b[0]), QPointF(*b[1]))
        fade = QLinearGradient(0, 0, W * 0.55, 0)
        fade.setColorAt(0, QColor("#0e1319"))
        fade.setColorAt(1, QColor(14, 19, 25, 0))
        p.fillRect(QRectF(0, 0, W * 0.55, H), fade)

    def _plate_path(self, z: float, hw=92.0, hh=62.0, off=(0.0, 0.0)) -> QPainterPath:
        pts = self._proj([[off[0] - hw, off[1] - hh, z], [off[0] + hw, off[1] - hh, z],
                          [off[0] + hw, off[1] + hh, z], [off[0] - hw, off[1] + hh, z]])
        path = QPainterPath(QPointF(*pts[0]))
        for q in pts[1:]:
            path.lineTo(*q)
        path.closeSubpath()
        return path

    def _paint_chain(self, p: QPainter, k: float) -> None:
        # three plates: root CA, intermediate CA, leaf. They rise one after another.
        levels = [(-30.0, "#64748b", 0.00), (20.0, "#38bdf8", 0.16), (70.0, theme.ACCENT, 0.32)]
        # vertical link between the plates
        for i in range(2):
            a, b = levels[i], levels[i + 1]
            prog = _ease((k - b[2] - 0.12) / 0.12)
            if prog > 0:
                z0, z1 = a[0], a[0] + (b[0] - a[0]) * prog
                ln = self._proj([[0, 0, z0], [0, 0, z1]])
                p.setPen(QPen(QColor(255, 255, 255, 70), 1.6, Qt.DashLine))
                p.drawLine(QPointF(*ln[0]), QPointF(*ln[1]))
        for i, (z, col, t0) in enumerate(levels):
            rise = _ease((k - t0) / 0.2)
            if rise <= 0:
                continue
            zz = z - (1 - rise) * 40
            path = self._plate_path(zz)
            c = QColor(col)
            # shadow on the grid
            p.save()
            p.setOpacity(p.opacity() * rise)
            sh = self._plate_path(-45.0)
            p.fillPath(sh, QColor(0, 0, 0, 40))
            fillc = QColor(c)
            fillc.setAlpha(46 if i < 2 else 70)
            p.fillPath(path, fillc)
            p.setPen(QPen(c, 2.0))
            p.drawPath(path)
            # text lines on the plate
            p.setPen(QPen(QColor(255, 255, 255, 60), 2.2, Qt.SolidLine, Qt.RoundCap))
            for j, (x0, x1) in enumerate([(-70, 10), (-70, 40), (-70, -15)]):
                ln = self._proj([[x0, -34 + j * 14, zz], [x1, -34 + j * 14, zz]])
                p.drawLine(QPointF(*ln[0]), QPointF(*ln[1]))
            # seal
            seal = self._proj([[58, 30, zz]])[0]
            p.setPen(QPen(c, 2))
            p.setBrush(QColor(c.red(), c.green(), c.blue(), 60))
            p.drawEllipse(QPointF(*seal), 9, 6)
            p.restore()
        # scan ring sweeping over the leaf plate
        sw = (k - 0.45) / 0.45
        if 0 < sw < 1:
            r = 20 + 150 * _ease(sw)
            t = np.linspace(0, 2 * math.pi, 120)
            ring = self._proj(np.column_stack([r * np.cos(t), r * np.sin(t), np.full_like(t, 70.0)]))
            p.setPen(QPen(QColor(45, 212, 191, int(200 * (1 - sw))), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline([QPointF(*q) for q in ring])
        # check mark drawn on the leaf plate + glow
        ck = _ease((k - 0.62) / 0.22)
        if ck > 0:
            z = 70.0
            c0 = self._proj([[0, 0, z]])[0]
            pts = np.array([[c0[0] - 26, c0[1] + 2], [c0[0] - 9, c0[1] + 18], [c0[0] + 28, c0[1] - 16]])
            tip_glow = QRadialGradient(QPointF(*self._proj([[0, 0, z]])[0]), 90)
            tip_glow.setColorAt(0, QColor(45, 212, 191, int(70 * ck)))
            tip_glow.setColorAt(1, QColor(45, 212, 191, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(tip_glow))
            p.drawEllipse(QPointF(*self._proj([[0, 0, z]])[0]), 90, 90)
            seg = [QPointF(*pts[0]), QPointF(*pts[1]), QPointF(*pts[2])]
            l1, l2 = np.hypot(*(pts[1] - pts[0])), np.hypot(*(pts[2] - pts[1]))
            d = ck * (l1 + l2)
            path = QPainterPath(seg[0])
            if d <= l1:
                f = d / l1
                path.lineTo(QPointF(*(pts[0] + (pts[1] - pts[0]) * f)))
            else:
                path.lineTo(seg[1])
                f = (d - l1) / l2
                path.lineTo(QPointF(*(pts[1] + (pts[2] - pts[1]) * f)))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#04211d"), 11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(theme.ACCENT), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

    def _paint_text(self, p: QPainter) -> None:
        x = 58
        f = QFont("sans", 46, QFont.Black)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.setPen(QColor("#f1f5f9"))
        p.drawText(QPointF(x, H * 0.47), "Cert")
        w = p.fontMetrics().horizontalAdvance("Cert ")
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QPointF(x + w, H * 0.47), "Deck")
        p.setPen(Qt.NoPen)
        g = QLinearGradient(x, 0, x + 230, 0)
        g.setColorAt(0, QColor(theme.ACCENT))
        g.setColorAt(1, QColor(45, 212, 191, 0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(x, H * 0.47 + 16, 230, 3), 1.5, 1.5)
        p.setFont(QFont("sans", 11))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QPointF(x + 2, H * 0.47 + 50), CREDITS)
        p.setFont(QFont("sans", 10, QFont.DemiBold))
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QPointF(x + 2, H * 0.47 + 76), f"Version {self.version}")
        p.setFont(QFont("sans", 8))
        p.setPen(QColor(255, 255, 255, 70))
        p.drawText(QPointF(x + 2, H - 38), "TLS certificate monitor  ·  expiry, chain and trust at a glance")

    def _paint_progress(self, p: QPainter, k: float) -> None:
        x0, x1, y = 58.0, W - 58.0, H - 24.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(x0, y, x1 - x0, 3), 1.5, 1.5)
        g = QLinearGradient(x0, 0, x1, 0)
        g.setColorAt(0, QColor(theme.ACCENT))
        g.setColorAt(1, QColor("#38bdf8"))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(x0, y, (x1 - x0) * min(k, 1.0), 3), 1.5, 1.5)
