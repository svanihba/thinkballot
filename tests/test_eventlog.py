"""Event log files: hourly append-only JSON lines per process, gzip of complete files, 60-day deletion."""

import datetime as dt
import gzip
import json
import multiprocessing
import os
import threading
import time

from thinkballot.eventlog import EventLog


def at(y, mo, d, h=0, mi=0, sec=0):
    return dt.datetime(y, mo, d, h, mi, sec, tzinfo=dt.timezone.utc).timestamp()


NOW = at(2026, 10, 30, 14, 30)
PID = os.getpid()


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_write_appends_one_json_line_per_event(tmp_path):
    log = EventLog(tmp_path)
    assert log.write({"type": "pageview", "path": "/é"}, now=NOW)
    assert log.write({"type": "click", "props": {"label": "中"}}, now=NOW)
    rows = lines(tmp_path / f"events-2026-10-30-14-{PID}-0.jsonl")
    assert [r["type"] for r in rows] == ["pageview", "click"]
    assert all(r["v"] == 1 for r in rows)
    assert rows[0]["path"] == "/é" and rows[1]["props"]["label"] == "中"
    assert "中" in (tmp_path / f"events-2026-10-30-14-{PID}-0.jsonl").read_text(encoding="utf-8")


def test_file_name_uses_utc_hour(tmp_path):
    log = EventLog(tmp_path)
    log.write({"type": "a"}, now=at(2026, 10, 31, 6, 30))
    log.write({"type": "b"}, now=at(2026, 10, 31, 7, 0))
    assert (tmp_path / f"events-2026-10-31-06-{PID}-0.jsonl").exists()
    assert (tmp_path / f"events-2026-10-31-07-{PID}-0.jsonl").exists()


def test_new_file_after_max_lines(tmp_path):
    log = EventLog(tmp_path, max_lines=3)
    for i in range(7):
        log.write({"type": "e", "i": i}, now=NOW)
    counts = [len(lines(tmp_path / f"events-2026-10-30-14-{PID}-{s}.jsonl")) for s in range(3)]
    assert counts == [3, 3, 1]


def test_new_instance_continues_after_highest_seq(tmp_path):
    EventLog(tmp_path, max_lines=1).write({"type": "a"}, now=NOW)
    EventLog(tmp_path, max_lines=1).write({"type": "b"}, now=NOW)
    assert (tmp_path / f"events-2026-10-30-14-{PID}-1.jsonl").exists()


def test_oversize_line_is_dropped(tmp_path):
    log = EventLog(tmp_path)
    assert not log.write({"type": "x", "big": "a" * 5000}, now=NOW)
    assert not list(tmp_path.glob("*.jsonl")) or all(p.stat().st_size == 0 for p in tmp_path.glob("*.jsonl"))


def test_disk_guard_drops_events(tmp_path):
    log = EventLog(tmp_path, min_free_bytes=10**18)
    assert not log.write({"type": "x"}, now=NOW)
    assert not list(tmp_path.glob("*.jsonl"))


def test_write_never_raises_on_unwritable_dir(tmp_path):
    f = tmp_path / "not-a-dir"
    f.write_text("x")
    assert not EventLog(f).write({"type": "x"}, now=NOW)


def test_files_and_directory_are_not_world_readable(tmp_path):
    d = tmp_path / "events"
    EventLog(d).write({"type": "x"}, now=NOW)
    assert d.stat().st_mode & 0o007 == 0
    assert all(p.stat().st_mode & 0o007 == 0 for p in d.iterdir())


def _worker(directory, n_threads, n_writes):
    log = EventLog(directory)

    def run():
        for i in range(n_writes):
            log.write({"type": "load", "pad": "x" * 1000, "i": i})
    threads = [threading.Thread(target=run) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_threads_and_processes_write_whole_lines(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_worker, args=(tmp_path, 8, 500)) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    total = 0
    for path in tmp_path.glob("events-*.jsonl"):
        rows = lines(path)  # every line parses
        total += len(rows)
    assert total == 2 * 8 * 500


def _make(tmp_path, name, rows=2):
    p = tmp_path / name
    p.write_text("".join(json.dumps({"v": 1, "i": i}) + "\n" for i in range(rows)))
    return p


def test_maintain_gzips_complete_files_only(tmp_path):
    h13 = _make(tmp_path, "events-2026-10-30-13-111-0.jsonl")
    h14 = _make(tmp_path, "events-2026-10-30-14-111-0.jsonl")
    original = h13.read_bytes()
    log = EventLog(tmp_path)
    log.maintain(now=at(2026, 10, 30, 14, 5))  # within the 10-minute grace
    assert h13.exists() and not (tmp_path / (h13.name + ".gz")).exists()
    log.maintain(now=at(2026, 10, 30, 14, 11))
    assert not h13.exists()
    assert gzip.decompress((tmp_path / (h13.name + ".gz")).read_bytes()) == original
    assert h14.exists() and not (tmp_path / (h14.name + ".gz")).exists()


def test_maintain_gzips_a_full_file_once_the_next_one_exists(tmp_path):
    s0 = _make(tmp_path, "events-2026-10-30-14-111-0.jsonl")
    s1 = _make(tmp_path, "events-2026-10-30-14-111-1.jsonl")
    EventLog(tmp_path).maintain(now=NOW)
    assert not s0.exists() and (tmp_path / (s0.name + ".gz")).exists()
    assert s1.exists()


def test_maintain_skips_fresh_tmp_and_clears_stale_tmp(tmp_path):
    f = _make(tmp_path, "events-2026-10-30-12-111-0.jsonl")
    tmp = tmp_path / (f.name + ".gz.tmp")
    tmp.write_bytes(b"partial")
    log = EventLog(tmp_path)
    log.maintain(now=NOW)
    assert f.exists() and tmp.exists()  # another worker may be compressing it right now
    old = time.time() - 7200
    os.utime(tmp, (old, old))
    log.maintain(now=NOW)
    assert f.exists() and not tmp.exists()  # a crashed attempt is cleared, the data kept
    log.maintain(now=NOW)
    assert not f.exists() and (tmp_path / (f.name + ".gz")).exists()


def test_retention_deletes_files_older_than_60_days(tmp_path):
    today = dt.date(2026, 10, 30)

    def name(days_ago, ext):
        d = today - dt.timedelta(days=days_ago)
        return f"events-{d.isoformat()}-10-111-0{ext}"
    old = tmp_path / name(61, ".jsonl.gz")
    old.write_bytes(gzip.compress(b"{}\n"))
    edge = tmp_path / name(60, ".jsonl.gz")
    edge.write_bytes(gzip.compress(b"{}\n"))
    recent = _make(tmp_path, name(1, ".jsonl"))
    EventLog(tmp_path).maintain(now=NOW)
    assert not old.exists() and edge.exists()
    assert (tmp_path / (recent.name + ".gz")).exists()


def test_write_runs_maintenance(tmp_path):
    stale = _make(tmp_path, "events-2026-10-29-01-111-0.jsonl")
    log = EventLog(tmp_path)
    log.write({"type": "x"}, now=NOW)
    log.wait_maintenance()
    assert not stale.exists() and (tmp_path / (stale.name + ".gz")).exists()


def test_retention_runs_even_when_disk_guard_drops_events(tmp_path):
    old = tmp_path / "events-2026-08-01-10-111-0.jsonl.gz"
    old.write_bytes(gzip.compress(b"{}\n"))
    log = EventLog(tmp_path, min_free_bytes=10**18)
    assert not log.write({"type": "x"}, now=NOW)
    log.wait_maintenance()
    assert not old.exists()


def test_maintenance_never_delays_a_write(tmp_path, monkeypatch):
    log = EventLog(tmp_path)
    monkeypatch.setattr(log, "maintain", lambda now=None: time.sleep(1))
    started = time.monotonic()
    assert log.write({"type": "x"}, now=NOW)
    assert time.monotonic() - started < 0.5
    log.wait_maintenance()


def test_a_late_thread_never_moves_back_an_hour(tmp_path):
    log = EventLog(tmp_path)
    log.write({"type": "a"}, now=at(2026, 10, 30, 14, 0, 0))
    log.write({"type": "b"}, now=at(2026, 10, 30, 13, 59))  # stamped just before the hour, written after
    log.write({"type": "c"}, now=at(2026, 10, 30, 14, 0, 1))
    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == [f"events-2026-10-30-14-{PID}-0.jsonl"]
