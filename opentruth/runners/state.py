"""State/invariant runner. Reads durable storage after HTTP actions. Not a dashboard."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from opentruth.assertions import evaluate
from opentruth.runners.http import HttpRunner
from opentruth.store import RunStore
from opentruth.verdicts import FAIL, INCONCLUSIVE

ALLOWED_TABLES = {"users", "identities"}


class StateRunner:
    def __init__(self, store: RunStore, db_path: Path, http: HttpRunner):
        self.store = store
        self.db_path = Path(db_path)
        self.http = http
        self.last_rows: list[dict[str, Any]] | None = None
        self.last_query: dict[str, Any] | None = None

    def _query(self, sql: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        if not self.db_path.is_file():
            return [], f"sqlite file missing: {self.db_path}"
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sql, params)
                rows = [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()
            return rows, None
        except sqlite3.Error as exc:
            return [], str(exc)

    def run_sql_query(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        cid = step["constraint_id"]
        sql = str(step["sql"])
        params = dict(step.get("params") or {})
        table_ok = any(f" FROM {table} " in f" {sql} " or f" FROM {table}\n" in sql for table in ALLOWED_TABLES)
        if not table_ok:
            rows, error = [], f"sql not limited to {sorted(ALLOWED_TABLES)}"
        else:
            rows, error = self._query(sql, params)
        self.last_rows = rows
        payload = {"sql": sql, "params": params, "rows": rows, "error": error}
        self.last_query = payload
        action_id = self.store.allocate("A-")
        blob = self.store.write_blob(
            "artifacts",
            f"{action_id}.state.json",
            (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8"),
        )
        self.store.append(
            "actions.jsonl",
            {
                "id": action_id,
                "constraint_id": cid,
                "type": "sql_query",
                "target": sql,
                "network_path": blob,
                "error": error,
            },
        )
        observations: list[dict[str, Any]] = []
        oid = self.store.allocate("O-")
        rec = self.store.append(
            "observations.jsonl",
            {
                "id": oid,
                "action_id": action_id,
                "constraint_id": cid,
                "kind": "state",
                "value": json.dumps(rows, sort_keys=True, default=str),
                "sql": sql,
                "rows": rows,
                "path": blob,
                "error": error,
            },
        )
        observations.append(rec)
        emitted: list[dict[str, Any]] = []
        if error:
            eid = self.store.allocate("E-")
            emitted.append(
                self.store.append(
                    "assertions.jsonl",
                    {
                        "id": eid,
                        "constraint_id": cid,
                        "action_id": action_id,
                        "step_id": step["id"],
                        "check": "action_executed",
                        "expect": "sql_query",
                        "cites": [oid],
                        "result": INCONCLUSIVE,
                        "detail": error,
                        "artifact": blob,
                    },
                )
            )
        _ = observations
        return emitted

    def run_assert_state(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        cid = step["constraint_id"]
        payload = self.last_query or {"rows": self.last_rows or [], "error": "no prior sql_query"}
        action_id = self.store.allocate("A-")
        blob = self.store.write_blob(
            "artifacts",
            f"{action_id}.state.json",
            (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8"),
        )
        self.store.append(
            "actions.jsonl",
            {
                "id": action_id,
                "constraint_id": cid,
                "type": "assert",
                "target": step.get("check", "assert"),
                "network_path": blob,
                "error": payload.get("error"),
            },
        )
        oid = self.store.allocate("O-")
        observations = [
            self.store.append(
                "observations.jsonl",
                {
                    "id": oid,
                    "action_id": action_id,
                    "constraint_id": cid,
                    "kind": "state",
                    "value": json.dumps(payload.get("rows") or [], sort_keys=True, default=str),
                    "sql": payload.get("sql"),
                    "rows": payload.get("rows") or [],
                    "path": blob,
                    "error": payload.get("error"),
                },
            )
        ]
        result, cites, detail = evaluate(
            step["check"],
            str(step.get("expect", "")),
            observations,
            extra=step,
        )
        eid = self.store.allocate("E-")
        artifact = blob if result in (FAIL, INCONCLUSIVE) else None
        rec = self.store.append(
            "assertions.jsonl",
            {
                "id": eid,
                "constraint_id": cid,
                "action_id": action_id,
                "step_id": step["id"],
                "check": step["check"],
                "expect": step.get("expect"),
                "cites": cites,
                "result": result,
                "detail": detail,
                "artifact": artifact,
            },
        )
        return [rec]

    def run_step(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        kind = step["kind"]
        if kind == "http_request":
            return self.http.run_step(step)
        if kind == "sql_query":
            return self.run_sql_query(step)
        if kind == "assert":
            check = step.get("check", "")
            if check in {"status_equals", "json_contains", "text_contains", "url_contains"}:
                return self.http.run_step(step)
            return self.run_assert_state(step)
        return self.http.run_step(step)


def execute_state_plan(store: RunStore, plan: dict[str, Any], db_path: Path) -> list[dict[str, Any]]:
    http = HttpRunner(store, plan["base_url"])
    runner = StateRunner(store, db_path, http)
    assertions: list[dict[str, Any]] = []
    for step in plan["steps"]:
        assertions.extend(runner.run_step(step))
    return assertions
