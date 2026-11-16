"""File-based database: one JSON file with the domain list, the last scan results and the settings."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .checker import CertInfo, DEFAULT_PORT, parse_target

DEFAULTS = {"threshold_days": 30, "scan_on_start": True}


def default_path() -> Path:
    base = os.environ.get("CERTDECK_DB")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(xdg) / "certdeck" / "certdeck.json"


@dataclass
class Entry:
    host: str
    port: int = DEFAULT_PORT
    note: str = ""
    info: CertInfo = field(default_factory=CertInfo)

    @property
    def key(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def label(self) -> str:
        return self.host if self.port == DEFAULT_PORT else self.key


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.entries: list[Entry] = []
        self.settings: dict = dict(DEFAULTS)
        self.existed = self.path.exists()
        self.load()

    # ------------------------------------------------------------------ persistence
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            # corrupted file: keep a copy instead of silently overwriting it
            try:
                self.path.replace(self.path.with_suffix(".json.corrupt"))
            except OSError:
                pass
            return
        self.settings.update(data.get("settings", {}))
        for d in data.get("domains", []):
            try:
                self.entries.append(Entry(d["host"], int(d.get("port", DEFAULT_PORT)), d.get("note", ""),
                                          CertInfo.from_dict(d.get("info", {}))))
            except (KeyError, TypeError, ValueError):
                continue

    def save(self) -> None:
        """Atomic write (temp file + rename): a crash never leaves a half-written database."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "settings": self.settings,
                "domains": [{"host": e.host, "port": e.port, "note": e.note, "info": e.info.to_dict()}
                            for e in self.entries]}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".certdeck-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ domains
    def find(self, host: str, port: int) -> Entry | None:
        return next((e for e in self.entries if e.host == host and e.port == port), None)

    def add(self, text: str) -> tuple[Entry, bool]:
        """Adds a domain ('host', 'host:port' or a URL). Returns (entry, created). Raises ValueError."""
        host, port = parse_target(text)
        e = self.find(host, port)
        if e:
            return e, False
        e = Entry(host, port)
        self.entries.append(e)
        self.save()
        return e, True

    def remove(self, entry: Entry) -> None:
        self.entries.remove(entry)
        self.save()
