"""Visitor events as append-only JSON-lines files, one file per worker process per UTC hour.

The site only ever appends: a line is written with a single write() on a file opened with O_APPEND, so two
threads or a crash can at worst lose a line, never garble another. A file is complete once its hour ended
more than 10 minutes ago or the process moved on to its next file (after max_lines); complete files are
gzipped, and files dated more than keep_days ago are deleted. A separate analytics system copies the
complete files; nothing here reads them back. Logging never raises: on any problem the event is dropped.
"""

import contextvars
import datetime as dt
import gzip
import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import config

LINE_LIMIT = 4096
GRACE = 600  # seconds after an hour ends before its files count as complete
STALE_TMP = 3600
MAINTAIN_EVERY = 600
NAME_RE = re.compile(r"^events-(\d{4}-\d{2}-\d{2})-(\d{2})-(\d+)-(\d+)\.jsonl(\.gz)?$")

log = logging.getLogger("thinkballot.eventlog")
_logs = {}
_logs_lock = threading.Lock()

# The page load (rid) a tracked visitor's request belongs to, so internal events (AI calls) can name it.
current_rid = contextvars.ContextVar("current_rid", default=None)


def enabled():
    """Logging is on for the production copy (or forced for local checks), never on test copies."""
    return config.ANALYTICS == "force" or (config.ANALYTICS == "1" and config.IS_PRODUCTION)


def log_event(event):
    """Append one event (ts in ms added if missing) to this process's file; False if off or dropped."""
    if not enabled():
        return False
    event = dict(event)
    event.setdefault("ts", int(time.time() * 1000))
    return get_log(config.EVENT_LOG_DIR).write(event)


def get_log(directory):
    """One EventLog per directory per process."""
    directory = Path(directory)
    with _logs_lock:
        if directory not in _logs:
            _logs[directory] = EventLog(directory)
        return _logs[directory]


class EventLog:
    def __init__(self, directory, min_free_bytes=5 * 10**9, keep_days=60, max_lines=10_000):
        self.directory = Path(directory)
        self.min_free_bytes, self.keep_days, self.max_lines = min_free_bytes, keep_days, max_lines
        self._lock = threading.Lock()
        self._hour = None  # "YYYY-MM-DD-HH" of the current file
        self._seq = 0
        self._count = 0
        self._free = (0.0, True)  # (checked at, enough space)
        self._last_maintain = None
        self._maint_thread = None
        self._warned = {}

    def _warn(self, kind, message):
        now = time.monotonic()
        if now - self._warned.get(kind, -60) >= 60:
            self._warned[kind] = now
            log.warning("event log: %s", message)

    def free_ok(self):
        checked, ok = self._free
        if time.monotonic() - checked >= 60 or checked == 0.0:
            ok = shutil.disk_usage(self.directory).free >= self.min_free_bytes
            self._free = (time.monotonic(), ok)
        return ok

    def _next_seq(self, hour):
        """For a new hour (or a new process), continue after any file this pid already has for the hour."""
        pid = os.getpid()
        seqs = [int(m.group(4)) for p in self.directory.iterdir()
                if (m := NAME_RE.match(p.name)) and f"{m.group(1)}-{m.group(2)}" == hour and int(m.group(3)) == pid]
        return max(seqs) + 1 if seqs else 0

    def _maybe_maintain(self, now):
        """Start maintenance on a background thread every 10 minutes, so no request ever waits for it."""
        with self._lock:
            if self._last_maintain is not None and now - self._last_maintain < MAINTAIN_EVERY:
                return
            if self._maint_thread is not None and self._maint_thread.is_alive():
                return
            self._last_maintain = now

            def run():
                try:
                    self.maintain(now)
                except Exception as exc:  # noqa: BLE001
                    self._warn("maintain", f"maintenance failed: {exc}")
            self._maint_thread = threading.Thread(target=run, name="eventlog-maintain", daemon=True)
            self._maint_thread.start()

    def wait_maintenance(self, timeout=10):
        """For tests: wait for a running maintenance pass to finish."""
        if self._maint_thread is not None:
            self._maint_thread.join(timeout)

    def write(self, event, now=None):
        now = time.time() if now is None else now
        try:
            self._maybe_maintain(now)  # also while events are being dropped: retention must keep running
        except Exception as exc:  # noqa: BLE001
            self._warn("maintain", f"could not start maintenance: {exc}")
        try:
            event = dict(event)
            event.setdefault("v", 1)
            line = (json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
            if len(line) >= LINE_LIMIT:
                return False
            with self._lock:
                self.directory.mkdir(mode=0o750, parents=True, exist_ok=True)
                if not self.free_ok():
                    self._warn("disk", "free space below the limit; events dropped")
                    return False
                hour = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%d-%H")
                if self._hour is not None and hour < self._hour:
                    hour = self._hour  # stamped just before the hour, written after: never reopen a past hour
                if hour != self._hour:
                    self._hour, self._seq, self._count = hour, self._next_seq(hour), 0
                elif self._count >= self.max_lines:
                    self._seq, self._count = self._seq + 1, 0
                path = self.directory / f"events-{hour}-{os.getpid()}-{self._seq}.jsonl"
                fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
                try:
                    os.write(fd, line)
                finally:
                    os.close(fd)
                self._count += 1
        except Exception as exc:  # noqa: BLE001 - logging must never break a page
            self._warn("write", f"write failed: {exc}")
            return False
        return True

    def maintain(self, now=None):
        now = time.time() if now is None else now
        today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
        cutoff = today - dt.timedelta(days=self.keep_days)
        if not self.directory.is_dir():
            return
        files = []
        for p in self.directory.iterdir():
            m = NAME_RE.match(p.name)
            if not m:
                continue
            day = dt.date.fromisoformat(m.group(1))
            if day < cutoff:
                p.unlink(missing_ok=True)
                continue
            files.append((p, m))
        latest = {}  # (hour, pid) -> highest seq
        for p, m in files:
            key = (f"{m.group(1)}-{m.group(2)}", m.group(3))
            latest[key] = max(latest.get(key, -1), int(m.group(4)))
        for p, m in files:
            if m.group(5):
                continue
            hour = f"{m.group(1)}-{m.group(2)}"
            hour_end = dt.datetime.strptime(hour, "%Y-%m-%d-%H").replace(tzinfo=dt.timezone.utc).timestamp() + 3600
            superseded = int(m.group(4)) < latest[(hour, m.group(3))]
            if now - hour_end > GRACE or superseded:
                self._compress(p)

    def _compress(self, path):
        gz = path.with_name(path.name + ".gz")
        tmp = path.with_name(path.name + ".gz.tmp")
        if gz.exists():
            if path.exists():
                path.unlink(missing_ok=True)  # an earlier run finished the gzip but not the removal
            return
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError:
            try:
                if time.time() - tmp.stat().st_mtime > STALE_TMP:
                    tmp.unlink(missing_ok=True)  # a crashed attempt; the next run starts again
            except FileNotFoundError:
                pass
            return
        try:
            data = path.read_bytes()
            with os.fdopen(fd, "wb") as out:
                out.write(gzip.compress(data))
            if gzip.decompress(tmp.read_bytes()) != data:
                raise OSError("gzip check failed")
            os.replace(tmp, gz)
            path.unlink(missing_ok=True)
        except FileNotFoundError:
            tmp.unlink(missing_ok=True)  # the other worker finished first
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
