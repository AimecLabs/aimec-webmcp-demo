"""Governed registry execution with durable, session-owned results and evidence."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request
from uuid import uuid4

from aimec_task_store import TaskConflict, TaskLimit, now
from webmcp import WebMcpError, _redact, _request_json, _require_identifier


DEMO_CAPABILITIES = frozenset({
    "aimec.business-diagnostics",
    "aimec.ai-opportunity-analyst",
    "aimec.ai-solution-architect",
})
EVIDENCE_FIELDS = frozenset({
    "event_id", "timestamp", "service", "event", "run_id", "task_id",
    "capability_id", "operation_id", "action", "kind", "transport",
    "result_sha256", "output_fields", "agent", "model",
})


class CapabilityJobs:
    def __init__(self, registry_url, store, event_store, *, opener, allowed=DEMO_CAPABILITIES):
        self.registry_url = registry_url.rstrip("/")
        self.store, self.events, self.opener = store, event_store, opener
        self.allowed = frozenset(allowed)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aimec-capability")

    def close(self):
        self.pool.shutdown(wait=True)

    def request(self, method, path, payload=None):
        return _request_json(method, self.registry_url + path, payload, opener=self.opener)

    def _long_request(self, path, payload, timeout=450):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(self.registry_url + path, data=body, headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST")
        try:
            with self.opener(request, timeout=timeout) as response:
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

    def catalog(self, kind):
        response = self.request("GET", "/v1/capabilities?kind=" + kind)
        records = response.get("capabilities")
        if not isinstance(records, list):
            raise WebMcpError(502, "capability_catalog_invalid")
        return [record for record in records if isinstance(record, dict) and record.get("id") in self.allowed and record.get("kind") == kind and record.get("status") == "approved"]

    def agents(self):
        agents = []
        for record in self.catalog("agent"):
            try:
                health = self.request("GET", "/v1/capabilities/health?capability_id=" + record["id"])
            except WebMcpError:
                continue
            if health.get("healthy") is not True:
                continue
            agents.append({
                "id": record["id"], "name": record["display_name"], "state": "online", "approval": "approved",
                "version": record["version"], "capabilities": record["capabilities"], "operations": record["operations"],
                "execution": "tool-grounded local Qwen inference via Ollama; public or synthetic planning inputs only",
            })
        agents.sort(key=lambda item: item["id"])
        return {"count": len(agents), "agents": agents, "source": "approved_capability_registry_a2a"}

    def _event(self, event, job, **fields):
        self.events.append({
            "event_id": uuid4().hex, "timestamp": now(), "service": "alpha-capability-jobs",
            "event": event, "run_id": job["job_id"], "task_id": job["job_id"], "kind": job["kind"],
            "capability_id": job["capability_id"], "operation_id": job["operation_id"], **fields,
        })

    def submit(self, kind, payload, owner):
        required = {"capability_id", "operation_id", "input"}
        if not required.issubset(payload) or set(payload) - required - {"request_id"}:
            raise WebMcpError(400, "invalid_capability_task_fields")
        capability_id = _require_identifier(payload["capability_id"], "capability_id")
        operation_id = _require_identifier(payload["operation_id"], "operation_id")
        supplied = payload["input"]
        if not isinstance(supplied, dict):
            raise WebMcpError(400, "invalid_tool_input")
        record = next((r for r in self.catalog(kind) if r["id"] == capability_id), None)
        if record is None:
            raise WebMcpError(404, "approved_capability_not_found")
        operation = next((o for o in record.get("operations", []) if isinstance(o, dict) and o.get("id") == operation_id), None)
        action = "invoke" if kind == "tool" else "delegate"
        if not operation or operation.get("action") != action:
            raise WebMcpError(404, "approved_operation_not_found")
        request_key = _require_identifier(payload.get("request_id", uuid4().hex), "request_id")
        try:
            job, created = self.store.begin(owner, kind, capability_id, operation_id, supplied, request_key)
        except TaskLimit as exc:
            raise WebMcpError(429, str(exc)) from exc
        except TaskConflict as exc:
            raise WebMcpError(409, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise WebMcpError(400, "invalid_task_input") from exc
        if created:
            if kind == "agent":
                self.pool.submit(self._execute, owner, job, supplied, action)
            else:
                self._execute(owner, job, supplied, action, raise_errors=True)
                job = self.store.get(owner, job["job_id"])
        elif kind == "tool" and job["state"] != "completed":
            raise WebMcpError(409, "task_not_completed_use_status")
        job["replayed"] = not created
        return job

    def _execute(self, owner, job, supplied, action, *, raise_errors=False):
        try:
            self.store.transition(owner, job["job_id"], "running")
            self._event("capability_job_started", job)
            payload = {
                "capability_id": job["capability_id"], "operation_id": job["operation_id"], "action": action,
                "correlation_id": job["job_id"], "idempotency_key": job["job_id"], "input": supplied,
            }
            response = self._long_request("/v1/capabilities/execute", payload, timeout=450 if job["kind"] == "agent" else 10)
            if response.get("correlation_id") != job["job_id"] or not isinstance(response.get("result"), dict):
                raise WebMcpError(502, "capability_result_invalid")
            completed = self.store.transition(owner, job["job_id"], "completed", result=response["result"])
            self._event("capability_job_completed", completed, result_sha256=completed["artifacts"][0]["sha256"], transport=response.get("transport"))
        except Exception as exc:
            if self.store.get(owner, job["job_id"])["state"] in {"queued", "running"}:
                self.store.transition(owner, job["job_id"], "failed", error="capability_execution_failed")
            if raise_errors:
                if isinstance(exc, WebMcpError):
                    raise
                raise WebMcpError(503, "capability_execution_failed") from exc

    def get(self, job_id, owner):
        job_id = _require_identifier(job_id, "job_id")
        try:
            return self.store.get(owner, job_id)
        except KeyError as exc:
            raise WebMcpError(404, "task_not_found") from exc
        except TaskConflict as exc:
            raise WebMcpError(503, "task_integrity_failed") from exc

    def evidence(self, job_id, owner):
        job = self.get(job_id, owner)
        events = [{k: v for k, v in event.items() if k in EVIDENCE_FIELDS} for event in self.events.list_events(run_id=job["job_id"], limit=100)]
        artifact_hash = job["artifacts"][0]["sha256"] if job["artifacts"] else None
        provider_event = "business_agent_completed" if job["kind"] == "agent" else "business_tool_completed"
        provider = [event for event in events if event.get("event") == provider_event]
        return {
            "job_id": job["job_id"], "task_id": job["task_id"], "state": job["state"], "timeline": job["timeline"],
            "artifacts": job["artifacts"], "events": events,
            "result_digest_verified": bool(artifact_hash and len(provider) == 1 and provider[0].get("result_sha256") == artifact_hash),
            "provider_execution_count": len(provider), "source": "persistent_execution_ledger",
        }
