from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


class ExecutionEventStore:
    """Append-only execution ledger shared by every framework service."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("AIMEC_EVENT_DB", "/tmp/aimec-state/executions.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    service TEXT NOT NULL,
                    event TEXT NOT NULL,
                    run_id TEXT,
                    task_id TEXT,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_events_run
                    ON execution_events(run_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_execution_events_date
                    ON execution_events(substr(timestamp, 1, 10), sequence);
                """
            )

    def append(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO execution_events
                    (event_id, timestamp, service, event, run_id, task_id, record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["event_id"],
                    record["timestamp"],
                    record["service"],
                    record["event"],
                    record.get("run_id"),
                    record.get("task_id"),
                    json.dumps(record, ensure_ascii=False, sort_keys=True),
                ),
            )

    def list_events(
        self,
        *,
        run_id: str | None = None,
        date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            parameters.append(run_id)
        if date:
            datetime.strptime(date, "%Y-%m-%d")
            clauses.append("substr(timestamp, 1, 10) = ?")
            parameters.append(date)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        safe_limit = max(1, min(int(limit), 10_000))
        parameters.append(safe_limit)
        query = (
            "SELECT record_json FROM execution_events"
            + where
            + " ORDER BY sequence DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [json.loads(row["record_json"]) for row in reversed(rows)]

    def daily_summary(self, date: str) -> dict[str, Any]:
        events = self.list_events(date=date, limit=10_000)
        service_counts: dict[str, int] = {}
        run_ids: set[str] = set()
        completed: set[str] = set()
        failed: set[str] = set()
        for item in events:
            service = str(item["service"])
            service_counts[service] = service_counts.get(service, 0) + 1
            run_id = item.get("run_id")
            if run_id:
                run_ids.add(str(run_id))
                if item["event"] in {"run_completed", "queue_task_completed"}:
                    completed.add(str(run_id))
                if (
                    item["event"] in {"run_stopped", "request_failed"}
                    or str(item["event"]).endswith("_failed") and item.get("status") == "failed"
                ):
                    failed.add(str(run_id))
        run_summaries = [self.run_summary(run_id) for run_id in sorted(run_ids)]
        report_lines = [
            (
                f"{item['run_id']} ({item['task_id'] or 'unassigned'}): "
                f"{item['status']}; {item['tool_count']} tools; "
                f"USD {item['cost_usd']:.4f}; next: {item['next_step'] or 'none'}"
            )
            for item in run_summaries
        ]
        return {
            "date": date,
            "event_count": len(events),
            "run_count": len(run_ids),
            "completed_run_count": len(completed),
            "failed_run_count": len(failed),
            "services": dict(sorted(service_counts.items())),
            "runs": run_summaries,
            "report_lines": report_lines,
            "summary": (
                f"{date}: {len(events)} events across {len(run_ids)} runs; "
                f"{len(completed)} completed and {len(failed)} failed or stopped."
            ),
        }

    def run_summary(self, run_id: str) -> dict[str, Any]:
        normalized = str(run_id).strip()
        if not normalized:
            raise ValueError("run_id is required")
        events = self.list_events(run_id=normalized, limit=10_000)
        if not events:
            raise ValueError(f"run not found: {normalized}")

        received = next((item for item in events if item["event"] == "run_received"), events[0])
        terminal_names = {
            "run_completed", "run_stopped", "run_paused", "request_failed",
            "queue_task_completed", "queue_task_failed",
        }
        terminal = next((item for item in reversed(events) if item["event"] in terminal_names), events[-1])
        tool_events = [
            item for item in events
            if item["event"] in {"tool_completed", "tool_failed"}
        ]
        tools = [
            {
                "tool": str(item.get("tool") or ""),
                "operation": str(item.get("operation") or ""),
                "status": "completed" if item["event"] == "tool_completed" else "failed",
                "duration_ms": float(item.get("duration_ms") or 0),
                "output_fields": item.get("output_fields") or [],
                "error": item.get("error"),
            }
            for item in tool_events
        ]
        errors = [
            {
                "service": item["service"],
                "event": item["event"],
                "error": str(item.get("error") or item.get("reason") or "unspecified"),
            }
            for item in events
            if item.get("error") or item["event"].endswith("_failed") or item["event"] == "run_stopped"
        ]
        status = str(terminal.get("status") or {
            "run_completed": "completed",
            "run_paused": "waiting_for_human",
            "run_stopped": "failed",
            "request_failed": "failed",
        }.get(terminal["event"], "in_progress"))
        cost_usd = round(sum(float(item.get("cost_usd") or 0) for item in events), 6)
        summary = {
            "contract_version": "1.0",
            "run_id": normalized,
            "task_id": str(received.get("task_id") or terminal.get("task_id") or ""),
            "status": status,
            "status_change": str(terminal.get("status_change") or ""),
            "started_at": received["timestamp"],
            "finished_at": terminal["timestamp"] if terminal["event"] in terminal_names else None,
            "duration_ms": float(terminal.get("duration_ms") or 0),
            "cost_usd": cost_usd,
            "plan": received.get("plan") or [],
            "tools": tools,
            "tool_count": len(tools),
            "evidence": terminal.get("evidence") or {},
            "tests": terminal.get("tests") or {},
            "result": terminal.get("output") or {},
            "errors": errors,
            "next_step": str(terminal.get("next_step") or received.get("next_step") or ""),
            "event_count": len(events),
        }
        summary["summary"] = (
            f"{normalized}: {status}; {len(tools)} tools; {len(errors)} errors; "
            f"{summary['duration_ms']:.2f} ms; USD {cost_usd:.4f}."
        )
        return summary


class JsonEventLogger:
    def __init__(self, service: str) -> None:
        self.service = service
        self._lock = threading.Lock()
        log_dir = Path(os.getenv("AIMEC_LOG_DIR", "/tmp/aimec-logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{service}.jsonl"
        self.store = ExecutionEventStore()

    def emit(self, event: str, *, run_id: str | None = None, **fields: Any) -> None:
        record = {
            "event_id": f"EVT-{uuid4().hex.upper()}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service,
            "event": event,
            "run_id": run_id,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.store.append(record)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        print(line, flush=True)


class ServiceState:
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests = 0
        self.failures = 0
        self.logger = JsonEventLogger(name)

    def metrics(self) -> str:
        labels = f'service="{self.name}"'
        return (
            "# TYPE aimec_service_up gauge\n"
            f"aimec_service_up{{{labels}}} 1\n"
            "# TYPE aimec_service_requests_total counter\n"
            f"aimec_service_requests_total{{{labels}}} {self.requests}\n"
            "# TYPE aimec_service_failures_total counter\n"
            f"aimec_service_failures_total{{{labels}}} {self.failures}\n"
        )


RouteHandler = Callable[["AimecHandler", dict[str, Any]], tuple[int, Any]]


class AimecHandler(BaseHTTPRequestHandler):
    state: ServiceState
    routes: dict[tuple[str, str], RouteHandler] = {}

    def log_message(self, *_: Any) -> None:
        return

    def _json_body(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if size == 0:
            return {}
        if size > 2_000_000:
            raise ValueError("request body exceeds 2 MB")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, value: str, content_type: str) -> None:
        body = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, method: str) -> None:
        self.state.requests += 1
        parsed = urlsplit(self.path)
        if method == "GET" and parsed.path == "/health":
            self._send_json(200, {"status": "healthy", "service": self.state.name})
            return
        if method == "GET" and parsed.path == "/metrics":
            self._send_text(200, self.state.metrics(), "text/plain; version=0.0.4")
            return
        route = self.routes.get((method, parsed.path))
        if route is None:
            self._send_json(404, {"error": "route_not_found"})
            return
        payload: dict[str, Any] = {}
        try:
            payload = self._json_body() if method in {"POST", "PUT", "PATCH"} else {}
            payload["_query"] = parse_qs(parsed.query)
            status, response = route(self, payload)
            self._send_json(status, response)
        except (ValueError, json.JSONDecodeError) as exc:
            self.state.failures += 1
            self._send_json(400, {"error": "invalid_request", "detail": str(exc)})
        except Exception as exc:  # Services fail closed and expose no traceback.
            self.state.failures += 1
            raw_run_id = payload.get("run_id") or payload.get("correlation_id")
            run_id = str(raw_run_id).strip()[:160] if raw_run_id else None
            self.state.logger.emit(
                "request_failed",
                run_id=run_id,
                path=parsed.path,
                error=type(exc).__name__,
            )
            self._send_json(500, {"error": "internal_error", "detail": type(exc).__name__})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


def serve(name: str, routes: dict[tuple[str, str], RouteHandler]) -> None:
    host = os.getenv("AIMEC_HOST", "0.0.0.0")
    port = int(os.getenv("AIMEC_PORT", "8000"))
    handler = type(f"{name.title()}Handler", (AimecHandler,), {})
    handler.state = ServiceState(name)
    handler.routes = routes
    handler.state.logger.emit("service_started", host=host, port=port)
    ThreadingHTTPServer((host, port), handler).serve_forever()
