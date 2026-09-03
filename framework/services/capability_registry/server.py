from __future__ import annotations

import os
from hmac import compare_digest
from uuid import uuid4

from aimec_capability_registry import (
    CapabilityExecutor,
    PersistentCapabilityRegistry,
)
from aimec_http import AimecHandler, serve


registry = PersistentCapabilityRegistry(
    os.getenv("AIMEC_CAPABILITY_REGISTRY_DB", "/var/lib/aimec/capabilities.json")
)
executor = CapabilityExecutor()
approval_token = os.environ.get("AIMEC_CAPABILITY_APPROVAL_TOKEN", "")


def submit(handler: AimecHandler, payload: dict) -> tuple[int, dict]:
    before = len(registry.records)
    record = registry.submit(payload.get("manifest"))
    created = len(registry.records) > before
    handler.state.logger.emit(
        "capability_submitted",
        capability_id=record["id"],
        kind=record["kind"],
        status=record["status"],
        duplicate=not created,
        digest=record["digest"],
    )
    return (201 if created else 200), record


def pending(_: AimecHandler, __: dict) -> tuple[int, dict]:
    records = registry.pending()
    return 200, {"count": len(records), "capabilities": records}


def discover(_: AimecHandler, payload: dict) -> tuple[int, dict]:
    query = payload.get("_query", {})
    kind = (query.get("kind") or [None])[0]
    capability = (query.get("capability") or [None])[0]
    if kind is not None and kind not in {"tool", "agent"}:
        raise ValueError("kind must be tool or agent")
    records = registry.discover(kind=kind, capability=capability)
    return 200, {"count": len(records), "capabilities": records}


def health(_: AimecHandler, payload: dict) -> tuple[int, dict]:
    capability_id = (payload.get("_query", {}).get("capability_id") or [""])[0]
    record = registry.records.get(capability_id)
    if record is None or record.status != "approved":
        return 404, {"error": "approved_capability_not_found"}
    return 200, {"capability_id": capability_id, "healthy": executor.healthy(record.manifest)}


def decide(handler: AimecHandler, payload: dict) -> tuple[int, dict]:
    presented = handler.headers.get("X-AIMEC-Approval-Token", "")
    if not approval_token or not compare_digest(presented, approval_token):
        raise ValueError("capability approval authorization is required")
    reviewer = str(payload.get("reviewer") or "")
    if not reviewer.startswith("admin:") or len(reviewer) > 160:
        raise ValueError("an administrator reviewer is required")
    record = registry.decide(
        str(payload.get("capability_id") or ""),
        reviewer=reviewer,
        approved=payload.get("approved") is True,
        granted_permissions=payload.get("granted_permissions"),
    )
    handler.state.logger.emit(
        "capability_approval_decided",
        capability_id=record["id"],
        kind=record["kind"],
        status=record["status"],
        reviewer=reviewer,
        granted_permissions=record["granted_permissions"],
    )
    return 200, record


def execute(handler: AimecHandler, payload: dict) -> tuple[int, dict]:
    correlation_id = str(payload.get("correlation_id") or f"RUN-{uuid4().hex[:12].upper()}")
    idempotency_key = str(payload.get("idempotency_key") or "")
    plan = registry.plan(
        str(payload.get("capability_id") or ""),
        str(payload.get("operation_id") or ""),
        action=str(payload.get("action") or ""),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    handler.state.logger.emit(
        "capability_execution_started",
        run_id=correlation_id,
        capability_id=plan["capability_id"],
        kind=plan["kind"],
        operation_id=plan["operation_id"],
        action=plan["action"],
        transport=plan["transport"]["protocol"],
    )
    result = executor.execute(plan, payload.get("input") or {})
    handler.state.logger.emit(
        "capability_execution_completed",
        run_id=correlation_id,
        capability_id=plan["capability_id"],
        kind=plan["kind"],
        operation_id=plan["operation_id"],
        action=plan["action"],
        transport=result["transport"],
        output_fields=sorted(result["result"]),
    )
    return 200, result


if __name__ == "__main__":
    serve(
        "capability-registry",
        {
            ("POST", "/v1/capabilities/submit"): submit,
            ("GET", "/v1/capabilities/pending"): pending,
            ("GET", "/v1/capabilities"): discover,
            ("GET", "/v1/capabilities/health"): health,
            ("POST", "/v1/internal/capabilities/decide"): decide,
            ("POST", "/v1/capabilities/execute"): execute,
        },
    )
