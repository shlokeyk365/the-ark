"""SQLite persistence for immutable simulation runs and reports."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

JsonObject = Dict[str, Any]


class ReportRepository:
    """Store complete run payloads without coupling domain services to SQL."""

    def __init__(self, database_path: Union[str, Path]) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[sqlite3.Connection] = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.database_path == ":memory:":
            if self._connection is None:
                self._connection = sqlite3.connect(":memory:", check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
            return self._connection
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_runs (
                    run_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL UNIQUE,
                    scenario_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    report_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS simulation_runs_completed_at
                ON simulation_runs(completed_at DESC)
                """
            )
            connection.commit()
        finally:
            if self.database_path != ":memory:":
                connection.close()

    def save_run(self, run: JsonObject) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO simulation_runs (
                    run_id, report_id, scenario_id, status, started_at,
                    completed_at, input_fingerprint, run_json, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["report_id"],
                    run["scenario_id"],
                    run["status"],
                    run["started_at"],
                    run["completed_at"],
                    run["input_fingerprint"],
                    json.dumps(run, separators=(",", ":"), sort_keys=True),
                    json.dumps(run["report"], separators=(",", ":"), sort_keys=True),
                ),
            )
            connection.commit()
        finally:
            if self.database_path != ":memory:":
                connection.close()

    def get_run(self, run_id: str) -> Optional[JsonObject]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT run_json FROM simulation_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return json.loads(row["run_json"]) if row else None
        finally:
            if self.database_path != ":memory:":
                connection.close()

    def get_report(self, report_id: str) -> Optional[JsonObject]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT report_json FROM simulation_runs WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            return json.loads(row["report_json"]) if row else None
        finally:
            if self.database_path != ":memory:":
                connection.close()

    def list_runs(self, limit: int = 50) -> List[JsonObject]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT run_json FROM simulation_runs
                ORDER BY completed_at DESC, run_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [json.loads(row["run_json"]) for row in rows]
        finally:
            if self.database_path != ":memory:":
                connection.close()
