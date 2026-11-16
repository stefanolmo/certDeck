import json

from certdeck.checker import CertInfo
from certdeck.db import Database


def test_persistence(tmp_path):
    p = tmp_path / "sub" / "db.json"
    db = Database(p)
    assert not db.existed and db.entries == []
    e, created = db.add("https://Example.com/")
    assert created and e.key == "example.com:443"
    assert db.add("example.com")[1] is False
    db.add("host:8443")
    e.info = CertInfo(checked_at=5.0, subject_cn="example.com", not_after=99.0, san=["example.com"])
    db.settings["threshold_days"] = 45
    db.save()
    db2 = Database(p)
    assert db2.existed
    assert [x.key for x in db2.entries] == ["example.com:443", "host:8443"]
    assert db2.entries[0].info.subject_cn == "example.com" and db2.entries[0].info.san == ["example.com"]
    assert db2.settings["threshold_days"] == 45 and db2.settings["scan_on_start"] is True
    db2.remove(db2.entries[0])
    assert [x.key for x in Database(p).entries] == ["host:8443"]


def test_corrupt_file_is_kept(tmp_path):
    p = tmp_path / "db.json"
    p.write_text("{not json")
    db = Database(p)
    assert db.entries == []
    assert (tmp_path / "db.json.corrupt").exists()


def test_tolerates_bad_rows(tmp_path):
    p = tmp_path / "db.json"
    p.write_text(json.dumps({"domains": [{"host": "a.com"}, {"nohost": 1}, {"host": "b.com", "port": "x"}]}))
    assert [e.key for e in Database(p).entries] == ["a.com:443"]
