"""Date-partitioned complete PubMed download with durable per-window checkpoints.

Never declare a search complete without count reconciliation. Changes in the live
PubMed index can cause count mismatch and require starting a new search.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from pubmed import SearchInfo, iter_pubmed_batches, search_window

MAX_WINDOW = 9000  # margin below the strict 10,000-record ESearch limit


class IncompleteSearchError(RuntimeError):
    """No silent truncation: search cannot be certified complete."""


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    count: int

    @property
    def label(self):
        return f"{self.start.isoformat()} – {self.end.isoformat()}"


def split_range(start: date, end: date) -> tuple[tuple[date, date], tuple[date, date]]:
    if start >= end:
        raise IncompleteSearchError(f"Cannot split single day {start} further by publication date.")
    mid = start + timedelta(days=(end - start).days // 2)
    return (start, mid), (mid + timedelta(days=1), end)


def plan_windows(session, query: str, start: date, end: date,
                 on_event: Callable[[str], None] | None = None,
                 search_fn=search_window) -> tuple[SearchInfo, list[Window]]:
    root = search_fn(session, query, start, end)
    windows: list[Window] = []

    def visit(left: date, right: date, info: SearchInfo):
        if info.count <= MAX_WINDOW:
            if info.count:
                windows.append(Window(left, right, info.count))
            return
        if left == right:
            raise IncompleteSearchError(
                f"More than {MAX_WINDOW:,} hits occur on {left}. "
                "This case cannot be exhaustively split by day. Refine the query; no truncated result is labeled complete."
            )
        for a, b in split_range(left, right):
            part = search_fn(session, query, a, b)
            if on_event:
                on_event(f"Planning {a} – {b}: {part.count:,} matches")
            visit(a, b, part)

    visit(start, end, root)
    if sum(w.count for w in windows) != root.count:
        raise IncompleteSearchError(
            "Sub-window counts do not equal the full query count. PubMed date boundaries "
            "or index updates may have affected results. No search will be marked complete."
        )
    return root, windows


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_run_id(query: str, start_year: int, end_year: int) -> str:
    spec = json.dumps({"query": query.strip(), "start": start_year, "end": end_year}, sort_keys=True)
    return hashlib.sha256(spec.encode()).hexdigest()[:20]


class SearchStore:
    """Local SQLite persistence; each finished window is committed atomically."""
    def __init__(self, location: Path | str):
        self.path = Path(location)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, query TEXT NOT NULL, first_year INTEGER NOT NULL,
            last_year INTEGER NOT NULL, expected INTEGER NOT NULL,
            searched_at TEXT NOT NULL, translated TEXT NOT NULL,
            status TEXT NOT NULL, updated TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS windows (
            run_id TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
            expected INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            PRIMARY KEY(run_id,start,end)
        );
        CREATE TABLE IF NOT EXISTS records (
            run_id TEXT NOT NULL, pmid TEXT NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY(run_id,pmid)
        );
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def clear(self, run_id: str):
        with self.db:
            for table, where in (("records", "run_id"), ("windows", "run_id"), ("runs", "id")):
                self.db.execute(f"DELETE FROM {table} WHERE {where}=?", (run_id,))

    def create(self, run_id: str, query: str, start_year: int, end_year: int,
               root: SearchInfo, windows: list[Window]):
        if self.run(run_id) is not None:
            raise ValueError("Run already exists; resume or start fresh.")
        with self.db:
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                            (run_id, query, start_year, end_year, root.count, root.searched_at,
                             root.query, "running", _utc()))
            self.db.executemany("INSERT INTO windows VALUES(?,?,?,?,?)",
                                [(run_id, w.start.isoformat(), w.end.isoformat(), w.count, "pending")
                                 for w in windows])

    def run(self, run_id):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def windows(self, run_id):
        rows = self.db.execute("SELECT * FROM windows WHERE run_id=? ORDER BY start", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def record_count(self, run_id):
        return self.db.execute("SELECT COUNT(*) FROM records WHERE run_id=?", (run_id,)).fetchone()[0]

    def checkpoint(self, run_id: str, window: dict, records: list[dict]):
        """Do not commit incomplete or duplicate windows."""
        if len(records) != window["expected"]:
            raise IncompleteSearchError(
                f"{window['start']}–{window['end']}: got {len(records)} records, expected {window['expected']}.")
        ids = [str(row.get("PMID", "")) for row in records]
        if not all(ids) or len(set(ids)) != len(ids):
            raise IncompleteSearchError("Missing or duplicate PMIDs in a PubMed window.")
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO records VALUES(?,?,?)",
                                [(run_id, pid, json.dumps(item, ensure_ascii=False))
                                 for pid, item in zip(ids, records)])
            self.db.execute("UPDATE windows SET status='done' WHERE run_id=? AND start=? AND end=?",
                            (run_id, window["start"], window["end"]))
            self.db.execute("UPDATE runs SET updated=? WHERE id=?", (_utc(), run_id))

    def finalize(self, run_id: str) -> bool:
        run = self.run(run_id)
        windows = self.windows(run_id)
        complete = (all(w["status"] == "done" for w in windows)
                    and sum(w["expected"] for w in windows) == run["expected"]
                    and self.record_count(run_id) == run["expected"])
        with self.db:
            self.db.execute("UPDATE runs SET status=?,updated=? WHERE id=?",
                            ("complete" if complete else "incomplete", _utc(), run_id))
        return complete

    def iter_records(self, run_id: str):
        cursor = self.db.execute("SELECT data FROM records WHERE run_id=? ORDER BY CAST(pmid AS INTEGER)", (run_id,))
        for (data,) in cursor:
            yield json.loads(data)

    def sample(self, run_id: str, limit: int = 100):
        rows = self.db.execute("SELECT data FROM records WHERE run_id=? LIMIT ?", (run_id, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]


def execute_full_search(session, store: SearchStore, query: str, first_year: int,
                        last_year: int, *, fresh: bool = False,
                        on_event: Callable[[str], None] | None = None,
                        on_progress: Callable[[int, int], None] | None = None,
                        search_fn=search_window, batch_fn=iter_pubmed_batches):
    if not 1800 <= first_year <= last_year <= 2100:
        raise ValueError("Invalid publication-year range.")
    start, end = date(first_year, 1, 1), date(last_year, 12, 31)
    run_id = get_run_id(query, first_year, last_year)
    if fresh:
        store.clear(run_id)
    current = store.run(run_id)
    if current is None:
        if on_event:
            on_event("Checking full PubMed count and planning sub-10,000 search windows…")
        root, partitions = plan_windows(session, query, start, end, on_event, search_fn)
        store.create(run_id, query.strip(), first_year, last_year, root, partitions)
    else:
        if on_event:
            on_event(f"Resuming existing job from {current['searched_at']}; completed windows will be skipped.")

    windows = store.windows(run_id)
    completed = sum(w["expected"] for w in windows if w["status"] == "done")
    total = store.run(run_id)["expected"]
    if on_progress:
        on_progress(completed, total)
    for w in windows:
        if w["status"] == "done":
            continue
        left, right = date.fromisoformat(w["start"]), date.fromisoformat(w["end"])
        info = search_fn(session, query, left, right)  # refresh expired History token
        if info.count != w["expected"]:
            raise IncompleteSearchError(
                f"PubMed changed for {w['start']}–{w['end']} since planning "
                f"({w['expected']} → {info.count}). Saved windows remain intact. "
                "Start a fresh run for a consistent new count.")
        if on_event:
            on_event(f"Fetching {w['start']} – {w['end']} ({info.count:,})")
        fetched = []
        for batch, position, expected in batch_fn(session, info):
            fetched.extend(batch)
            if on_progress:
                on_progress(completed + position, total)
        store.checkpoint(run_id, w, fetched)
        completed += w["expected"]

    if not store.finalize(run_id):
        raise IncompleteSearchError(
            f"Expected {total:,} matches, but only {store.record_count(run_id):,} unique PMIDs are stored. "
            "This job is INCOMPLETE (possibly overlapping PubMed date assignments or live index updates)."
        )
    return run_id
