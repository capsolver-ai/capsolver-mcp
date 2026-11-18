"""SQLite atomic claims coordinate submission deduplication and query budgets."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


class TaskStore:
    """Records are account/scope-bound. Multiple instances may share one database."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            file = Path(path).expanduser()
            file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(file, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            path = file
        self._db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS task_records (
                scope TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                task_id TEXT, mode TEXT NOT NULL DEFAULT 'async', state TEXT NOT NULL,
                created_at REAL NOT NULL, query_count INTEGER NOT NULL DEFAULT 0,
                next_query_at REAL NOT NULL DEFAULT 0, error_code TEXT,
                PRIMARY KEY(scope, request_id), UNIQUE(scope, task_id)
            )
        """)
        # Serialize schema migration across processes sharing an existing ledger.
        self._db.execute("BEGIN IMMEDIATE")
        try:
            columns = {row["name"] for row in self._db.execute("PRAGMA table_info(task_records)")}
            if "submission_deadline" not in columns:
                self._db.execute("ALTER TABLE task_records ADD COLUMN submission_deadline REAL")
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def get(self, scope: str, request_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT * FROM task_records WHERE scope=? AND request_id=?", (scope, request_id)
        ).fetchone()
        if row is None:
            raise KeyError("Task record was not found in this account and scope.")
        return dict(row)

    def by_task_id(self, scope: str, task_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM task_records WHERE scope=? AND task_id=?", (scope, task_id)).fetchone()
        if row is None:
            raise KeyError("Task ID was not found in this account and scope.")
        return dict(row)

    def claim(self, scope: str, request_id: str, fingerprint: str, now: float,
              *, submission_deadline: float | None = None) -> tuple[dict[str, Any], bool]:
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO task_records(scope,request_id,fingerprint,state,created_at,submission_deadline) VALUES(?,?,?,'submitting',?,?)",
            (scope, request_id, fingerprint, now, submission_deadline),
        )
        record = self.get(scope, request_id)
        if record["fingerprint"] != fingerprint:
            raise ValueError("Request ID was already used with different parameters.")
        return record, cursor.rowcount == 1

    def expire_submission(self, scope: str, request_id: str, now: float,
                          *, legacy_timeout: float) -> dict[str, Any]:
        self._db.execute(
            """UPDATE task_records SET state='acceptance_unknown',error_code='SUBMISSION_OUTCOME_UNKNOWN'
            WHERE scope=? AND request_id=? AND state='submitting'
              AND COALESCE(submission_deadline,created_at+?+1)<?""",
            (scope, request_id, legacy_timeout, now),
        )
        return self.get(scope, request_id)

    def update(self, scope: str, request_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"task_id", "mode", "state", "next_query_at", "error_code"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid task metadata update.")
        self._db.execute(
            "UPDATE task_records SET " + ",".join(k + "=?" for k in fields) + " WHERE scope=? AND request_id=?",
            (*fields.values(), scope, request_id),
        )
        return self.get(scope, request_id)

    def reserve_query(
        self, scope: str, request_id: str, now: float, *, lease: float, max_queries: int, max_age: float
    ) -> bool:
        result = self._db.execute(
            """
            UPDATE task_records SET query_count=query_count+1,next_query_at=?
            WHERE scope=? AND request_id=? AND state IN ('processing','ready')
              AND task_id IS NOT NULL AND next_query_at<=? AND query_count<? AND created_at>?
        """,
            (now + lease, scope, request_id, now, max_queries, now - max_age),
        )
        return result.rowcount == 1
