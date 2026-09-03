from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


SENSITIVE = re.compile(
    r"(^|[_-])(api[_-]?key|token|secret|password|credential|private[_-]?key|authorization)($|[_-])",
    re.I,
)


class WebMcpError(RuntimeError):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact(nested)
            for key, nested in value.items()
            if not SENSITIVE.search(str(key))
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _require_identifier(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 160 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", result):
        raise WebMcpError(400, f"invalid_{label}")
    return result


def _resolve_capability_record(
    records: list[dict[str, Any]],
    *,
    kind: str,
    capability_id: str,
    operation_id: str,
) -> dict[str, Any] | None:
    """Resolve a registry ID, or its unambiguous operation capability alias.

    Discovery exposes a durable registry record ID and the semantic capability
    carried by each operation.  WebMCP callers commonly select the latter, so
    retain the registry ID as the canonical execution identity while accepting
    either value at the public boundary.
    """
    direct = next(
        (
            record for record in records
            if record.get("id") == capability_id and record.get("kind") == kind
        ),
        None,
    )
    if direct is not None:
        return direct

    aliases = [
        record
        for record in records
        if record.get("kind") == kind
        and capability_id in (record.get("capabilities") or [])
        and any(
            isinstance(operation, dict)
            and operation.get("id") == operation_id
            and operation.get("capability") == capability_id
            for operation in record.get("operations") or []
        )
    ]
    if len(aliases) > 1:
        raise WebMcpError(409, "ambiguous_capability_reference")
    return aliases[0] if aliases else None


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener(request, timeout=8) as response:
            raw = response.read(2_000_001)
    except HTTPError as exc:
        if exc.code in {400, 403, 404, 409, 422}:
            raise WebMcpError(exc.code, "upstream_request_rejected") from exc
        raise WebMcpError(502, "upstream_service_failed") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WebMcpError(503, "upstream_service_unavailable") from exc
    if len(raw) > 2_000_000:
        raise WebMcpError(502, "upstream_response_too_large")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebMcpError(502, "upstream_response_invalid") from exc
    if not isinstance(result, dict):
        raise WebMcpError(502, "upstream_response_invalid")
    return _redact(result)


class AlphaWebMcpAdapter:
    """Thin WebMCP-to-AIMEC bridge; all business work stays in existing services."""

    def __init__(
        self,
        capability_registry_url: str,
        *,
        agent_directory: Callable[[], dict[str, Any]],
        coordinator: Any,
        opener: Callable[..., Any] = urlopen,
        execution_jobs: Any = None,
    ) -> None:
        self.capability_registry_url = capability_registry_url.strip().rstrip("/")
        self.agent_directory = agent_directory
        self.coordinator = coordinator
        self.opener = opener
        self.execution_jobs = execution_jobs

    def _catalog(self) -> list[dict[str, Any]]:
        if self.execution_jobs is not None:
            return self.execution_jobs.catalog("tool")
        if not self.capability_registry_url:
            raise WebMcpError(503, "capability_registry_unavailable")
        payload = _request_json(
            "GET",
            f"{self.capability_registry_url}/v1/capabilities?kind=tool",
            opener=self.opener,
        )
        records = payload.get("capabilities")
        if not isinstance(records, list):
            raise WebMcpError(502, "capability_catalog_invalid")
        return [record for record in records if isinstance(record, dict)]

    def get_available_tools(self) -> dict[str, Any]:
        tools = []
        for record in self._catalog():
            if record.get("kind") != "tool" or record.get("status") != "approved":
                continue
            operations = []
            for operation in record.get("operations") or []:
                if not isinstance(operation, dict):
                    continue
                operations.append({
                    "id": operation.get("id"),
                    "action": operation.get("action"),
                    "capability": operation.get("capability"),
                    "invocation_capability_id": record.get("id"),
                    "input_schema": operation.get("input_schema") or {},
                    "output_schema": operation.get("output_schema") or {},
                    "timeout_seconds": operation.get("timeout_seconds"),
                })
            tools.append({
                "id": record.get("id"),
                "invocation_capability_id": record.get("id"),
                "display_name": record.get("display_name"),
                "version": record.get("version"),
                "capabilities": list(record.get("capabilities") or []),
                "operations": operations,
                "risk": _redact(record.get("risk") or {}),
            })
        tools.sort(key=lambda item: str(item.get("id") or ""))
        return {"count": len(tools), "tools": tools, "source": "approved_capability_registry"}

    def run_tool(self, payload: dict[str, Any], *, owner: str = "local") -> dict[str, Any]:
        if self.execution_jobs is not None:
            return self.execution_jobs.submit("tool", payload, owner)
        if set(payload) - {"capability_id", "operation_id", "input"}:
            raise WebMcpError(400, "unknown_run_tool_field")
        capability_id = _require_identifier(payload.get("capability_id"), "capability_id")
        operation_id = _require_identifier(payload.get("operation_id"), "operation_id")
        tool_input = payload.get("input", {})
        if not isinstance(tool_input, dict):
            raise WebMcpError(400, "invalid_tool_input")
        record = _resolve_capability_record(
            self._catalog(),
            kind="tool",
            capability_id=capability_id,
            operation_id=operation_id,
        )
        if (
            record is None
            or record.get("kind") != "tool"
            or record.get("status") != "approved"
        ):
            raise WebMcpError(404, "approved_tool_not_found")
        operation = next(
            (item for item in record.get("operations") or []
             if isinstance(item, dict) and item.get("id") == operation_id),
            None,
        )
        if not isinstance(operation, dict) or not operation.get("action"):
            raise WebMcpError(404, "approved_operation_not_found")
        request_id = f"WEBMCP-{uuid4().hex}"
        return _request_json(
            "POST",
            f"{self.capability_registry_url}/v1/capabilities/execute",
            {
                "capability_id": capability_id,
                "operation_id": operation_id,
                "action": operation["action"],
                "correlation_id": request_id,
                "idempotency_key": request_id,
                "input": tool_input,
            },
            opener=self.opener,
        )

    def get_available_agents(self) -> dict[str, Any]:
        if self.execution_jobs is not None:
            return self.execution_jobs.agents()
        projection = self.agent_directory()
        nodes = projection.get("nodes") if isinstance(projection, dict) else None
        if not isinstance(nodes, list):
            raise WebMcpError(503, "agent_directory_unavailable")
        agents = [
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "state": node.get("state"),
                "approval": "approved",
            }
            for node in nodes
            if isinstance(node, dict)
            and node.get("approval") == "approved"
            and node.get("state") == "online"
        ]
        agents.sort(key=lambda item: str(item.get("id") or ""))
        return {"count": len(agents), "agents": agents, "source": "approved_a2a_network"}

    def delegate_task(self, payload: dict[str, Any], *, owner: str = "local") -> dict[str, Any]:
        if self.execution_jobs is not None:
            return self.execution_jobs.submit("agent", payload, owner)
        if set(payload) != {"prompt"}:
            raise WebMcpError(400, "invalid_delegate_task_fields")
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt or len(prompt) > 4_000:
            raise WebMcpError(400, "invalid_task_prompt")
        if not self.get_available_agents()["agents"]:
            raise WebMcpError(409, "no_approved_online_agents")
        try:
            return _redact(self.coordinator.create(prompt))
        except ValueError as exc:
            raise WebMcpError(400, "task_rejected") from exc
        except RuntimeError as exc:
            raise WebMcpError(409, "task_could_not_start") from exc

    def _job(self, job_id: Any, owner: str = "local") -> dict[str, Any]:
        if self.execution_jobs is not None:
            return self.execution_jobs.get(job_id, owner)
        normalized = _require_identifier(job_id, "job_id")
        try:
            return _redact(self.coordinator.get(normalized))
        except KeyError as exc:
            raise WebMcpError(404, "task_not_found") from exc

    def get_task_status(self, job_id: Any, *, owner: str = "local") -> dict[str, Any]:
        job = self._job(job_id, owner)
        return {
            "job_id": job.get("job_id"),
            "task_id": job.get("task_id"),
            "state": job.get("state"),
            "updated_at": job.get("updated_at"),
            "timeline": job.get("timeline") or [],
        }

    def get_task_result(self, job_id: Any, *, owner: str = "local") -> dict[str, Any]:
        job = self._job(job_id, owner)
        if job.get("state") != "completed":
            raise WebMcpError(409, "task_result_not_ready")
        response = {
            "job_id": job.get("job_id"),
            "task_id": job.get("task_id"),
            "state": "completed",
            "answer": job.get("answer"),
            "artifacts": job.get("artifacts") or [],
        }
        if self.execution_jobs is not None:
            response["result"] = job["result"]
        return response

    def get_execution_evidence(self, job_id: Any, *, owner: str = "local") -> dict[str, Any]:
        if self.execution_jobs is not None:
            return self.execution_jobs.evidence(job_id, owner)
        job = self._job(job_id, owner)
        return {
            "job_id": job.get("job_id"),
            "task_id": job.get("task_id"),
            "state": job.get("state"),
            "timeline": job.get("timeline") or [],
            "artifacts": job.get("artifacts") or [],
            "source": "alpha_coordinator_and_a2a_artifacts",
        }
